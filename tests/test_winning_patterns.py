"""Regression tests for the 5 winning patterns lifted from Claude Code RE.

1. DenialTracker (L3 healing)
2. Tool.concurrency_safe flag
3. FSWriteTool read-before-write contract
4. HookBus.fire_stop / fire_pre_compact
5. Verdict.SAFETY_BLOCKED bypass-immune ranking
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from forge import (
    AgentDef,
    DenialTracker,
    HookBus,
    HookContext,
    Tool,
    ToolCall,
    ToolResult,
    Verdict,
    attach_healing,
)
from forge.tools.builtin.fs import FSReadTool, FSWriteTool


# ---------------------------------------------------------------------------
# 1. DenialTracker
# ---------------------------------------------------------------------------

def test_denial_tracker_short_circuit_after_max_repeats() -> None:
    dt = DenialTracker(max_repeats=3, window_seconds=600)
    call = ToolCall(id="1", name="shell", arguments={"cmd": "rm -rf /"})

    for _ in range(3):
        assert not dt.should_short_circuit("agent_a", call)
        dt.record("agent_a", call, reason="hard no")

    assert dt.should_short_circuit("agent_a", call)
    # Different args do NOT trip the loop guard.
    other = ToolCall(id="2", name="shell", arguments={"cmd": "ls"})
    assert not dt.should_short_circuit("agent_a", other)
    # Different agent does NOT trip.
    assert not dt.should_short_circuit("agent_b", call)


def test_denial_tracker_reset() -> None:
    dt = DenialTracker(max_repeats=2)
    call = ToolCall(id="1", name="t", arguments={"x": 1})
    dt.record("a", call); dt.record("a", call)
    assert dt.should_short_circuit("a", call)
    dt.reset("a")
    assert not dt.should_short_circuit("a", call)


@pytest.mark.asyncio
async def test_attach_healing_fires_safety_block_on_denial_loop() -> None:
    """End-to-end: 3 denials of the same call → 4th call gets SAFETY_BLOCKED."""
    hooks = HookBus()
    # External pre-hook that blocks all 'shell' calls — simulates a
    # permission rule the agent keeps hitting.
    @hooks.on_pre_tool
    def deny_shell(ctx: HookContext) -> None:
        if ctx.tool_call and ctx.tool_call.name == "shell":
            ctx.block("policy: shell denied")

    circuits = attach_healing(hooks)
    assert hasattr(circuits, "denials")

    call = ToolCall(id="x", name="shell", arguments={"cmd": "id"})

    # First 3: BLOCKED but not safety-blocked. The post-tool hook records each.
    for _ in range(3):
        ctx = HookContext(session_id="s", agent_name="loopy", tool_call=call)
        v = await hooks.fire_pre_tool(ctx)
        assert v == Verdict.BLOCKED, v
        # Simulate the loop's post-tool fire after the BLOCKED short-circuit.
        ctx.tool_result = ToolResult(call.id, call.name, "blocked", is_error=True)
        await hooks.fire_post_tool(ctx)

    # 4th call: DenialTracker fires SAFETY_BLOCKED before the policy hook.
    ctx = HookContext(session_id="s", agent_name="loopy", tool_call=call)
    v = await hooks.fire_pre_tool(ctx)
    assert v == Verdict.SAFETY_BLOCKED, v


# ---------------------------------------------------------------------------
# 2. Tool.concurrency_safe flag
# ---------------------------------------------------------------------------

def test_concurrency_safe_default_false_and_in_schema() -> None:
    class _Mut(Tool):
        name = "mut"
        async def execute(self, call, agent):  # type: ignore[override]
            return ToolResult(call.id, self.name, "")

    class _Pure(Tool):
        name = "pure"
        concurrency_safe = True
        async def execute(self, call, agent):  # type: ignore[override]
            return ToolResult(call.id, self.name, "")

    assert _Mut.concurrency_safe is False
    assert _Pure.concurrency_safe is True
    assert _Pure().schema()["concurrency_safe"] is True
    assert _Mut().schema()["concurrency_safe"] is False


def test_builtin_fs_read_marked_concurrency_safe() -> None:
    assert FSReadTool.concurrency_safe is True
    assert FSWriteTool.concurrency_safe is False


# ---------------------------------------------------------------------------
# 3. FSWriteTool read-before-write
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fs_write_blocks_overwrite_without_prior_read() -> None:
    with tempfile.TemporaryDirectory() as d:
        reader = FSReadTool(root=d)
        writer = FSWriteTool(root=d, read_tool=reader)
        agent = AgentDef(name="a", instructions="", profile="mock")

        # New-file write succeeds (no prior file existed).
        r = await writer.execute(
            ToolCall(id="1", name="fs_write", arguments={"path": "f.txt", "content": "v1"}),
            agent,
        )
        assert not r.is_error, r.content

        # Overwrite WITHOUT a read should fail.
        # (Use a fresh writer instance with a fresh reader to simulate a
        # different session / agent that never read the file.)
        reader2 = FSReadTool(root=d)
        writer2 = FSWriteTool(root=d, read_tool=reader2)
        r2 = await writer2.execute(
            ToolCall(id="2", name="fs_write", arguments={"path": "f.txt", "content": "v2"}),
            agent,
        )
        assert r2.is_error and "was not read" in r2.content

        # force=true bypasses.
        r3 = await writer2.execute(
            ToolCall(id="3", name="fs_write",
                     arguments={"path": "f.txt", "content": "v3", "force": True}),
            agent,
        )
        assert not r3.is_error
        assert Path(d, "f.txt").read_text() == "v3"


@pytest.mark.asyncio
async def test_fs_write_detects_stale_edit_after_external_change() -> None:
    """Read → external mutation → write should refuse with stale-edit guard."""
    import os, time
    with tempfile.TemporaryDirectory() as d:
        reader = FSReadTool(root=d)
        writer = FSWriteTool(root=d, read_tool=reader)
        agent = AgentDef(name="a", instructions="", profile="mock")
        p = Path(d, "g.txt")
        p.write_text("original")

        # Agent reads → records mtime.
        await reader.execute(
            ToolCall(id="r", name="fs_read", arguments={"path": "g.txt"}), agent
        )

        # External actor mutates (bumps mtime).
        time.sleep(0.01)
        p.write_text("changed by someone else")
        os.utime(p, None)  # ensure mtime moves

        # Agent's write should now refuse.
        r = await writer.execute(
            ToolCall(id="w", name="fs_write",
                     arguments={"path": "g.txt", "content": "agent v2"}),
            agent,
        )
        assert r.is_error and "stale-edit" in r.content


# ---------------------------------------------------------------------------
# 4. HookBus.fire_stop / fire_pre_compact
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_and_pre_compact_hooks_fire() -> None:
    bus = HookBus()
    fired: list[str] = []

    @bus.on_stop
    async def _stop(ctx: HookContext) -> None:
        fired.append("stop")

    @bus.on_pre_compact
    def _compact(ctx: HookContext) -> None:  # sync hook also accepted
        fired.append("compact")

    ctx = HookContext(session_id="s", agent_name="a")
    await bus.fire_stop(ctx)
    await bus.fire_pre_compact(ctx)
    assert fired == ["stop", "compact"]


# ---------------------------------------------------------------------------
# 5. Verdict.SAFETY_BLOCKED ranking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_blocked_outranks_blocked_and_warning() -> None:
    bus = HookBus()

    @bus.on_pre_tool
    async def warn(ctx: HookContext) -> Verdict:
        return Verdict.WARNING

    @bus.on_pre_tool
    async def safety(ctx: HookContext) -> Verdict:
        return Verdict.SAFETY_BLOCKED

    @bus.on_pre_tool
    async def downgrade_attempt(ctx: HookContext) -> Verdict:
        return Verdict.READY  # must NOT downgrade SAFETY_BLOCKED

    call = ToolCall(id="1", name="x", arguments={})
    v = await bus.fire_pre_tool(HookContext(session_id="s", agent_name="a", tool_call=call))
    assert v == Verdict.SAFETY_BLOCKED


def test_hook_context_safety_block_helper() -> None:
    ctx = HookContext(session_id="s", agent_name="a")
    ctx.warn("ok-ish")
    assert ctx.verdict == Verdict.WARNING
    ctx.block("nope")
    assert ctx.verdict == Verdict.BLOCKED
    ctx.safety_block("absolutely not")
    assert ctx.verdict == Verdict.SAFETY_BLOCKED
