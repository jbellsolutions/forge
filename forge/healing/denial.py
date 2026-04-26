"""DenialTracker — prevents pathological denied-tool loops.

When a hook returns BLOCKED for a tool call, the agent often re-issues the
same call with the same arguments, gets blocked again, and burns context
without progress. The DenialTracker remembers recent denials per agent and
short-circuits repeats with a stronger signal: "you have already been told
no — adapt or escalate."

Pattern lifted from Claude Code's `permissions.ts` denial state tracking.
Lives at L3 healing because it's a feedback loop on the L0 hook bus, same
as CircuitBreaker — both prevent thrash, just on different signals.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from ..kernel.types import ToolCall, Verdict


@dataclass
class _DenialRecord:
    tool: str
    arg_key: str  # canonicalized arguments hash
    ts: float
    reason: str


@dataclass
class DenialTracker:
    """Tracks (tool, arguments) → recent denials per agent.

    Defaults are conservative: 3 denials of the same (tool, args) within
    `window_seconds` trip the loop guard. Trip causes subsequent calls to
    return SAFETY_BLOCKED (bypass-immune) so an AUTO-mode agent can't drown
    the signal.
    """
    max_repeats: int = 3
    window_seconds: float = 600.0  # 10 min
    history_size: int = 64
    _by_agent: dict[str, deque[_DenialRecord]] = field(default_factory=dict)

    def _bucket(self, agent_name: str) -> deque[_DenialRecord]:
        b = self._by_agent.get(agent_name)
        if b is None:
            b = deque(maxlen=self.history_size)
            self._by_agent[agent_name] = b
        return b

    @staticmethod
    def _arg_key(call: ToolCall) -> str:
        # Stable canonical key for deduplication. Sort keys; coerce to str.
        try:
            items = sorted((str(k), str(v)) for k, v in (call.arguments or {}).items())
        except Exception:  # noqa: BLE001
            items = [("__raw__", str(call.arguments))]
        return "|".join(f"{k}={v}" for k, v in items)

    def record(self, agent_name: str, call: ToolCall, reason: str = "") -> None:
        """Log a denial. Call from a `PostToolUse`/`PreToolUse` hook when
        verdict is BLOCKED or SAFETY_BLOCKED."""
        self._bucket(agent_name).append(
            _DenialRecord(call.name, self._arg_key(call), time.time(), reason)
        )

    def recent_count(self, agent_name: str, call: ToolCall) -> int:
        """How many times this exact (tool, args) has been denied within the window."""
        cutoff = time.time() - self.window_seconds
        key = self._arg_key(call)
        return sum(
            1 for r in self._bucket(agent_name)
            if r.tool == call.name and r.arg_key == key and r.ts >= cutoff
        )

    def should_short_circuit(self, agent_name: str, call: ToolCall) -> bool:
        """True if this (tool, args) has been denied >= `max_repeats` times
        within the window. Caller should set Verdict.SAFETY_BLOCKED."""
        return self.recent_count(agent_name, call) >= self.max_repeats

    def reset(self, agent_name: str | None = None) -> None:
        if agent_name is None:
            self._by_agent.clear()
        else:
            self._by_agent.pop(agent_name, None)
