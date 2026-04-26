# forge

[![PyPI](https://img.shields.io/pypi/v/forge-harness.svg)](https://pypi.org/project/forge-harness/)
[![CI](https://github.com/jbellsolutions/forge/actions/workflows/ci.yml/badge.svg)](https://github.com/jbellsolutions/forge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/forge-harness.svg)](https://pypi.org/project/forge-harness/)

Model-agnostic, self-learning, self-healing **agent harness** — and a Python SDK for building agent swarms.

Drop into any project. Spin up parallel councils. Self-improve via recursion. Memory and skills compound across projects. Use it from code, from a CLI, or as a Claude Code slash command + MCP server.

> **Distribution name:** `forge-harness` (on PyPI). **Import name:** `forge` (in Python). Same pattern as `pillow` → `import PIL`.

## Layers

```
L7  Observability  OTel · token+cost · dry-run verdict · replayable traces
L6  Use-case       Personas · skills · routers · heartbeats
L5  Self-improve   Skill autosynthesis · eval gate · skill search
L4  Swarm          Topology × consensus · sub-agent isolation
L3  Self-healing   ErrorType · CircuitBreaker · retry policy
L2  Tools          MCP → Computer/Browser → CLI shell · per-persona deny-list
L1  Memory         ReasoningBank · git journal · Obsidian vault · cross-project genome · .claude/
L0  Kernel         Agent loop · hook lifecycle · provider-as-profile
```

## Quickstart (60 seconds)

```bash
pip install "forge-harness[anthropic,mcp]"
mkdir -p ~/.forge && echo "ANTHROPIC_API_KEY=sk-ant-..." > ~/.forge/.env && chmod 600 ~/.forge/.env
forge doctor                                   # verify
```

```python
import asyncio
from forge import (
    HookBus, ToolRegistry,
    RoleCouncilSpawner, RoleAssignment, SwarmSpec, Topology, Consensus,
    attach_healing,
)

async def main():
    tools, hooks = ToolRegistry(), HookBus()
    attach_healing(hooks)
    s = RoleCouncilSpawner(tools=tools, hooks=hooks, max_turns=4)
    s.set_assignments([
        RoleAssignment(profile="anthropic",            role="optimist"),
        RoleAssignment(profile="anthropic-haiku",      role="skeptic"),
        RoleAssignment(profile="anthropic-contrarian", role="pragmatist"),
    ])
    result = await s.run(
        "Should we ship today?",
        SwarmSpec(topology=Topology.PARALLEL_COUNCIL, consensus=Consensus.MAJORITY,
                  members=["anthropic", "anthropic-haiku", "anthropic-contrarian"]),
    )
    print("verdict:", result.verdict.winner)

asyncio.run(main())
```

## Install

```bash
# From PyPI (recommended)
pip install forge-harness

# With optional integrations
pip install "forge-harness[anthropic,mcp]"        # add Anthropic SDK + MCP client
pip install "forge-harness[all]"                  # everything: anthropic, openai, mcp, composio, otel, embeddings

# From GitHub main
pip install git+https://github.com/jbellsolutions/forge.git

# Editable for development
git clone https://github.com/jbellsolutions/forge.git
cd forge && pip install -e ".[dev,anthropic,mcp]"
```

Optional extras: `anthropic`, `openai`, `mcp`, `composio`, `otel`, `embeddings`, `dev`, `all`.

## Configure

```bash
mkdir -p ~/.forge
cat > ~/.forge/.env <<EOF
ANTHROPIC_API_KEY=sk-ant-...
OPENROUTER_API_KEY=sk-or-...     # optional
COMPOSIO_API_KEY=ak_...          # optional, unlocks 1000+ SaaS tools
EOF
chmod 600 ~/.forge/.env
```

forge auto-loads `~/.forge/.env` on import. Verify:

```bash
forge doctor
```

## Use it from code (the SDK path)

```python
import asyncio
from forge.kernel import HookBus
from forge.healing import attach_healing
from forge.swarm import (
    RoleCouncilSpawner, RoleAssignment, SwarmSpec, Topology, Consensus,
)
from forge.tools import ToolRegistry
from forge.tools.builtin.echo import EchoTool

async def main():
    tools = ToolRegistry(); tools.register(EchoTool())
    hooks = HookBus(); attach_healing(hooks)

    spawner = RoleCouncilSpawner(tools=tools, hooks=hooks, max_turns=4)
    spawner.set_assignments([
        RoleAssignment(profile="anthropic",            role="optimist"),
        RoleAssignment(profile="anthropic-haiku",      role="skeptic"),
        RoleAssignment(profile="anthropic-contrarian", role="pragmatist"),
    ])

    spec = SwarmSpec(
        topology=Topology.PARALLEL_COUNCIL,
        consensus=Consensus.MAJORITY,
        members=["anthropic", "anthropic-haiku", "anthropic-contrarian"],
    )
    result = await spawner.run("Should we ship today?", spec)
    print(result.verdict.winner)

asyncio.run(main())
```

The full primitive set:

```python
# Kernel
from forge.kernel import AgentLoop, AgentDef, HookBus, HookContext, Verdict

# Providers (model-as-profile)
from forge.providers import make_provider, load_profile
# Profiles: anthropic, anthropic-haiku, anthropic-contrarian,
#           openrouter-deepseek, openai-gpt4, ollama-llama3, mock

# Tools (3-tier fall-through)
from forge.tools import ToolRegistry
from forge.tools.builtin.shell import ShellTool, ClaudeCodeTool, CodexCLITool, GeminiCLITool
from forge.tools.builtin.fs import FSReadTool, FSWriteTool
from forge.tools.builtin.browser import HttpFetchTool
from forge.tools.builtin.obsidian import ObsidianWriteTool, ObsidianSearchTool
from forge.tools.mcp_client import MCPClientPool, load_mcp_servers
from forge.tools.composio_adapter import ComposioAdapter

# Healing
from forge.healing import CircuitBreaker, ErrorType, attach_healing

# Swarm
from forge.swarm import Spawner, RoleCouncilSpawner, SwarmSpec, Topology, Consensus

# Memory (per-project + cross-project genome)
from forge.memory import (
    ObsidianVault, ReasoningBank, GitJournal, ClaudeDir, genome, promote,
)

# Skills (eval-gated autosynth)
from forge.skills import SkillStore, autosynth, evaluate, promote_if_passing, SkillSearchIndex

# Observability
from forge.observability import TraceStore, Telemetry
from forge.observability.otel import OTelExporter

# Recursion (self-mod)
from forge.recursion import recurse_once, propose_with_llm, ResultsLedger
```

## Use it from the CLI

```bash
forge doctor                   # health check
forge run operator             # mock vertical end-to-end
forge run operator_real        # live council with MCP filesystem server
forge recurse --home ~/.forge/X
forge recurse-loop -n 5        # nightly cron friendly
forge dashboard --home ~/.forge/X
forge skill list
forge vault search --query "shipping"
forge heartbeat run --dir ~/.forge/X/.claude/heartbeats
forge mcp                      # run as MCP stdio server
```

## Use it inside Claude Code (slash + skill + MCP)

**One-time setup:**

```bash
claude mcp add -s user forge -- /path/to/.venv/bin/forge mcp
```

**Inside a Claude Code session:**

```
/forge council "Should we ship today?"
/forge recurse
/forge vault write Q4 plan :: ship by Oct #planning
/forge vault search shipping
/forge remember "Friday EOD ships work"
/forge recall shipping
/forge skill list
/forge doctor
```

The skill at `~/.claude/skills/forge/SKILL.md` also auto-triggers on intent — you can just say *"run a council on whether to ship"* and Claude calls `forge_council` for you.

## Memory model

- **Per-project working memory** at `<your_project>/.claude/forge/` — traces, telemetry, project-specific skills
- **Cross-project genome** at `~/.forge/genome.json` — high-confidence learnings compound across all your projects
- **Obsidian vault** at `~/.forge/vault` — human-readable knowledge graph; open in Obsidian, see backlinks, edit by hand

## Schedulers

Templates in `forge/scheduler/`:

```bash
# macOS launchd (nightly self-improve)
cp forge/scheduler/launchd.plist.template ~/Library/LaunchAgents/com.forge.recurse.plist
launchctl load ~/Library/LaunchAgents/com.forge.recurse.plist

# Linux/macOS cron
crontab -e        # paste from forge/scheduler/cron.crontab.template

# CI / GitHub Actions
mkdir -p .github/workflows
cp forge/scheduler/github_action.yml.template .github/workflows/forge-nightly.yml
```

## Verification

```bash
pytest -q                                      # 70 tests
forge doctor                                   # env audit
python examples/operator/run.py                # mock end-to-end
ANTHROPIC_API_KEY=... python examples/recursion_demo/run.py        # live recursion
ANTHROPIC_API_KEY=... python examples/operator_real/run_with_tools.py  # live council
```

## Architecture references

forge synthesizes patterns from many sources without inheriting any single one:

- **Ruflo** — provider-as-profile, topology × consensus as config, ReasoningBank loop
- **Hermes (Nous)** — autonomous skill synthesis post-task
- **Meta-Harness (Yoon Ho Lee)** — full-fidelity trace store as the recursion substrate
- **OpenHarness (HKUDS)** — hook bus + permission modes + dry-run verdict
- **OpenClaw** — per-session-type tool allowlists, gateway-as-router
- **Claude Agent SDK** — `AgentDefinition`, hook lifecycle, permission modes
- **Anthropic harness paper** — Initializer→Coding split, git-as-session-journal
- **Composio** — session+auth tool registry over 1000+ apps
- **Fowler** — *Guides* (feedforward) + *Sensors* (feedback) vocabulary
- **AutoAgent** — `program.md` regularizer, FIXED ADAPTER BOUNDARY sentinel, `results.tsv` ledger
- **Justin's repos (autonomous-sdr, coo-agent, Orgo)** — `.claude/` filesystem contract, `ErrorType` + `CircuitBreaker`, eval-gated A/B promotion

## License

MIT
