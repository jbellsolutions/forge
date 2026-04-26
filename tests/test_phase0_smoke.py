"""Phase 0 verification: kernel + hooks + tool + mock provider end-to-end."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from forge.kernel import (
    AgentDef, AgentLoop, HookBus, HookContext, PermissionMode, Verdict,
)
from forge.observability import TraceStore
from forge.providers import load_profile
from forge.providers.mock import MockProvider
from forge.tools import ToolRegistry
from forge.tools.builtin.echo import EchoTool


def _build(profile_name: str = "mock"):
    tools = ToolRegistry()
    tools.register(EchoTool())
    hooks = HookBus()
    profile = load_profile(profile_name)
    provider = MockProvider.echo_then_done(profile, message="ping")
    agent = AgentDef(
        name="t-agent",
        instructions="smoke",
        profile=profile_name,
        permission_mode=PermissionMode.AUTO,
    )
    return tools, hooks, provider, agent


@pytest.mark.asyncio
async def test_kernel_runs_tool_and_returns_text():
    tools, hooks, provider, agent = _build()
    loop = AgentLoop(agent, provider, tools, hooks=hooks, max_turns=4)
    result = await loop.run("hi")
    assert "ping" in result.final_text
    assert result.turns == 2
    # input_tokens recorded across both calls
    assert result.usage["input_tokens"] >= 1


@pytest.mark.asyncio
async def test_hook_can_block_tool_call():
    tools, hooks, provider, agent = _build()
    blocked = []

    @hooks.on_pre_tool
    def _block(ctx: HookContext):
        ctx.block("test-block")
        blocked.append(ctx.tool_call.name)

    loop = AgentLoop(agent, provider, tools, hooks=hooks, max_turns=4)
    result = await loop.run("hi")
    assert blocked == ["echo"]
    # The tool result should reflect the block
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert "BLOCKED" in tool_msgs[0].content


@pytest.mark.asyncio
async def test_trace_store_writes_jsonl(tmp_path: Path):
    tools, hooks, provider, agent = _build()
    trace = TraceStore(root=tmp_path)
    trace.attach(hooks)
    loop = AgentLoop(agent, provider, tools, hooks=hooks, max_turns=4)
    result = await loop.run("hi")

    sessions = list(tmp_path.iterdir())
    assert len(sessions) == 1
    sess = sessions[0]
    assert (sess / "tool_calls.jsonl").exists()
    assert (sess / "events.jsonl").exists()
    assert (sess / "messages.jsonl").exists()
    # Tool call should have both pre and post phases
    import json
    lines = (sess / "tool_calls.jsonl").read_text().splitlines()
    phases = [json.loads(l).get("phase") for l in lines]
    assert "pre" in phases and "post" in phases


@pytest.mark.asyncio
async def test_deny_list_hides_tool_from_agent():
    tools, hooks, provider, agent = _build()
    agent.denied_tools = ["echo"]
    schemas = tools.schemas_for(agent)
    assert schemas == []


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_not_crash():
    from forge.kernel.types import ToolCall
    tools, hooks, _provider, agent = _build()
    fake = ToolCall(id="x", name="does_not_exist", arguments={})
    # Calling registry directly: should KeyError
    import pytest as _pt
    with _pt.raises(KeyError):
        await tools.execute(fake, agent)
