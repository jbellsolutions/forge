"""Full-fidelity trace store (lifted from Meta-Harness).

Per-session JSONL files. No summarization at write time — the optimizer reads raw.

Layout:
  <root>/<session_id>/messages.jsonl
  <root>/<session_id>/tool_calls.jsonl
  <root>/<session_id>/events.jsonl

Wires into the kernel via hook subscriptions.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from ..kernel.hooks import HookBus, HookContext


class TraceStore:
    def __init__(self, root: str | Path = ".forge/traces") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        d = self.root / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write(self, session_id: str, stream: str, record: dict[str, Any]) -> None:
        path = self.session_dir(session_id) / f"{stream}.jsonl"
        record = {"ts": time.time(), **record}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=_default) + "\n")

    def attach(self, hooks: HookBus) -> None:
        """Subscribe to lifecycle and tool events."""

        @hooks.on_session_start
        def _on_start(ctx: HookContext) -> None:
            self.write(ctx.session_id, "events", {
                "kind": "session_start", "agent": ctx.agent_name,
            })

        @hooks.on_pre_tool
        def _on_pre(ctx: HookContext) -> None:
            tc = ctx.tool_call
            self.write(ctx.session_id, "tool_calls", {
                "phase": "pre",
                "agent": ctx.agent_name,
                "id": tc.id if tc else None,
                "name": tc.name if tc else None,
                "arguments": tc.arguments if tc else None,
                "verdict": ctx.verdict.value,
            })

        @hooks.on_post_tool
        def _on_post(ctx: HookContext) -> None:
            tc = ctx.tool_call
            tr = ctx.tool_result
            self.write(ctx.session_id, "tool_calls", {
                "phase": "post",
                "agent": ctx.agent_name,
                "id": tc.id if tc else None,
                "name": tc.name if tc else None,
                "result": tr.content if tr else None,
                "is_error": tr.is_error if tr else None,
                "verdict": ctx.verdict.value,
                "notes": ctx.notes,
            })

        @hooks.on_session_end
        def _on_end(ctx: HookContext) -> None:
            usage = ctx.extra.get("usage", {})
            messages = ctx.extra.get("messages", [])
            for m in messages:
                self.write(ctx.session_id, "messages", _record_of(m))
            self.write(ctx.session_id, "events", {
                "kind": "session_end", "agent": ctx.agent_name, "usage": usage,
            })


def _record_of(obj: Any) -> dict[str, Any]:
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {"value": str(obj)}


def _default(o: Any) -> Any:
    if is_dataclass(o):
        return asdict(o)
    if hasattr(o, "__dict__"):
        return dict(o.__dict__)
    if hasattr(o, "value"):
        return o.value
    return str(o)
