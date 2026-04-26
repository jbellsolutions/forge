"""Wire healing into the kernel via hook subscriptions."""
from __future__ import annotations

from ..kernel.hooks import HookBus, HookContext
from ..kernel.types import Verdict
from .circuit_breaker import CircuitRegistry
from .denial import DenialTracker
from .error_types import classify


def attach_healing(
    hooks: HookBus,
    circuits: CircuitRegistry | None = None,
    denials: DenialTracker | None = None,
) -> CircuitRegistry:
    """Subscribe healing primitives to the hook bus.

    Pre-tool:
      - If `denials` show this (agent, tool, args) hit `max_repeats` recently,
        emit ``SAFETY_BLOCKED`` (bypass-immune) — stops pathological loops
        where the agent re-issues the same denied call.
      - If a tool's circuit is OPEN, emit ``BLOCKED``.

    Post-tool:
      - If ``is_error``, classify and trip the breaker.
      - If the verdict is a denial, record it on the DenialTracker so the
        loop guard fires next time.

    Returns the ``CircuitRegistry`` (backward-compatible). The bound
    ``DenialTracker`` is exposed as ``circuits.denials`` for callers that
    want to inspect or reset it.
    """
    circuits = circuits or CircuitRegistry()
    denials = denials or DenialTracker()
    # Expose for caller introspection without breaking the prior return shape.
    circuits.denials = denials  # type: ignore[attr-defined]

    @hooks.on_pre_tool
    def _pre(ctx: HookContext) -> None:
        if not ctx.tool_call:
            return
        # Loop guard first — bypass-immune so AUTO mode can't override.
        if denials.should_short_circuit(ctx.agent_name, ctx.tool_call):
            ctx.safety_block(
                f"denial loop: {ctx.tool_call.name} with same args has been "
                f"blocked {denials.recent_count(ctx.agent_name, ctx.tool_call)} "
                f"times — adapt or escalate"
            )
            return
        # Then circuit breaker.
        cb = circuits.get(ctx.tool_call.name)
        if not cb.allow():
            ctx.block(
                f"circuit OPEN for {ctx.tool_call.name} "
                f"(failures={cb.consecutive_failures})"
            )

    @hooks.on_post_tool
    def _post(ctx: HookContext) -> None:
        if not ctx.tool_call:
            return
        # Record any denial verdicts so the loop guard can fire next time.
        if ctx.verdict in (Verdict.BLOCKED, Verdict.SAFETY_BLOCKED):
            denials.record(
                ctx.agent_name, ctx.tool_call,
                reason="; ".join(ctx.notes) if ctx.notes else ctx.verdict.value,
            )
        if not ctx.tool_result:
            return
        cb = circuits.get(ctx.tool_call.name)
        if ctx.tool_result.is_error:
            et = classify(ctx.tool_result.content)
            cb.record_failure(reason=et.value)
            ctx.notes.append(
                f"healing: classified={et.value}, breaker={cb.state.value}"
            )
        else:
            cb.record_success()

    return circuits
