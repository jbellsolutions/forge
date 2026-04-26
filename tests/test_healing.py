"""Phase 3 — healing layer."""
from __future__ import annotations

import time

import pytest

from forge.healing import (
    CircuitBreaker, CircuitRegistry, CircuitState, ErrorType, attach_healing, classify,
)
from forge.kernel import (
    AgentDef, AgentLoop, AssistantTurn, HookBus, PermissionMode, ToolCall,
)
from forge.providers import load_profile
from forge.providers.mock import MockProvider
from forge.tools import Tool, ToolRegistry


def test_classify_taxonomy():
    assert classify("connection reset by peer") == ErrorType.TRANSIENT
    assert classify("HTTP 429 too many requests") == ErrorType.TRANSIENT
    assert classify("command not found: claude") == ErrorType.ENVIRONMENTAL
    assert classify("json decode error") == ErrorType.DATA
    assert classify("out of memory") == ErrorType.RESOURCE
    assert classify("agent reasoned wrong") == ErrorType.LOGIC


def test_circuit_breaker_trips_and_recovers():
    cb = CircuitBreaker(name="t", fail_threshold=3, cooldown_seconds=0.01)
    for _ in range(2):
        cb.record_failure("x")
    assert cb.state == CircuitState.CLOSED
    cb.record_failure("x")
    assert cb.state == CircuitState.OPEN
    assert cb.allow() is False
    time.sleep(0.02)
    # Now in HALF_OPEN with 50% probe rate; force a deterministic probe
    cb.recovery_throughput = 1.0
    assert cb.allow() is True
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


class _BadTool(Tool):
    name = "bad"
    description = "always fails"
    parameters = {"type": "object", "properties": {}}
    tier = "mcp"
    async def execute(self, call, agent):
        from forge.kernel.types import ToolResult
        return ToolResult(call.id, self.name, "connection reset", is_error=True)


@pytest.mark.asyncio
async def test_healing_hook_blocks_after_trips():
    tools = ToolRegistry()
    tools.register(_BadTool())
    hooks = HookBus()
    circuits = attach_healing(hooks, CircuitRegistry(fail_threshold=2, cooldown_seconds=10))

    profile = load_profile("mock")
    # Script: 4 tool-call turns + 1 final
    tcs = [ToolCall(id=f"c{i}", name="bad", arguments={}) for i in range(4)]
    script = [
        AssistantTurn(text="", tool_calls=[tcs[0]], usage={"input_tokens": 1, "output_tokens": 1}),
        AssistantTurn(text="", tool_calls=[tcs[1]], usage={"input_tokens": 1, "output_tokens": 1}),
        AssistantTurn(text="", tool_calls=[tcs[2]], usage={"input_tokens": 1, "output_tokens": 1}),
        AssistantTurn(text="", tool_calls=[tcs[3]], usage={"input_tokens": 1, "output_tokens": 1}),
        AssistantTurn(text="done", tool_calls=[], usage={"input_tokens": 1, "output_tokens": 1}),
    ]
    provider = MockProvider.scripted(profile, script)
    agent = AgentDef(name="a", instructions="", profile="mock", permission_mode=PermissionMode.AUTO)
    loop = AgentLoop(agent, provider, tools, hooks=hooks, max_turns=6)
    result = await loop.run("go")

    snap = circuits.snapshot()
    assert snap["bad"]["state"] in {"open", "half_open"}
    # Some tool calls should have been blocked
    blocked_msgs = [m for m in result.messages if m.role == "tool" and "BLOCKED" in m.content]
    assert blocked_msgs, "expected at least one blocked tool call after trip"
