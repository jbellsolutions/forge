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


@pytest.mark.asyncio
async def test_hook_return_verdict_honored() -> None:
    """Regression: hooks returning a Verdict (instead of mutating ctx) must be honored.

    Earlier `fire_pre_tool` discarded the handler return value and only read
    `ctx.verdict`, contradicting the documented "hooks return ready/warning/blocked"
    contract. Both patterns are now accepted; most-restrictive wins.
    """
    from forge.kernel import ToolCall

    bus = HookBus()

    @bus.on_pre_tool
    async def gate(ctx: HookContext) -> Verdict:
        if "rm" in str(ctx.tool_call.arguments):
            return Verdict.BLOCKED
        return Verdict.READY

    safe = ToolCall(id="1", name="echo", arguments={"text": "hi"})
    danger = ToolCall(id="2", name="shell", arguments={"cmd": "rm -rf /"})

    v1 = await bus.fire_pre_tool(HookContext(session_id="s", agent_name="a", tool_call=safe))
    v2 = await bus.fire_pre_tool(HookContext(session_id="s", agent_name="a", tool_call=danger))
    assert v1 == Verdict.READY
    assert v2 == Verdict.BLOCKED


@pytest.mark.asyncio
async def test_hook_most_restrictive_wins() -> None:
    """Multiple hooks: the most-restrictive verdict wins (BLOCKED > WARNING > READY)."""
    from forge.kernel import ToolCall

    bus = HookBus()

    @bus.on_pre_tool
    async def warn_hook(ctx: HookContext) -> Verdict:
        return Verdict.WARNING

    @bus.on_pre_tool
    async def ready_hook(ctx: HookContext) -> Verdict:
        return Verdict.READY  # must NOT downgrade WARNING

    call = ToolCall(id="1", name="echo", arguments={})
    v = await bus.fire_pre_tool(HookContext(session_id="s", agent_name="a", tool_call=call))
    assert v == Verdict.WARNING
