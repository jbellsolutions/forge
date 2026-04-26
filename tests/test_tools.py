"""Phase 2 — tool layer."""
from __future__ import annotations

from pathlib import Path

import pytest

from forge.kernel.types import AgentDef, ToolCall
from forge.tools import ToolRegistry
from forge.tools.builtin.fs import FSReadTool, FSWriteTool
from forge.tools.builtin.shell import ShellTool
from forge.tools.mcp_adapter import (
    InProcessMCPAdapter, InProcessMCPServer, MCPToolSpec,
)


def _agent() -> AgentDef:
    return AgentDef(name="t", instructions="", profile="mock")


@pytest.mark.asyncio
async def test_fs_write_then_read_roundtrip(tmp_path: Path):
    w = FSWriteTool(root=tmp_path)
    r = FSReadTool(root=tmp_path)
    res = await w.execute(ToolCall("1", "fs_write", {"path": "x.txt", "content": "hello"}), _agent())
    assert not res.is_error
    res = await r.execute(ToolCall("2", "fs_read", {"path": "x.txt"}), _agent())
    assert res.content == "hello"


@pytest.mark.asyncio
async def test_fs_blocks_path_escape(tmp_path: Path):
    w = FSWriteTool(root=tmp_path)
    res = await w.execute(ToolCall("1", "fs_write", {"path": "../escape.txt", "content": "x"}), _agent())
    assert res.is_error


@pytest.mark.asyncio
async def test_shell_runs_echo(tmp_path: Path):
    sh = ShellTool(cwd=tmp_path)
    res = await sh.execute(ToolCall("1", "shell", {"command": "echo forge-shell-ok"}), _agent())
    assert "forge-shell-ok" in res.content
    assert not res.is_error


@pytest.mark.asyncio
async def test_in_process_mcp_adapter_proxies_tool():
    server = InProcessMCPServer()

    async def handler(args):
        return f"got {args.get('q')}"

    server.register(MCPToolSpec(
        name="q_tool", description="", parameters={"type": "object", "properties": {"q": {"type": "string"}}},
        handler=handler,
    ))
    reg = ToolRegistry()
    for t in InProcessMCPAdapter(server).tools():
        reg.register(t)
    res = await reg.execute(ToolCall("1", "q_tool", {"q": "ping"}), _agent())
    assert "got ping" in res.content
