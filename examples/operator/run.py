"""Operator vertical — Phase 8 proof-of-harness.

Synthesizes patterns from autonomous-sdr (persona/council router), coo-agent
(three-tier tools + heartbeats), and Orgo (`.claude/` filesystem + healing +
learning). Runs end-to-end on the mock provider — no API keys required.

Exercises every layer:
- L0 kernel + hook bus
- L1 memory: ReasoningBank + .claude/ contract
- L2 tools: MCP (in-process), browser (HTTP fetch), shell (CLI tier)
- L3 healing: CircuitRegistry attached
- L4 swarm: parallel-council topology with majority consensus
- L5 skills: SkillStore + autosynth + eval gate
- L7 observability: TraceStore + Telemetry
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from forge.healing import attach_healing
from forge.kernel import AgentDef, AgentLoop, AssistantTurn, HookBus, PermissionMode, ToolCall
from forge.memory import ClaudeDir, ReasoningBank
from forge.observability import Telemetry, TraceStore
from forge.providers import load_profile
from forge.providers.mock import MockProvider
from forge.skills import (
    SkillRun, SkillStore, autosynth, default_proposer, evaluate, promote_if_passing,
)
from forge.swarm import Consensus, Spawner, SwarmSpec, Topology
from forge.tools import ToolRegistry
from forge.tools.builtin.browser import HttpFetchTool
from forge.tools.builtin.echo import EchoTool
from forge.tools.builtin.shell import ShellTool
from forge.tools.mcp_adapter import (
    InProcessMCPAdapter, InProcessMCPServer, MCPToolSpec,
)


HOME = Path(".forge/operator-demo")


def build_mcp_server() -> InProcessMCPServer:
    server = InProcessMCPServer()

    async def notion_search(args):
        q = args.get("query", "")
        return f"[mock notion] 3 hits for {q!r}: morning_brief, q4_plan, hiring_loop"

    async def airtable_lookup(args):
        return f"[mock airtable] record={args.get('record_id', 'rec_demo')}"

    server.register(MCPToolSpec(
        name="notion_search",
        description="Search the operator's Notion workspace.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        handler=notion_search,
    ))
    server.register(MCPToolSpec(
        name="airtable_lookup",
        description="Look up an Airtable record by id.",
        parameters={"type": "object", "properties": {"record_id": {"type": "string"}}, "required": ["record_id"]},
        handler=airtable_lookup,
    ))
    return server


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    # Tier 1: MCP
    for t in InProcessMCPAdapter(build_mcp_server()).tools():
        reg.register(t)
    # Tier 2: Computer/browser
    reg.register(HttpFetchTool())
    # Tier 3: CLI shell
    reg.register(ShellTool(cwd=str(HOME / "sandbox")))
    # Builtin smoke
    reg.register(EchoTool())
    return reg


def build_hooks(home: Path) -> tuple[HookBus, Telemetry]:
    hooks = HookBus()
    TraceStore(root=home / "traces").attach(hooks)
    telemetry = Telemetry(path=home / "telemetry.jsonl")
    telemetry.attach(hooks)
    attach_healing(hooks)
    return hooks, telemetry


def scripted_member(name: str, output: str) -> MockProvider:
    """Build a mock provider that echoes via the `echo` tool then returns `output`."""
    profile = load_profile("mock")
    tc = ToolCall(id=f"call_{name}", name="echo", arguments={"text": f"{name}: {output}"})
    script = [
        AssistantTurn(text="", tool_calls=[tc], usage={"input_tokens": 12, "output_tokens": 8}),
        AssistantTurn(text=output, tool_calls=[], usage={"input_tokens": 14, "output_tokens": 6}),
    ]
    return MockProvider.scripted(profile, script)


async def run_council(hooks: HookBus, registry: ToolRegistry, task: str) -> str:
    """Three-member parallel council. We override Spawner._run_member so we can
    inject scripted mock providers per member without spinning up real APIs."""
    spec = SwarmSpec(
        topology=Topology.PARALLEL_COUNCIL,
        consensus=Consensus.MAJORITY,
        members=["mock", "mock", "mock"],
    )
    spawner = Spawner(tools=registry, hooks=hooks)

    async def fake_member(profile_name, _task, role):
        # Two mocks vote "ship", one votes "wait" -> majority is "ship"
        votes = ["ship", "ship", "wait"]
        idx = fake_member._calls         # type: ignore[attr-defined]
        fake_member._calls += 1          # type: ignore[attr-defined]
        agent = AgentDef(
            name=f"council:{idx}",
            instructions="vote ship or wait",
            profile="mock",
            permission_mode=PermissionMode.AUTO,
        )
        provider = scripted_member(f"m{idx}", votes[idx % 3])
        loop = AgentLoop(agent, provider, registry, hooks=hooks, max_turns=4)
        return await loop.run(_task)

    fake_member._calls = 0  # type: ignore[attr-defined]
    spawner._run_member = fake_member  # type: ignore[assignment]
    result = await spawner.run(task, spec)
    return result.verdict.winner if result.verdict else ""


async def main() -> int:
    HOME.mkdir(parents=True, exist_ok=True)
    claude = ClaudeDir(HOME / ".claude")
    bank = ReasoningBank(path=HOME / "reasoning_bank.json")
    skills = SkillStore(root=HOME / ".claude" / "skills")

    # Seed initial skill
    skills.write_skill("daily_decision",
                       "# daily_decision\n\nGiven the morning brief, output ship or wait.\n",
                       version="v1")

    registry = build_registry()
    hooks, telemetry = build_hooks(HOME)

    # Heartbeat: morning brief -> council -> verdict -> bank + claude/
    print("[operator] heartbeat: morning_brief")
    verdict = await run_council(hooks, registry,
                                "Should we ship the new feature today?")
    print(f"[operator] council verdict: {verdict!r}")

    bank.consolidate(bank.distill(f"Council voted {verdict} on shipping today",
                                  tags=["decision", "shipping"]))
    claude.append_observation({"event": "council_decision", "verdict": verdict})

    # Skill autosynth + eval gate demo (synthetic 60 runs, mostly positive)
    for i in range(60):
        skills.log_run(SkillRun(
            skill="daily_decision", version="v1",
            input_hash=SkillStore.hash_input(f"in_{i}"),
            output=f"verdict {i}", outcome_score=0.4 + (0.05 if i % 3 == 0 else -0.02),
        ))
    synth = autosynth(skills, "daily_decision", proposer=default_proposer,
                      min_runs=10, positive_floor=0.0)
    if synth:
        # Synthetic candidate runs: mostly better
        for i in range(60):
            skills.log_run(SkillRun(
                skill="daily_decision", version=synth.new_version,
                input_hash=SkillStore.hash_input(f"in_{i}"),
                output=f"verdict {i}", outcome_score=0.55,
            ))
        report = promote_if_passing(skills, "daily_decision", synth.new_version)
        print(f"[operator] eval gate: promoted={report.promoted} reason={report.reason}")
        print(f"[operator] current skill version: {skills.current_version('daily_decision')}")

    print("[operator] telemetry summary:")
    import json as _j
    print(_j.dumps(telemetry.summary(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
