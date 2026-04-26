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
    concurrency_safe = True  # read-only

    def __init__(self, root: str | Path = ".forge/sandbox") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        # path -> stat_result.st_mtime_ns (read-before-write contract).
        # Set on read; checked on write to detect stale-edit races between
        # parallel sub-agents (lifted from Claude Code FileEditTool readFileState).
        self._read_state: dict[str, int] = {}

    def _resolve(self, p: str) -> Path:
        target = (self.root / p).resolve()
        if not str(target).startswith(str(self.root)):
            raise ValueError(f"path escapes sandbox: {p}")
        return target

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        try:
            path = self._resolve(call.arguments["path"])
            content = path.read_text(encoding="utf-8")
            try:
                self._read_state[str(path)] = path.stat().st_mtime_ns
            except OSError:
                pass
            return ToolResult(call.id, self.name, content)
        except Exception as e:  # noqa: BLE001
            return ToolResult(call.id, self.name, f"error: {e}", is_error=True)


class FSWriteTool(Tool):
    name = "fs_write"
    description = (
        "Write content to a file in the agent sandbox. If the target file "
        "already exists, the agent must have read it during this session "
        "(read-before-write contract) — this prevents stale-overwrite races "
        "between parallel sub-agents. Pass `force=true` to override."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "force": {
                "type": "boolean",
                "description": "Bypass read-before-write check. Default false.",
            },
        },
        "required": ["path", "content"],
    }
    tier = "computer_browser"
    concurrency_safe = False  # write — must serialize against other writes to same path

    def __init__(
        self,
        root: str | Path = ".forge/sandbox",
        read_tool: "FSReadTool | None" = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        # Optional sibling FSReadTool whose _read_state we consult for the
        # stale-edit check. If None, the contract is enforced loosely
        # (existing files require force=True).
        self._read_tool = read_tool

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        try:
            target = (self.root / call.arguments["path"]).resolve()
            if not str(target).startswith(str(self.root)):
                return ToolResult(call.id, self.name, "path escapes sandbox", is_error=True)
            force = bool(call.arguments.get("force", False))
            # Read-before-write: if the file exists and we have not seen a
            # fresh read of it, refuse unless `force=true`.
            if target.exists() and not force:
                key = str(target)
                cur_mtime: int | None = None
                try:
                    cur_mtime = target.stat().st_mtime_ns
                except OSError:
                    cur_mtime = None
                seen = self._read_tool._read_state.get(key) if self._read_tool else None
                if seen is None:
                    return ToolResult(
                        call.id, self.name,
                        f"refused: {target.relative_to(self.root)} exists but "
                        f"was not read in this session. Read it first or pass force=true.",
                        is_error=True,
                    )
                if cur_mtime is not None and seen != cur_mtime:
                    return ToolResult(
                        call.id, self.name,
                        f"refused: {target.relative_to(self.root)} changed since "
                        f"last read (stale-edit guard). Re-read or pass force=true.",
                        is_error=True,
                    )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(call.arguments["content"], encoding="utf-8")
            # Refresh read-state so subsequent writes from the same agent succeed
            # without forcing.
            if self._read_tool is not None:
                try:
                    self._read_tool._read_state[str(target)] = target.stat().st_mtime_ns
                except OSError:
                    pass
            return ToolResult(call.id, self.name, f"wrote {target.relative_to(self.root)}")
        except Exception as e:  # noqa: BLE001
            return ToolResult(call.id, self.name, f"error: {e}", is_error=True)
