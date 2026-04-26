"""Tool registry — three-tier fall-through (MCP -> Computer/Browser -> CLI shell).

Phase 0: just the registry interface + per-agent allow/deny enforcement.
Phase 2 will wire actual MCP / computer-use / CLI subprocess tiers.

Stance (locked decision): full tool access by default, deny-list per persona.
The hook bus enforces blast-radius gates separately.
"""
from __future__ import annotations

from typing import Any

from ..kernel.types import AgentDef, ToolCall, ToolResult
from .base import Tool, Tier


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if not tool.name:
            raise ValueError(f"tool {type(tool).__name__} has empty name")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"tool {name!r} not registered")
        return self._tools[name]

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def by_tier(self, tier: Tier) -> list[Tool]:
        return [t for t in self._tools.values() if t.tier == tier]

    def visible_to(self, agent: AgentDef) -> list[Tool]:
        """Apply persona allow/deny lists. Default = all tools (stance: full access)."""
        out = []
        for t in self._tools.values():
            if agent.allowed_tools is not None and t.name not in agent.allowed_tools:
                continue
            if t.name in agent.denied_tools:
                continue
            out.append(t)
        return out

    def schemas_for(self, agent: AgentDef) -> list[dict[str, Any]]:
        return [t.schema() for t in self.visible_to(agent)]

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        tool = self.get(call.name)
        # Re-enforce visibility at execution time (defense in depth).
        if tool not in self.visible_to(agent):
            return ToolResult(
                tool_call_id=call.id, name=call.name,
                content=f"tool {call.name!r} not visible to agent {agent.name!r}",
                is_error=True,
            )
        return await tool.execute(call, agent)
