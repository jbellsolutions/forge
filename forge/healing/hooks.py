"""Wire healing into the kernel via hook subscriptions."""
from __future__ import annotations

from ..kernel.hooks import HookBus, HookContext
from .circuit_breaker import CircuitRegistry
from .error_types import classify


def attach_healing(hooks: HookBus, circuits: CircuitRegistry | None = None) -> CircuitRegistry:
    """Subscribe a CircuitRegistry to PreToolUse / PostToolUse.

    Pre: if a tool's circuit is OPEN and `allow()` returns False, block.
    Post: feed success/failure back into the breaker; classify error type for telemetry.
    """
    circuits = circuits or CircuitRegistry()

    @hooks.on_pre_tool
    def _pre(ctx: HookContext) -> None:
        if not ctx.tool_call:
            return
        cb = circuits.get(ctx.tool_call.name)
        if not cb.allow():
            ctx.block(f"circuit OPEN for {ctx.tool_call.name} (failures={cb.consecutive_failures})")

    @hooks.on_post_tool
    def _post(ctx: HookContext) -> None:
        if not ctx.tool_call or not ctx.tool_result:
            return
        cb = circuits.get(ctx.tool_call.name)
        if ctx.tool_result.is_error:
            et = classify(ctx.tool_result.content)
            cb.record_failure(reason=et.value)
            ctx.notes.append(f"healing: classified={et.value}, breaker={cb.state.value}")
        else:
            cb.record_success()

    return circuits
