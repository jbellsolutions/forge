"""Composio adapter — Tier 1 SaaS tool registry.

Two paths:
  1. composio_native — uses the `composio` Python SDK directly (preferred).
     Requires COMPOSIO_API_KEY. Lets you fetch any of 1000+ tools by name or app.
  2. composio_mcp    — Composio also publishes an MCP server; route through MCPClientPool.

Both produce forge Tool objects so the rest of the harness doesn't care.

Usage:
    composio = ComposioAdapter(api_key=os.environ["COMPOSIO_API_KEY"])
    tools = composio.tools(apps=["GMAIL", "NOTION"])           # by app
    tools = composio.tools(actions=["GMAIL_SEND_EMAIL"])       # by action
    for t in tools: registry.register(t)
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from ..kernel.types import AgentDef, ToolCall, ToolResult
from .base import Tool

log = logging.getLogger("forge.composio")


class _ComposioTool(Tool):
    tier = "mcp"

    def __init__(
        self, *,
        name: str, description: str, schema: dict[str, Any],
        action_id: str, runner,
    ) -> None:
        self.name = f"composio__{name.lower()}"   # type: ignore[misc]
        self.description = description            # type: ignore[misc]
        self.parameters = schema                  # type: ignore[misc]
        self._action_id = action_id
        self._runner = runner

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        try:
            result = await asyncio.to_thread(self._runner, self._action_id, call.arguments)
            text = result if isinstance(result, str) else str(result)
            return ToolResult(call.id, self.name, text)
        except Exception as e:  # noqa: BLE001
            return ToolResult(call.id, self.name, f"composio error: {type(e).__name__}: {e}",
                              is_error=True)


class ComposioAdapter:
    """Native Composio SDK adapter."""

    def __init__(self, api_key: str | None = None, entity_id: str = "default") -> None:
        try:
            from composio import ComposioToolSet  # type: ignore
        except ImportError as e:
            raise ImportError(
                "install composio: pip install composio_core composio_openai"
            ) from e
        self._toolset = ComposioToolSet(
            api_key=api_key or os.getenv("COMPOSIO_API_KEY"),
            entity_id=entity_id,
        )

    def tools(
        self,
        *,
        apps: list[str] | None = None,
        actions: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> list[Tool]:
        """Return forge Tool wrappers for matching Composio actions."""
        # The Composio SDK has slightly different shapes by version; this code
        # targets the post-0.5 API that exposes get_action_schemas / execute_action.
        kwargs: dict[str, Any] = {}
        if apps:
            kwargs["apps"] = apps
        if actions:
            kwargs["actions"] = actions
        if tags:
            kwargs["tags"] = tags
        schemas = self._toolset.get_action_schemas(**kwargs)

        def runner(action_id: str, arguments: dict[str, Any]) -> Any:
            return self._toolset.execute_action(action=action_id, params=arguments or {})

        out: list[Tool] = []
        for s in schemas:
            # SDK returns dicts or pydantic models depending on version
            d = s if isinstance(s, dict) else s.dict() if hasattr(s, "dict") else s.__dict__
            name = d.get("name") or d.get("action") or "unknown"
            description = d.get("description", "")
            params = d.get("parameters") or d.get("input_schema") or {"type": "object", "properties": {}}
            out.append(_ComposioTool(
                name=name, description=description, schema=params,
                action_id=name, runner=runner,
            ))
        return out


def composio_via_mcp(api_key: str | None = None):
    """Helper: build an MCPServerConfig pointing at Composio's MCP entrypoint.

    Lets you reuse the MCPClientPool plumbing instead of installing the SDK.
    """
    from .mcp_client import MCPServerConfig
    return MCPServerConfig(
        name="composio",
        command="npx",
        args=["-y", "@composio/mcp"],
        env={"COMPOSIO_API_KEY": api_key or os.getenv("COMPOSIO_API_KEY", "")},
    )
