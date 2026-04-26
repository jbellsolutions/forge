"""Browser tool — Tier 2. Phase 2 ships an HTTP fetch stub; real Browser-Use /
computer-use wiring is layered in via dedicated adapters later.
"""
from __future__ import annotations

import asyncio
from typing import Any
from urllib.request import Request, urlopen

from ...kernel.types import AgentDef, ToolCall, ToolResult
from ..base import Tool


class HttpFetchTool(Tool):
    name = "http_fetch"
    description = "Fetch a URL and return its body (truncated to 16KB)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 15},
        },
        "required": ["url"],
    }
    tier = "computer_browser"

    def __init__(self, max_bytes: int = 16 * 1024) -> None:
        self.max_bytes = max_bytes

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        url = call.arguments.get("url", "")
        timeout = int(call.arguments.get("timeout_seconds", 15))

        def _fetch() -> tuple[int, bytes]:
            req = Request(url, headers={"User-Agent": "forge/0.1"})
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310 -- forge sandbox
                return resp.status, resp.read(self.max_bytes + 1)

        try:
            status, body = await asyncio.to_thread(_fetch)
            text = body[: self.max_bytes].decode("utf-8", errors="replace")
            truncated = len(body) > self.max_bytes
            return ToolResult(
                call.id, self.name,
                f"HTTP {status}\n{text}" + ("\n[truncated]" if truncated else ""),
                metadata={"status": status, "url": url},
            )
        except Exception as e:  # noqa: BLE001
            return ToolResult(call.id, self.name, f"fetch error: {type(e).__name__}: {e}", is_error=True)
