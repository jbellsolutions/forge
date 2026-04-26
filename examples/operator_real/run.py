"""Operator vertical against REAL services.

What this exercises end-to-end:
- L0 kernel + hook bus
- L1 memory: Obsidian vault (live, ~/.forge/vault) + ReasoningBank
- L2 tools: REAL MCP filesystem server (npx @modelcontextprotocol/server-filesystem)
            + native Obsidian tools, native shell, native echo
            + optional Composio MCP if COMPOSIO_API_KEY is set
- L3 healing: CircuitRegistry attached
- L4 swarm: 3-member parallel council with role-injected prompts (optimist /
            skeptic / pragmatist) running on REAL Anthropic models
- L7 observability: TraceStore + Telemetry + optional OTel exporter

Costs: with ~3 short prompts to Sonnet + Haiku + Sonnet-contrarian, expect
       <$0.05 per run. Hard cap via `max_turns=4`.

Requirements:
- ANTHROPIC_API_KEY in env
- npx (Node 18+) on PATH
- pip install -e .[anthropic,mcp]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from forge.healing import attach_healing
from forge.kernel import HookBus
from forge.kernel.types import AssistantTurn
from forge.providers import load_profile
from forge.providers.mock import MockProvider
from forge.memory import ClaudeDir, ObsidianVault, ReasoningBank
from forge.observability import Telemetry, TraceStore
from forge.observability.otel import OTelExporter
from forge.swarm import (
    Consensus, RoleAssignment, RoleCouncilSpawner, SwarmSpec, Topology,
)
from forge.tools import ToolRegistry
from forge.tools.builtin.echo import EchoTool
from forge.tools.builtin.obsidian import (
    ObsidianBacklinksTool, ObsidianReadTool, ObsidianSearchTool, ObsidianWriteTool,
)
from forge.tools.builtin.shell import ShellTool
from forge.tools.mcp_client import MCPClientPool, load_mcp_servers


HOME = Path.home() / ".forge" / "operator-real"
VAULT = Path.home() / ".forge" / "vault"
HERE = Path(__file__).parent


def build_registry(vault: ObsidianVault) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(EchoTool())
    reg.register(ShellTool(cwd=str(HOME / "sandbox")))
    reg.register(ObsidianWriteTool(vault))
    reg.register(ObsidianReadTool(vault))
    reg.register(ObsidianSearchTool(vault))
    reg.register(ObsidianBacklinksTool(vault))
    return reg


def build_hooks(home: Path) -> tuple[HookBus, Telemetry]:
    hooks = HookBus()
    TraceStore(root=home / "traces").attach(hooks)
    telemetry = Telemetry(path=home / "telemetry.jsonl")
    telemetry.attach(hooks)
    OTelExporter(service_name="forge.operator-real").attach(hooks)
    attach_healing(hooks)
    return hooks, telemetry


_LIVE = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _scripted_council_provider(vote: str):
    """Mock provider that votes one word + brief rationale."""
    return MockProvider.scripted(load_profile("mock"), [
        AssistantTurn(text=f"{vote}\nReasonable to proceed.", tool_calls=[],
                      usage={"input_tokens": 60, "output_tokens": 12}),
    ])


async def main() -> int:
    if _LIVE:
        print("[operator] LIVE mode (ANTHROPIC_API_KEY present)")
    else:
        print("[operator] MOCK mode (ANTHROPIC_API_KEY empty); behaviour identical, no spend")

    HOME.mkdir(parents=True, exist_ok=True)
    VAULT.mkdir(parents=True, exist_ok=True)
    ClaudeDir(HOME / ".claude")
    vault = ObsidianVault(VAULT)
    bank = ReasoningBank(path=HOME / "reasoning_bank.json")

    registry = build_registry(vault)
    hooks, telemetry = build_hooks(HOME)

    # ---- B1+B2: real MCP servers ----
    servers = load_mcp_servers(HERE / "mcp.json")
    print(f"[operator] mcp servers loaded: {[s.name for s in servers]}")
    if servers:
        async with MCPClientPool(servers) as pool:
            mcp_tools = await pool.list_tools()
            print(f"[operator] mcp tools: {[t.name for t in mcp_tools]}")
            for t in mcp_tools:
                registry.register(t)
            verdict = await run_council_and_record(registry, hooks, vault, bank)
    else:
        verdict = await run_council_and_record(registry, hooks, vault, bank)

    print(f"[operator] council verdict: {verdict!r}")
    print("[operator] telemetry summary:")
    print(json.dumps(telemetry.summary(), indent=2))
    print(f"[operator] vault notes -> {VAULT}")
    return 0


async def run_council_and_record(
    registry: ToolRegistry, hooks, vault: ObsidianVault, bank: ReasoningBank,
) -> str:
    spec = SwarmSpec(
        topology=Topology.PARALLEL_COUNCIL,
        consensus=Consensus.MAJORITY,
        # Three slots; assignments below pin role + profile
        members=["anthropic", "anthropic-haiku", "anthropic-contrarian"],
    )
    spawner = RoleCouncilSpawner(
        tools=registry, hooks=hooks,
        base_instructions=(
            "You are a member of forge's daily-decision council. "
            "Decide whether to ship a small new feature today. "
            "Reply with EXACTLY one word: SHIP or WAIT, on its own line, then 1 sentence rationale."
        ),
        max_turns=2,
    )
    spawner.set_assignments([
        RoleAssignment(profile="anthropic",            role="optimist"),
        RoleAssignment(profile="anthropic-haiku",      role="skeptic"),
        RoleAssignment(profile="anthropic-contrarian", role="pragmatist"),
    ])

    # Mock-mode provider injection — same code path, deterministic outputs.
    if not _LIVE:
        votes = iter(["SHIP", "WAIT", "SHIP"])
        import forge.swarm.roles as _roles_mod
        def _mock_make(name, **kw):
            return _scripted_council_provider(next(votes))
        _roles_mod.make_provider = _mock_make  # type: ignore[assignment]

    task = (
        "We just finished a small backend feature. Tests pass, no schema changes. "
        "Should we deploy it today?"
    )
    result = await spawner.run(task, spec)
    verdict = (result.verdict.winner if result.verdict else "").strip()

    # Record in Obsidian + ReasoningBank
    body_lines = ["Council members:", ""]
    for name, lr in result.members:
        body_lines.append(f"- **{name}** -> {lr.final_text!r}")
    body_lines.append("")
    body_lines.append(f"**Verdict:** {verdict}")
    body_lines.append("Linked: [[topics/shipping-policy]]")
    vault.write_note(
        title="Daily ship decision",
        body="\n".join(body_lines),
        folder="decisions",
        tags=["council", "shipping"],
    )
    bank.consolidate(bank.distill(
        f"Council voted {verdict} on shipping today",
        tags=["decision", "shipping"],
    ))
    return verdict


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
