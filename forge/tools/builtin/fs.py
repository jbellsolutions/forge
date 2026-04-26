"""Filesystem tools — read, write, list. Sandboxed to a root."""
from __future__ import annotations

from pathlib import Path

from ...kernel.types import AgentDef, ToolCall, ToolResult
from ..base import Tool


class FSReadTool(Tool):
    name = "fs_read"
    description = "Read a file from the agent sandbox. Returns its content."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    tier = "computer_browser"

    def __init__(self, root: str | Path = ".forge/sandbox") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, p: str) -> Path:
        target = (self.root / p).resolve()
        if not str(target).startswith(str(self.root)):
            raise ValueError(f"path escapes sandbox: {p}")
        return target

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        try:
            path = self._resolve(call.arguments["path"])
            return ToolResult(call.id, self.name, path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return ToolResult(call.id, self.name, f"error: {e}", is_error=True)


class FSWriteTool(Tool):
    name = "fs_write"
    description = "Write content to a file in the agent sandbox."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }
    tier = "computer_browser"

    def __init__(self, root: str | Path = ".forge/sandbox") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        try:
            target = (self.root / call.arguments["path"]).resolve()
            if not str(target).startswith(str(self.root)):
                return ToolResult(call.id, self.name, "path escapes sandbox", is_error=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(call.arguments["content"], encoding="utf-8")
            return ToolResult(call.id, self.name, f"wrote {target.relative_to(self.root)}")
        except Exception as e:  # noqa: BLE001
            return ToolResult(call.id, self.name, f"error: {e}", is_error=True)
