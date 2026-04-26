"""Tool base class — JSONSchema self-description (lifted from OpenHarness BaseTool)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Literal

if TYPE_CHECKING:
    from ..kernel.types import AgentDef, ToolCall, ToolResult


Tier = Literal["mcp", "computer_browser", "cli"]


class Tool(ABC):
    """Every tool declares: name, description, parameters (JSONSchema), tier."""

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    parameters: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    tier: ClassVar[Tier] = "mcp"
    # If True, the tool has no observable side effects on shared state for the
    # given inputs and may be batched in parallel with other concurrency-safe
    # calls. Default is False (conservative — write tools, shell, MCP RPCs that
    # mutate remote state). Read-only tools (fs_read, grep, http_fetch, search)
    # should override to True. Pattern lifted from Claude Code's Tool.isConcurrencySafe.
    concurrency_safe: ClassVar[bool] = False

    @abstractmethod
    async def execute(self, call: "ToolCall", agent: "AgentDef") -> "ToolResult":
        ...

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "tier": self.tier,
            "concurrency_safe": self.concurrency_safe,
        }
