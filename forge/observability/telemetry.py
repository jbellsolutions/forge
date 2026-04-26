"""Token + cost telemetry. OTel-shape spans without the otel dependency.

Per-session counters wired through the hook bus; can be flushed to a JSONL file.
A real OTel exporter is a one-class swap; this keeps forge usable without otel installed.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..kernel.hooks import HookBus, HookContext


# Cost per 1M tokens, by profile name. Edit as model prices move.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    # (input, output) in USD per 1M tokens
    "anthropic":         (3.0, 15.0),
    "anthropic-haiku":   (0.25, 1.25),
    "openrouter-deepseek": (0.27, 1.10),
    "openai-gpt4":       (0.15, 0.60),
    "ollama-llama3":     (0.0, 0.0),
    "mock":              (0.0, 0.0),
}


@dataclass
class SessionStat:
    session_id: str
    agent: str
    started_at: float = field(default_factory=time.time)
    ended_at: float = 0.0
    tool_calls: int = 0
    tool_errors: int = 0
    blocked: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class Telemetry:
    def __init__(self, prices: dict[str, tuple[float, float]] | None = None,
                 path: str | Path | None = None) -> None:
        self.prices = prices or DEFAULT_PRICES
        self.path = Path(path) if path else None
        self.sessions: dict[str, SessionStat] = {}
        self.tool_counts: dict[str, int] = defaultdict(int)

    def attach(self, hooks: HookBus) -> None:
        @hooks.on_session_start
        def _start(ctx: HookContext) -> None:
            self.sessions[ctx.session_id] = SessionStat(
                session_id=ctx.session_id, agent=ctx.agent_name,
            )

        @hooks.on_pre_tool
        def _pre(ctx: HookContext) -> None:
            ses = self.sessions.get(ctx.session_id)
            if ses and ctx.tool_call:
                ses.tool_calls += 1
                self.tool_counts[ctx.tool_call.name] += 1
                if ctx.verdict.value == "blocked":
                    ses.blocked += 1

        @hooks.on_post_tool
        def _post(ctx: HookContext) -> None:
            ses = self.sessions.get(ctx.session_id)
            if ses and ctx.tool_result and ctx.tool_result.is_error:
                ses.tool_errors += 1

        @hooks.on_session_end
        def _end(ctx: HookContext) -> None:
            ses = self.sessions.get(ctx.session_id)
            if not ses:
                return
            ses.ended_at = time.time()
            usage = ctx.extra.get("usage", {}) or {}
            ses.input_tokens = usage.get("input_tokens", 0)
            ses.output_tokens = usage.get("output_tokens", 0)
            # Resolve price by agent name suffix or profile name in `extra`
            profile = ctx.extra.get("profile") or ctx.agent_name.split(":")[-1]
            in_p, out_p = self.prices.get(profile, (0.0, 0.0))
            ses.cost_usd = (ses.input_tokens / 1e6) * in_p + (ses.output_tokens / 1e6) * out_p
            self._flush(ses)

    def _flush(self, ses: SessionStat) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ses.__dict__) + "\n")

    def summary(self) -> dict[str, Any]:
        total_in = sum(s.input_tokens for s in self.sessions.values())
        total_out = sum(s.output_tokens for s in self.sessions.values())
        total_cost = sum(s.cost_usd for s in self.sessions.values())
        return {
            "sessions": len(self.sessions),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_cost_usd": round(total_cost, 6),
            "tool_counts": dict(self.tool_counts),
        }
