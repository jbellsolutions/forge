"""Phase 7 — observability telemetry."""
from __future__ import annotations

from pathlib import Path

import pytest

from forge.kernel import (
    AgentDef, AgentLoop, HookBus, PermissionMode,
)
from forge.observability import Telemetry, TraceStore
from forge.observability.dashboard import summarize
from forge.providers import load_profile
from forge.providers.mock import MockProvider
from forge.tools import ToolRegistry
from forge.tools.builtin.echo import EchoTool


@pytest.mark.asyncio
async def test_telemetry_records_session_cost(tmp_path: Path):
    tools = ToolRegistry(); tools.register(EchoTool())
    hooks = HookBus()
    TraceStore(root=tmp_path / "traces").attach(hooks)
    tel = Telemetry(path=tmp_path / "telemetry.jsonl")
    tel.attach(hooks)
    profile = load_profile("mock")
    provider = MockProvider.echo_then_done(profile)
    agent = AgentDef(name="t", instructions="", profile="mock", permission_mode=PermissionMode.AUTO)
    loop = AgentLoop(agent, provider, tools, hooks=hooks, max_turns=4)
    await loop.run("hi")
    s = tel.summary()
    assert s["sessions"] == 1
    assert s["tool_counts"].get("echo", 0) >= 1
    assert (tmp_path / "telemetry.jsonl").exists()


def test_dashboard_summarize_handles_empty(tmp_path: Path):
    out = summarize(tmp_path)
    assert out["sessions"] == []
