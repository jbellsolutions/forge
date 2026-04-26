"""Core message and tool types. Provider-neutral."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class Message:
    role: Role
    content: str | list[dict[str, Any]]
    name: str | None = None  # for tool messages
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssistantTurn:
    """Output of one model call."""
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)  # input_tokens, output_tokens


class Verdict(str, Enum):
    """Hook bus dry-run verdict (lifted from OpenHarness)."""
    READY = "ready"
    WARNING = "warning"
    BLOCKED = "blocked"


class PermissionMode(str, Enum):
    """From Claude Agent SDK. Default = ask before destructive; Auto = run; Plan = dry-run only."""
    DEFAULT = "default"
    AUTO = "auto"
    PLAN = "plan"


@dataclass
class AgentDef:
    """Sub-agent definition. Lifted from Claude Agent SDK pattern."""
    name: str
    instructions: str
    profile: str  # provider profile name
    allowed_tools: list[str] | None = None  # None = all tools
    denied_tools: list[str] = field(default_factory=list)
    permission_mode: PermissionMode = PermissionMode.AUTO
    metadata: dict[str, Any] = field(default_factory=dict)
