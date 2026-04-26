"""Trivial echo tool. Phase 0 smoke verification."""
from __future__ import annotations

from ...kernel.types import AgentDef, ToolCall, ToolResult
from ..base import Tool


class EchoTool(Tool):
    name = "echo"
    description = "Echoes back the provided text. Use for smoke-testing the harness."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to echo back."},
        },
        "required": ["text"],
    }
    tier = "mcp"

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        text = call.arguments.get("text", "")
        return ToolResult(
            tool_call_id=call.id, name=self.name,
            content=f"echo: {text}",
        )
