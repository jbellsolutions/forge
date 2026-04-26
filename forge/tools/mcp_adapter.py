"""MCP adapter — Tier 1 backbone.

Connects to a running MCP server and exposes its tools as forge Tools.
Phase 2 ships an in-process stub so the registry plumbing is exercised
without requiring a real MCP server. Real wiring goes through the official
MCP Python SDK in a follow-on.

Usage:
    adapter = InProcessMCPAdapter(server)
    for tool in adapter.tools():
        registry.register(tool)
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..kernel.types import AgentDef, ToolCall, ToolResult
from .base import Tool


@dataclass
class MCPToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[str]]


class InProcessMCPServer:
    """Trivial in-process MCP-shaped server. Useful for tests + local recipes."""

    def __init__(self) -> None:
        self._specs: dict[str, MCPToolSpec] = {}

    def register(self, spec: MCPToolSpec) -> MCPToolSpec:
        self._specs[spec.name] = spec
        return spec

    def list_tools(self) -> list[MCPToolSpec]:
        return list(self._specs.values())


class _MCPProxyTool(Tool):
    tier = "mcp"

    def __init__(self, spec: MCPToolSpec) -> None:
        self._spec = spec
        self.name = spec.name           # type: ignore[misc]
        self.description = spec.description  # type: ignore[misc]
        self.parameters = spec.parameters    # type: ignore[misc]

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        try:
            content = await self._spec.handler(call.arguments)
            return ToolResult(call.id, self.name, content)
        except Exception as e:  # noqa: BLE001
            return ToolResult(call.id, self.name, f"mcp error: {type(e).__name__}: {e}", is_error=True)


class InProcessMCPAdapter:
    def __init__(self, server: InProcessMCPServer) -> None:
        self._server = server

    def tools(self) -> list[Tool]:
        return [_MCPProxyTool(spec) for spec in self._server.list_tools()]
