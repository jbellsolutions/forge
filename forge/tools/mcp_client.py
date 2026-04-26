"""Real MCP client using the official modelcontextprotocol Python SDK.

Connects to a stdio MCP server (the `mcp` CLI launches one per command),
lists tools, and exposes them as forge Tools that proxy `call_tool` over the
session.

Server config schema (matches Claude Desktop's mcp.json):
  {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/some/path"],
    "env": {"FOO": "bar"},
    "transport": "stdio"
  }

Usage:
  servers = load_mcp_servers("mcp.json")
  async with MCPClientPool(servers) as pool:
      tools = await pool.list_tools()       # forge Tool objects
      for t in tools: registry.register(t)
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..kernel.types import AgentDef, ToolCall, ToolResult
from .base import Tool

log = logging.getLogger("forge.mcp")


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"  # only stdio supported in v0; sse/http later

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> MCPServerConfig:
        return cls(
            name=name,
            command=data["command"],
            args=list(data.get("args", [])),
            env=dict(data.get("env", {})),
            transport=data.get("transport", "stdio"),
        )


def load_mcp_servers(path: str | Path) -> list[MCPServerConfig]:
    """Load Claude-Desktop-style mcp.json: { "mcpServers": { "<name>": {...} } }.

    - Skips entries whose name starts with `_` (commented-out scaffolding).
    - Expands `${VAR}` in args + env via os.path.expandvars.
    - Drops servers whose required env vars are unset (so optional integrations
      stay quiet when keys are missing).
    """
    import os
    raw = json.loads(Path(path).read_text())
    servers = raw.get("mcpServers", raw)
    out: list[MCPServerConfig] = []
    for name, data in servers.items():
        if name.startswith("_"):
            continue
        # Expand ${VAR} in args + env values.
        args = [os.path.expandvars(a) for a in data.get("args", [])]
        env = {k: os.path.expandvars(v) for k, v in (data.get("env") or {}).items()}
        # Skip if any required env value resolved empty.
        if any(not v for v in env.values()):
            log.warning("mcp server %r skipped: required env unset (%s)", name,
                        [k for k, v in env.items() if not v])
            continue
        out.append(MCPServerConfig(
            name=name,
            command=data["command"],
            args=args,
            env=env,
            transport=data.get("transport", "stdio"),
        ))
    return out


class _MCPProxyTool(Tool):
    """A forge Tool that proxies to an MCP session."""
    tier = "mcp"

    def __init__(self, server_name: str, mcp_name: str, description: str,
                 schema: dict[str, Any], session_getter):
        # Namespace tool names so two servers can publish identically-named tools.
        self.name = f"{server_name}__{mcp_name}"             # type: ignore[misc]
        self.description = description                       # type: ignore[misc]
        self.parameters = schema or {"type": "object", "properties": {}}  # type: ignore[misc]
        self._mcp_name = mcp_name
        self._get_session = session_getter

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        try:
            session = await self._get_session()
            result = await session.call_tool(self._mcp_name, call.arguments)
            # MCP returns content blocks; flatten text blocks for forge.
            parts: list[str] = []
            for block in getattr(result, "content", []) or []:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            return ToolResult(call.id, self.name, "\n".join(parts) or "(no content)")
        except Exception as e:  # noqa: BLE001
            return ToolResult(call.id, self.name, f"mcp error: {type(e).__name__}: {e}",
                              is_error=True)


class MCPClientPool:
    """Async-context-managed pool of stdio MCP sessions.

    Lazy-imports the official `mcp` SDK so forge stays installable without it.
    """

    def __init__(self, servers: list[MCPServerConfig]) -> None:
        self.servers = servers
        self._stack: AsyncExitStack | None = None
        self._sessions: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> MCPClientPool:
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._stack:
            await self._stack.__aexit__(*exc)

    async def _connect(self, cfg: MCPServerConfig):
        try:
            from mcp import ClientSession, StdioServerParameters  # type: ignore
            from mcp.client.stdio import stdio_client            # type: ignore
        except ImportError as e:
            raise ImportError("install `mcp` SDK: pip install mcp") from e

        params = StdioServerParameters(
            command=cfg.command, args=cfg.args, env={**cfg.env},
        )
        assert self._stack is not None
        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        log.info("mcp server %r connected", cfg.name)
        return session

    async def session_for(self, name: str):
        async with self._lock:
            if name not in self._sessions:
                cfg = next(s for s in self.servers if s.name == name)
                self._sessions[name] = await self._connect(cfg)
            return self._sessions[name]

    async def list_tools(self) -> list[Tool]:
        out: list[Tool] = []
        for cfg in self.servers:
            try:
                session = await self.session_for(cfg.name)
                resp = await session.list_tools()
            except Exception as e:  # noqa: BLE001
                log.warning("mcp server %r unreachable: %s", cfg.name, e)
                continue
            for tool in resp.tools:
                out.append(_MCPProxyTool(
                    server_name=cfg.name,
                    mcp_name=tool.name,
                    description=tool.description or "",
                    schema=tool.inputSchema or {"type": "object", "properties": {}},
                    session_getter=lambda n=cfg.name: self.session_for(n),
                ))
        return out
