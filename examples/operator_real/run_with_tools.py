"""Council members that ACTUALLY use tools — not just vote.

Difference from run.py:
- Each member has access to: MCP filesystem (read project files), Obsidian search
  (read prior decisions), shell (read git log).
- Task is non-trivial: analyze recent activity and produce a daily-decision
  recommendation grounded in evidence.
- Members use up to 4 turns each so they can call tools, read results, then vote.
- Verdict is recorded to Obsidian, ReasoningBank, and (after a threshold sweep)
  promoted to topics/.

Live mode requires ANTHROPIC_API_KEY; otherwise scripted mocks call the echo tool
once per member to prove the wiring without spending tokens.

Run:
    python examples/operator_real/run_with_tools.py
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
from forge.kernel.types import AssistantTurn, ToolCall
from forge.memory import (
    ClaudeDir, ObsidianVault, ReasoningBank, index_into_reasoning_bank, promote,
)
from forge.observability import Telemetry, TraceStore
from forge.observability.otel import OTelExporter
from forge.providers import load_profile, make_provider
from forge.providers.mock import MockProvider
from forge.swarm import Consensus, RoleAssignment, RoleCouncilSpawner, SwarmSpec, Topology
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

_LIVE = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def build_hooks(home: Path):
    hooks = HookBus()
    TraceStore(root=home / "traces").attach(hooks)
    tel = Telemetry(path=home / "telemetry.jsonl"); tel.attach(hooks)
    OTelExporter(service_name="forge.operator-real-tools").attach(hooks)
    attach_healing(hooks)
    return hooks, tel


def build_registry(vault: ObsidianVault) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(EchoTool())
    reg.register(ShellTool(cwd=str(HOME / "sandbox")))
    reg.register(ObsidianWriteTool(vault))
    reg.register(ObsidianReadTool(vault))
    reg.register(ObsidianSearchTool(vault))
    reg.register(ObsidianBacklinksTool(vault))
    return reg


def _scripted_tool_using(role: str):
    """Mock that calls obsidian_search once, then votes — exercises the tool path."""
    profile = load_profile("mock")
    tc = ToolCall(id=f"call_{role}", name="obsidian_search",
                  arguments={"query": "ship", "k": 3})
    script = [
        AssistantTurn(text="", tool_calls=[tc],
                      usage={"input_tokens": 40, "output_tokens": 8}),
        AssistantTurn(text=f"{role.upper()}: SHIP\nPrior decisions support shipping.",
                      tool_calls=[], usage={"input_tokens": 50, "output_tokens": 14}),
    ]
    return MockProvider.scripted(profile, script)


async def main() -> int:
    print(f"[operator-tools] mode={'LIVE' if _LIVE else 'MOCK'}")
    HOME.mkdir(parents=True, exist_ok=True)
    VAULT.mkdir(parents=True, exist_ok=True)
    ClaudeDir(HOME / ".claude")
    vault = ObsidianVault(VAULT)
    bank = ReasoningBank(path=HOME / "reasoning_bank.json")

    # Pre-populate vault with a prior decision so search has a hit
    vault.write_note(
        "prior-ship-q3",
        "Q3 we shipped on Friday EOD; positive outcome.",
        folder="decisions", tags=["shipping", "history"],
    )

    registry = build_registry(vault)
    hooks, telemetry = build_hooks(HOME)

    # Real MCP servers (filesystem rooted at vault)
    servers = load_mcp_servers(HERE / "mcp.json")
    print(f"[operator-tools] mcp servers: {[s.name for s in servers]}")
    pool_cm = MCPClientPool(servers) if servers else _NullCM()
    async with pool_cm as pool:
        if servers:
            for t in await pool.list_tools():
                registry.register(t)
        await run_council_with_tools(registry, hooks, vault, bank)

    # Promote any memories that crossed threshold during this run.
    # Index inbox notes the agent wrote into the bank first, so they participate.
    indexed = index_into_reasoning_bank(vault, bank, folder="inbox")
    # Bump confidence on the freshly-indexed shipping memory by judging it.
    for mid, mem in list(bank._mems.items())[-3:]:
        if "shipping" in mem.tags or "decision" in mem.tags:
            bank.judge(mid, +1.0)
    res = promote(bank, vault, threshold=0.55, min_used=1)
    print(f"[operator-tools] promotion: new={len(res.promoted)} updated={len(res.updated)} "
          f"skipped={res.skipped}")

    print("[operator-tools] telemetry:")
    print(json.dumps(telemetry.summary(), indent=2))
    return 0


class _NullCM:
    async def __aenter__(self): return self
    async def __aexit__(self, *e): return None
    async def list_tools(self): return []


async def run_council_with_tools(registry, hooks, vault, bank):
    spec = SwarmSpec(
        topology=Topology.PARALLEL_COUNCIL, consensus=Consensus.MAJORITY,
        members=["anthropic", "anthropic-haiku", "anthropic-contrarian"],
    )
    spawner = RoleCouncilSpawner(
        tools=registry, hooks=hooks,
        base_instructions=(
            "You are a council member deciding whether to ship today. "
            "Use tools when helpful: obsidian_search to check prior decisions, "
            "shell to inspect git, fs_vault tools to read project files. "
            "Reply with EXACTLY one word (SHIP or WAIT) on its own line, then "
            "1-2 sentences citing what you found."
        ),
        max_turns=8,
    )
    spawner.set_assignments([
        RoleAssignment(profile="anthropic",            role="optimist"),
        RoleAssignment(profile="anthropic-haiku",      role="skeptic"),
        RoleAssignment(profile="anthropic-contrarian", role="pragmatist"),
    ])

    if not _LIVE:
        votes = iter(["optimist", "skeptic", "pragmatist"])
        import forge.swarm.roles as _roles_mod
        def _mock_make(name, **kw):
            return _scripted_tool_using(next(votes))
        _roles_mod.make_provider = _mock_make  # type: ignore[assignment]

    task = (
        "Should we deploy today? Use obsidian_search to check what we did on "
        "previous Fridays, then vote SHIP or WAIT."
    )
    result = await spawner.run(task, spec)
    verdict = result.verdict.winner if result.verdict else ""
    print(f"[operator-tools] verdict: {verdict!r}")

    body_lines = ["## Council members\n"]
    for name, lr in result.members:
        body_lines.append(f"- **{name}** -> `{lr.final_text!r}`")
    body_lines.append(f"\n**Verdict:** {verdict}")
    vault.write_note(
        "council-with-tools",
        "\n".join(body_lines), folder="decisions",
        tags=["council", "shipping", "tool-using"],
    )
    bank.consolidate(bank.distill(
        f"Tool-using council voted {verdict} after consulting prior decisions",
        tags=["decision", "shipping"],
    ))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
