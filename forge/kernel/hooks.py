"""Hook bus — the extensibility seam.

Lifecycle events: SessionStart, PreToolUse, PostToolUse, SessionEnd.
Pre-hooks may return a Verdict to gate the call (READY / WARNING / BLOCKED).
Post-hooks may rewrite the ToolResult (e.g. retry, redaction, enrichment).

Lifted from OpenHarness (dry-run verdict) + Claude Agent SDK (lifecycle).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .types import ToolCall, ToolResult, Verdict

log = logging.getLogger("forge.hooks")


@dataclass
class HookContext:
    """Mutable context passed through every hook."""
    session_id: str
    agent_name: str
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    verdict: Verdict = Verdict.READY
    notes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def warn(self, msg: str) -> None:
        self.notes.append(msg)
        if self.verdict == Verdict.READY:
            self.verdict = Verdict.WARNING

    def block(self, msg: str) -> None:
        self.notes.append(msg)
        self.verdict = Verdict.BLOCKED


# Hook signatures. Hooks may be sync or async; the bus awaits both.
PreHook = Callable[[HookContext], Awaitable[None] | None]
PostHook = Callable[[HookContext], Awaitable[None] | None]
SessionHook = Callable[[HookContext], Awaitable[None] | None]


class HookBus:
    """Registry + dispatcher.

    Hooks fire in registration order. A pre-hook that sets verdict=BLOCKED short-circuits
    the tool call; downstream pre-hooks still run (so observability hooks see the block)
    but the tool itself is not executed.
    """

    def __init__(self) -> None:
        self._session_start: list[SessionHook] = []
        self._session_end: list[SessionHook] = []
        self._pre_tool: list[PreHook] = []
        self._post_tool: list[PostHook] = []

    # registration ---------------------------------------------------------
    def on_session_start(self, fn: SessionHook) -> SessionHook:
        self._session_start.append(fn); return fn

    def on_session_end(self, fn: SessionHook) -> SessionHook:
        self._session_end.append(fn); return fn

    def on_pre_tool(self, fn: PreHook) -> PreHook:
        self._pre_tool.append(fn); return fn

    def on_post_tool(self, fn: PostHook) -> PostHook:
        self._post_tool.append(fn); return fn

    # dispatch -------------------------------------------------------------
    async def fire_session_start(self, ctx: HookContext) -> None:
        for h in self._session_start:
            await _maybe_await(h(ctx))

    async def fire_session_end(self, ctx: HookContext) -> None:
        for h in self._session_end:
            await _maybe_await(h(ctx))

    async def fire_pre_tool(self, ctx: HookContext) -> Verdict:
        for h in self._pre_tool:
            await _maybe_await(h(ctx))
        return ctx.verdict

    async def fire_post_tool(self, ctx: HookContext) -> None:
        for h in self._post_tool:
            await _maybe_await(h(ctx))


async def _maybe_await(x: Any) -> Any:
    if hasattr(x, "__await__"):
        return await x
    return x
