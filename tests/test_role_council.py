"""Role-injected council member spawner."""
from __future__ import annotations

import pytest

from forge.kernel import HookBus
from forge.kernel.types import AssistantTurn
from forge.providers import load_profile
from forge.providers.mock import MockProvider
from forge.swarm import (
    Consensus, RoleAssignment, RoleCouncilSpawner, SwarmSpec, Topology,
)
from forge.tools import ToolRegistry
from forge.tools.builtin.echo import EchoTool


@pytest.mark.asyncio
async def test_role_council_emits_three_distinct_agents(monkeypatch):
    tools = ToolRegistry(); tools.register(EchoTool())
    hooks = HookBus()
    spawner = RoleCouncilSpawner(
        tools=tools, hooks=hooks,
        base_instructions="vote ship or wait",
        max_turns=2,
    )
    spawner.set_assignments([
        RoleAssignment(profile="mock", role="optimist"),
        RoleAssignment(profile="mock", role="skeptic"),
        RoleAssignment(profile="mock", role="pragmatist"),
    ])

    # Patch make_provider to return a fresh scripted MockProvider each call,
    # voting in alternating order so consensus picks "ship" 2-1.
    profile = load_profile("mock")
    votes = iter(["ship", "wait", "ship"])

    def fake_make_provider(name, **kw):
        v = next(votes)
        return MockProvider.scripted(profile, [
            AssistantTurn(text=v, tool_calls=[], usage={"input_tokens": 1, "output_tokens": 1}),
        ])

    monkeypatch.setattr("forge.swarm.roles.make_provider", fake_make_provider)

    spec = SwarmSpec(
        topology=Topology.PARALLEL_COUNCIL,
        consensus=Consensus.MAJORITY,
        members=["mock", "mock", "mock"],
    )
    result = await spawner.run("should we ship?", spec)
    assert result.verdict.winner == "ship"
    # Each member's first system message should contain its role prompt
    systems: list[str] = []
    for _, lr in result.members:
        sys_msgs = [m.content for m in lr.messages if m.role == "system" and isinstance(m.content, str)]
        systems.append(sys_msgs[0] if sys_msgs else "")
    joined = " | ".join(systems).upper()
    assert "OPTIMIST" in joined
    assert "SKEPTIC" in joined
    assert "PRAGMATIST" in joined
