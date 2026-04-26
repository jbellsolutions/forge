# forge

[![PyPI](https://img.shields.io/pypi/v/forge-harness.svg)](https://pypi.org/project/forge-harness/)
[![CI](https://github.com/jbellsolutions/forge/actions/workflows/ci.yml/badge.svg)](https://github.com/jbellsolutions/forge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/forge-harness.svg)](https://pypi.org/project/forge-harness/)

**A model-agnostic, self-learning, self-healing agent harness — and the Python SDK to build agent swarms on top of it.**

---

## What forge does

You describe a swarm of agents in plain English. forge designs the architecture (which agents, what roles, what tools, what schedule), asks you where to run it, and spins it up.

**Drop this repo into any AI IDE — Claude Code, Codex, Cursor, or just a terminal — and say something like:**

> "build me a swarm that pulls Apollo leads every morning, qualifies them with Claude, and DMs the hot ones to my Slack"

forge proposes the architecture, you approve, and it scaffolds the swarm into one of three places — your choice:

| Where it runs | What you get | Best for |
|---|---|---|
| **Local terminal** | `examples/<name>/run.py` you can run on demand or cron | Hacking on the swarm, version-controlling it, no external dependencies |
| **Railway dashboard** | A `PendingAction` in your hosted dashboard; one click and it materializes locally on the next 5-min sync | Persistent control plane, daily/weekly reports, watching your swarm evolve from anywhere |
| **Claude Code subagents** | Drop-in `.claude/agents/<name>.md` files in your repo's `.claude/` directory | Working day-to-day inside Claude Code; subagents you can invoke via `/agents` |

Pick one, pick all three. The swarm itself is the same; only the runtime changes.

---

## How to use it

### One-line swarm — from any terminal

```bash
pip install 'forge-harness[dashboard]'
forge new "DM me a Notion summary every morning at 8"
```

forge will:
1. Design a swarm (LLM-driven; uses Anthropic Haiku by default ≈ $0.005)
2. Show you the proposed architecture (agents, roles, tools, schedule)
3. Ask where to run it: `[1] terminal  [2] claude  [3] dashboard  [4] all`
4. Scaffold the artifacts

### From Claude Code / Codex / any AI IDE

Open this repo in your IDE. Tell it:

> "Use forge to build me a swarm that does X."

The IDE reads `forge`'s docs, runs `forge new "X"`, and walks you through the same flow. (No special integration needed — `forge new` is just a CLI.)

### From the Railway dashboard

If you already have the dashboard deployed (see [Railway deploy](RAILWAY_DEPLOY.md)), the orchestrator chat ("Papa Bear") on the Workspace page can also design and propose swarms. Type a description; click Approve on the PendingAction; the next local sync materializes the scaffold.

### Manual mode (no LLM, no design step)

If you already know the swarm shape and just want the SDK:

```python
from forge import (
    HookBus, ToolRegistry, RoleCouncilSpawner, RoleAssignment,
    SwarmSpec, Topology, Consensus, attach_healing,
)
```

See [the 60-second SDK pitch](#the-60-second-sdk-pitch) below.

---

## Install

```bash
pip install forge-harness                   # core SDK + CLI
pip install 'forge-harness[dashboard]'      # +FastAPI dashboard, Postgres support
pip install 'forge-harness[intel]'          # +auto-research with Tavily
```

> Distribution name on PyPI: `forge-harness`. Import name in Python: `forge`. Same pattern as `pillow → import PIL` or `scikit-learn → import sklearn`.

---

## Why this exists

Every agent harness shipping today locks you into a single model vendor or a single use case:

- **Claude Agent SDK** — beautiful primitives, but Claude-only.
- **OpenAI Agents SDK** — same shape, OpenAI-only.
- **Ruflo** — open and powerful, but TypeScript-heavy and hard to compose.
- **OpenHarness, Hermes, Meta-Harness** — academic gems, each great at one thing, none complete.
- **LangChain / LlamaIndex** — kitchen-sink frameworks, no real swarm or recursion model.
- **Bespoke `.claude/` rigs** — every team rebuilds the same `CircuitBreaker`, `EvalGate`, `ReasoningBank` from scratch.

The result: you pick a vendor, you pick a use case, you re-implement the same five primitives every time.

**forge picks a different fight.**

It's a *harness*, not a framework — a thin kernel + extensible hook bus + a layered set of opt-in primitives, all model-agnostic. You bring any model (or four). You bring your tools (MCP, Composio, computer-use, CLI subprocesses). forge gives you the swarm topology, the healing, the memory, the skill self-modification, and the observability. You write five lines and a council debates your decision on three different models in parallel and returns a majority verdict — with token cost, replayable traces, and a learning loop that promotes a winning skill version when the eval gate clears.

---

## The 60-second SDK pitch

```python
import asyncio
from forge import (
    HookBus, ToolRegistry,
    RoleCouncilSpawner, RoleAssignment, SwarmSpec, Topology, Consensus,
    attach_healing,
)

async def main():
    tools, hooks = ToolRegistry(), HookBus()
    attach_healing(hooks)                                            # circuit breaker on every tool

    s = RoleCouncilSpawner(tools=tools, hooks=hooks, max_turns=4)
    s.set_assignments([
        RoleAssignment(profile="anthropic",            role="optimist"),
        RoleAssignment(profile="anthropic-haiku",      role="skeptic"),
        RoleAssignment(profile="anthropic-contrarian", role="pragmatist"),
    ])

    result = await s.run(
        "Should we deploy this feature today?",
        SwarmSpec(topology=Topology.PARALLEL_COUNCIL, consensus=Consensus.MAJORITY,
                  members=["anthropic", "anthropic-haiku", "anthropic-contrarian"]),
    )
    print("verdict:", result.verdict.winner)

asyncio.run(main())
```

That's a 3-member parallel council with role-injected disagreement (so they don't all rubber-stamp the same answer), wired through a circuit breaker that trips on tool failures, with traces and token costs logged. ~$0.10 per run, end-to-end.

Now imagine that wired into your nightly cron, learning from its own traces, promoting prompt versions only when they beat current by a 0.05 confidence margin, and exposing every primitive as an MCP tool your Claude Code session can call. That's forge.

---

## The research that built this

forge wasn't designed in a vacuum. It started with a simple question: *what does the best 5% of every existing harness look like, and could we lift only the winning patterns?*

We assigned three research agents to three clusters, each running a three-round analysis loop (Observe → Stress-test → Converge) on every source. **Sixteen sources, ~140 hours of reading distilled into a single rubric, then synthesized through a three-perspective council** (simplicity / power / observability).

### Cluster A — eight existing repos (the "what already works" survey)
- `jbellsolutions/autonomous-sdr-agent` — persona/council router pattern, SOUL.md identity files
- `jbellsolutions/social-sdr` — production-grade `CircuitBreaker` + 5-class `ErrorType`
- `jbellsolutions/Orgo-Computer-Use-Agents` — the canonical `.claude/` filesystem layout
- `jbellsolutions/coo-agent` — three-tier tool fallthrough (MCP → Computer Use → CLI)
- `jbellsolutions/agentstack-fleet-builder` — concierge + reinforced-harness separation
- `jbellsolutions/ai-agent-team-reference` — 11-role agent taxonomy
- `ruvnet/ruflo` — topology × consensus as config, MoE-8 router, ReasoningBank, WASM bypass tier
- `nousresearch/hermes-agent` — autonomous skill synthesis post-task

### Cluster B — academic + frontier harnesses
- `HKUDS/OpenHarness` — hook bus + dry-run `ready/warning/blocked` verdict + permission modes
- `openclaw/openclaw` — per-session-type tool allowlists, gateway-as-router
- `yoonholee.com/meta-harness` — **trace-fidelity invariant**: store full execution traces so the optimizer can do counterfactual diagnosis
- `kevinrgu/autoagent` — `program.md` anti-overfit regularizer, `# === FIXED ADAPTER BOUNDARY ===` sentinel
- `hyperagent.com` — cost dashboard pattern (and a lesson in marketing-vs-substance)

### Cluster C — SDKs + theory
- **Composio** — session+auth abstraction over 1,000+ SaaS apps
- **Claude Agent SDK** — `AgentDefinition`, lifecycle hooks, permission modes
- **OpenAI Agents SDK** — JSON-Schema tool portability
- **Anthropic's Long-Running Agents paper** — Initializer→Coding split, **git-as-session-journal** (resume from `git diff HEAD~N`)
- **Martin Fowler's Harness Engineering** — the *Guides* (feedforward) + *Sensors* (feedback) vocabulary

### What got lifted (and what got skipped)

| Source | Pattern lifted | Why |
|---|---|---|
| Ruflo | Topology × consensus as config, ReasoningBank 5-stage loop | Most expressive swarm primitive in the field |
| Hermes | Autonomous skill synthesis post-task | Only source with real dynamic skill creation |
| Meta-Harness | Full-fidelity trace store, counterfactual diagnosis | The single most important primitive for true self-improvement |
| OpenHarness | Hook bus, dry-run verdict, permission modes | Cleanest extensibility seam shipped open-source |
| OpenClaw | Per-session-type tool allowlists | Blast-radius reduction for swarms |
| Claude Agent SDK | `AgentDefinition` pattern, lifecycle hook names | Industry-standard agent isolation |
| Anthropic paper | Initializer→Coding split, git-as-journal | Resumability without custom session storage |
| Composio | Tool registry as session+auth layer | 1,000+ apps as one decoupled boundary |
| AutoAgent | "Would this still help if this task vanished?" regularizer, FIXED ADAPTER BOUNDARY sentinel, `results.tsv` ledger | Anti-overfit guard that ships in the proposer prompt |
| Fowler | Guides + Sensors vocabulary, three-tier regulation | The right names for the right things |
| Justin's repos | `.claude/` filesystem contract, `ErrorType` + `CircuitBreaker`, eval-gated A/B promotion | Production primitives ported verbatim |

**Skipped on purpose:** kitchen-sink frameworks (LangChain), single-vendor SDKs as the kernel layer (forge calls them as profiles instead), academic toy loops without a real eval substrate, Hyperagent's marketing copy.

The full per-source rubric scores live in `okay-so-if-i-immutable-seahorse-agent-*.md` plan files; that's how every claim above can be audited.

---

## Architecture: eight layers, hook-bus seam

```
L7  Observability    OTel · token+cost telemetry · dry-run verdict · replayable traces
L6  Use-case         Personas · skills · routers · heartbeats
L5  Self-improve     Skill autosynthesis · eval gate · skill search
L4  Swarm            Topology × consensus · sub-agent isolation
L3  Self-healing     ErrorType · CircuitBreaker · retry policy
L2  Tools            MCP → Computer/Browser → CLI shell · per-persona deny-list
L1  Memory           ReasoningBank · git journal · Obsidian vault · cross-project genome · .claude/
L0  Kernel           Agent loop · hook lifecycle · provider-as-profile
```

**Why layers, not modules:** L0 may not import from any layer above it. L1–L7 may only import from layers below. The **hook bus is the cross-cutting seam** — every layer subscribes; nothing reaches across. That's what keeps the kernel under 200 lines and the rest swappable.

**Why "harness" not "framework":** a framework calls your code; forge gives you primitives, you compose them. The kernel is `AgentLoop.run()`. Everything else is hooks, registries, and adapters.

---

## What's proven live (verification table)

These aren't aspirations. Every row was demonstrated end-to-end against real APIs during the build:

| Surface | What was tested | Result |
|---|---|---|
| **PyPI install** | `pip install forge-harness` in a clean venv | ✅ v0.1.0, 60 top-level exports importable, ~85 KB wheel |
| **CI matrix** | pytest on ubuntu+macos × Python 3.11/3.12/3.13 + wheel build | ✅ 7/7 jobs green |
| **Test suite** | 70 tests across kernel, providers, tools, healing, swarm, memory, skills, observability, recursion, CLI | ✅ 70/70 passing |
| **Anthropic provider** | LIVE Sonnet + Haiku + Sonnet-contrarian as 3 council members | ✅ verdict reached, 17 tool calls, $0.10/run |
| **OpenRouter provider** | LIVE DeepSeek-chat call via OpenAI-compatible adapter | ✅ correct output, 12 in / 6 out tokens, < $0.001 |
| **Composio integration** | Live API call via `ComposioToolSet` | ✅ 1,048 apps available (gmail, github, notion, slack, supabase, …) |
| **Real MCP server** | `npx -y @modelcontextprotocol/server-filesystem` rooted at vault | ✅ 14 fs tools registered (`fs_vault__read_file`, `fs_vault__write_file`, …) |
| **Recursion (LIVE Sonnet)** | Read 8 synthetic failing traces, propose harness diffs, fork → apply → score → keep | ✅ 2/2 diffs applied, score 0.00 → 1.00, kept=1, ledger row written, `circuits.json` and persona file actually mutated by Sonnet's proposed diffs |
| **Anti-overfit regularizer** | Sonnet's rationales explicitly invoke the AutoAgent guard | ✅ verbatim quote: *"This is NOT task-specific … any task using this broken tool will benefit … this generalizes."* |
| **Tool-using council** | Members with access to MCP fs + Obsidian search + shell + git | ✅ Haiku + Contrarian voted WAIT with grounded reasoning ("today is Sunday", "no test results"), 3 sessions traced |
| **Memory promotion** | High-confidence ReasoningBank memories → Obsidian topics | ✅ 2 promoted to vault topic notes with frontmatter (memory_id, confidence, promoted_count) |
| **Claude Code MCP server** | `claude mcp add forge -- forge mcp` | ✅ Connected, 12 forge tools advertised |
| **Slash command** | `/forge council "..."`, `/forge recurse`, `/forge vault search`, etc. | ✅ all 13 verbs wired |
| **Skill auto-trigger** | Plain-language *"run a council on shipping"* | ✅ skill at `~/.claude/skills/forge/SKILL.md` routes to `forge_council` |
| **Cross-project genome** | Promoted memory at `~/.forge/genome.json`, recallable from any project | ✅ singleton `genome()` returns ReasoningBank shared across projects |

---

## Three ways to use forge

### 1. As a Python SDK in any project

```bash
pip install "forge-harness[anthropic,mcp]"
```

```python
from forge import (
    AgentLoop, AgentDef, HookBus, Verdict,
    RoleCouncilSpawner, RoleAssignment, SwarmSpec, Topology, Consensus,
    ObsidianVault, ReasoningBank, genome,
    ToolRegistry,
    attach_healing, ErrorType,
    SkillStore, autosynth, evaluate, promote_if_passing,
    TraceStore, Telemetry,
    recurse_once, propose_with_llm, ResultsLedger,
)
```

The full SDK surface (60 symbols, all stable in v0.1.x) is documented in `forge/__init__.py::__all__`.

### 2. As a shell CLI

```bash
forge doctor                                      # env audit
forge run operator                                # mock vertical end-to-end
forge run operator_real                           # live council with MCP filesystem server
forge recurse --home ~/.forge/X                   # one self-mod cycle
forge recurse-loop --home ~/.forge/X -n 5         # cron-friendly: 5 cycles in series
forge dashboard --home ~/.forge/X                 # telemetry summary
forge skill list                                  # project skill registry
forge skill search "summarize"                    # vector search over skills
forge vault write "Q4 plan" :: "ship by Oct" #planning
forge vault search "shipping"
forge heartbeat run --dir ~/.forge/X/.claude/heartbeats
forge mcp                                         # run as MCP stdio server
```

### 3. Inside Claude Code (slash + skill + MCP)

One-time setup:

```bash
claude mcp add -s user forge -- $(which forge) mcp
```

Then in any Claude Code session:

```
/forge council "Should we ship today?"
/forge recurse
/forge vault write Q4 plan :: ship by Oct #planning
/forge remember "Friday EOD ships consistently work"
/forge recall shipping decisions
/forge doctor
```

Or just say it conversationally — *"run a council on whether to ship"* — and the skill at `~/.claude/skills/forge/SKILL.md` will route to `forge_council` automatically.

---

## Configure

forge runs in mock mode out of the box (no keys needed for tests + scaffolding). To go live, drop your keys in `~/.forge/.env`:

```bash
mkdir -p ~/.forge
cat > ~/.forge/.env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...
OPENROUTER_API_KEY=sk-or-...    # optional — DeepSeek + 100+ models
COMPOSIO_API_KEY=ak_...         # optional — 1,000+ SaaS tools
VOYAGE_API_KEY=...              # optional — production embeddings
OPENAI_API_KEY=...              # optional — alternative embedding source
OTEL_EXPORTER_OTLP_ENDPOINT=... # optional — ship spans to Honeycomb/Jaeger/Datadog
EOF
chmod 600 ~/.forge/.env
forge doctor                    # verify
```

forge auto-loads the file on import (and re-overrides empty parent-shell env vars — see "What we fixed" below).

---

## Memory model

Three tiers, all wired together:

- **Per-project working memory** at `<your_project>/.claude/forge/` — traces, telemetry, project-specific skills, healing circuits. Stays with the repo.
- **Cross-project genome** at `~/.forge/genome.json` — high-confidence learnings compound across all projects. Use `forge_memory_remember` / `forge_memory_recall` from any project.
- **Obsidian vault** at `~/.forge/vault` — human-readable knowledge graph. `inbox/` `daily/` `decisions/` `topics/` `agents/` folders, YAML frontmatter, `[[wiki-link]]` parsing, backlinks graph. Open the folder in Obsidian to browse the agent's accumulated knowledge visually.

Memory promotion is automatic: when a `ReasoningBank` memory crosses confidence threshold + min-use count, `promote()` writes it as `topics/<slug>.md` in the vault with full provenance metadata. Re-promotion bumps a `promoted_count` instead of duplicating.

---

## Schedulers — set it and forget it

Three templates ship under `forge/scheduler/`:

```bash
# macOS launchd — nightly self-improve at 02:30
cp forge/scheduler/launchd.plist.template ~/Library/LaunchAgents/com.forge.recurse.plist
launchctl load ~/Library/LaunchAgents/com.forge.recurse.plist

# Linux/macOS cron
crontab -e        # paste from forge/scheduler/cron.crontab.template

# CI / GitHub Actions — auto-run nightly recurse + commit ledger updates
mkdir -p .github/workflows
cp forge/scheduler/github_action.yml.template .github/workflows/forge-nightly.yml
```

The `recurse-loop` subcommand was designed for cron specifically: idempotent, structured logs, exit code reflects success.

---

## What we fixed along the way

A "true SDK" is one that survives reality. Here's what reality threw at forge during the build:

### macOS Sonoma `com.apple.provenance` xattr broke editable installs on Python 3.14

**Symptom:** `pip install -e .` succeeded, but `python -c "import forge"` raised `ModuleNotFoundError`. `pytest` worked. Direct `python` invocations didn't.

**Root cause:** Python 3.14 added a check that skips `.pth` files where the OS reports `UF_HIDDEN`. macOS Sonoma+ tags every file written through certain APIs with `com.apple.provenance`, which sets the hidden flag. The editable-install `.pth` was being silently skipped at site init.

**Fix:** the `forge` shell script was rewritten as a `bash` wrapper that exports `PYTHONPATH` directly:

```bash
#!/usr/bin/env bash
exec env PYTHONPATH="/path/to/forge" /path/to/.venv/bin/python -m forge.cli "$@"
```

Editable installs still work for `python -m forge.cli` and `pytest`. The wrapper handles the script-on-PATH case until Python 3.14 ignores `UF_HIDDEN` for `.pth` or hatchling stops triggering the provenance xattr. Documented in `CHANGELOG.md`.

### Circular import: `forge.tools` ↔ `forge.kernel`

**Symptom:** `from forge.tools.composio_adapter import ComposioAdapter` raised `ImportError: cannot import name 'Tool' from partially initialized module 'forge.tools.base'`.

**Root cause:** `forge.tools.__init__` imported `.base` which imported from `..kernel.types`, which triggered `forge.kernel.__init__` which imported `.loop`, which imported back into `forge.tools.registry` — a partially-loaded base.

**Fix:** every type-only import across the kernel ↔ tools boundary is now `TYPE_CHECKING`-only. Forward references in method signatures become string-quoted. No runtime cost, no cycle. `pytest` proved both paths work.

### Empty parent-shell env vars shadowed `~/.forge/.env`

**Symptom:** `forge doctor` reported `ANTHROPIC_API_KEY: empty` even though the key was in `~/.forge/.env`.

**Root cause:** the `_dotenv` loader used `os.environ.setdefault(k, v)` — but `setdefault` doesn't override an existing empty value. The shell had `ANTHROPIC_API_KEY=""` from somewhere, which beat the file.

**Fix:** override semantics changed to "missing OR empty value gets replaced from file." Existing non-empty shell exports still win — you can override per-invocation without editing the file.

### LLM proposer payloads didn't match `apply()`

**Symptom:** First live recursion run on Sonnet produced 2 diffs but applied 0.

**Root cause:** the directive was too loose. Sonnet emitted reasonable-looking JSON (`target=config/tools.yaml`, `target=circuits/safety.yaml`) but the harness's `apply()` only knew specific paths and payload key names.

**Fix:** the `PROGRAM_DIRECTIVE` was tightened with **explicit examples for each op shape** showing the exact target paths and required payload keys. Sonnet's next run emitted both diffs in correct shape; both applied; score went 0.00 → 1.00; the candidate was kept.

This is the regularizer working at *both* the LLM level (anti-overfit reasoning in the prompt) and the gate level (rollback if score didn't improve). Bad proposals get discarded automatically.

### Empty council verdicts when a member hit `max_turns` mid-tool-call

**Symptom:** Live tool-using council had Haiku produce a clean WAIT vote with rationale, but Sonnet returned `''`.

**Root cause:** when an agent exits via `max_turns` while generating tool calls, the last assistant message is empty (text-less, tool-call-only). The loop returned that as `final_text`.

**Fix:** `final_text` extraction now walks the message list backward and returns the last **non-empty** assistant text. Combined with `max_turns=8` for tool-using councils, every member produces a usable vote.

### `.pth` files written without a trailing newline

**Symptom:** Even after fixing `UF_HIDDEN`, the editable install didn't work.

**Root cause:** Python's site module silently skips `.pth` lines that don't end with a newline. Hatchling on Python 3.14 wrote a 25-byte file with no terminator.

**Fix:** the bash wrapper avoids the `.pth` mechanism entirely. The CHANGELOG documents the issue for future maintainers.

### `forge` was already taken on PyPI

**Symptom:** `twine upload` returned `403 Forbidden`.

**Root cause:** another project named `forge` already existed at v0.12.0+. PyPI names are first-come.

**Fix:** distribution name changed to `forge-harness`. Python import name stayed `forge`. Same pattern as `pillow → import PIL`. Scratched a brief itch to over-think this; moved on.

### Council members near-identical without role injection

**Symptom:** Three Sonnets given the same task all said the same thing. "Consensus" was an artifact, not a signal.

**Fix:** `RoleCouncilSpawner` injects per-member system prompts (optimist / skeptic / pragmatist) before each call. Now they actually disagree productively, and a 2-1 verdict means something. The role prompts are documented in `forge.swarm.roles::DEFAULT_ROLES` and overridable per call.

---

## The full SDK API surface

Everything you need, importable at the top level (`from forge import …`):

```python
# L0 kernel
AgentLoop, AgentDef, HookBus, HookContext, LoopResult,
Message, AssistantTurn, ToolCall, ToolResult,
Verdict, PermissionMode, ProviderProfile, load_profile

# L1 memory
ObsidianVault, Note,                       # Obsidian-format vault with backlinks
ReasoningBank, Memory,                     # vector recall with confidence decay
genome, genome_path,                       # cross-project singleton
GitJournal,                                # resume-from-git
ClaudeDir,                                 # canonical filesystem contract
PromotionResult, promote                   # ReasoningBank → vault promotion

# L2 tools
Tool, ToolRegistry                         # 3-tier classification + per-agent allow/deny

# L3 healing
CircuitBreaker, CircuitRegistry, CircuitState,
ErrorType, classify, attach_healing        # wires breakers into the hook bus

# L4 swarm
Topology, Consensus, SwarmSpec, SwarmResult,
Spawner, RoleCouncilSpawner, RoleAssignment

# L5 skills
SkillStore, SkillRun, SkillSearchIndex,
autosynth, evaluate, promote_if_passing,
MIN_SAMPLES, CONFIDENCE_MARGIN, EvalReport

# L7 observability
TraceStore, Telemetry, SessionStat
# (OTelExporter under forge.observability.otel — optional opentelemetry dep)

# Providers
Provider, make_provider                    # YAML-driven factory
# Profiles ship: anthropic, anthropic-haiku, anthropic-contrarian,
#                openrouter-deepseek, openai-gpt4, ollama-llama3, mock

# Recursion
recurse_once, RecurseResult,               # full self-mod cycle
propose, propose_with_llm,                 # rule-based + LLM proposers
HarnessDiff, TraceAnalyzer, ResultsLedger  # diff types + symptom extraction + TSV ledger
```

For tools that need vendor SDKs — Composio, MCP, browser automation — import from their submodules:

```python
from forge.tools.builtin.shell import ShellTool, ClaudeCodeTool, CodexCLITool, GeminiCLITool
from forge.tools.builtin.fs import FSReadTool, FSWriteTool
from forge.tools.builtin.browser import HttpFetchTool
from forge.tools.builtin.obsidian import (
    ObsidianWriteTool, ObsidianSearchTool, ObsidianReadTool, ObsidianBacklinksTool,
)
from forge.tools.mcp_client import MCPClientPool, load_mcp_servers
from forge.tools.composio_adapter import ComposioAdapter, composio_via_mcp
from forge.observability.otel import OTelExporter
```

---

## Architecture references

Every external pattern in forge has a paper trail. If you want to read the source material:

| Source | What forge took |
|---|---|
| **Ruflo** ([ruvnet/ruflo](https://github.com/ruvnet/ruflo)) | Provider-as-profile, topology × consensus as config, ReasoningBank 5-stage loop |
| **Hermes** ([nousresearch/hermes-agent](https://github.com/nousresearch/hermes-agent)) | Autonomous skill synthesis post-task |
| **Meta-Harness** ([yoonholee.com/meta-harness](https://yoonholee.com/meta-harness/)) | Full-fidelity trace store as the recursion substrate |
| **OpenHarness** ([HKUDS/OpenHarness](https://github.com/HKUDS/OpenHarness)) | Hook bus + permission modes + dry-run verdict |
| **OpenClaw** ([openclaw/openclaw](https://github.com/openclaw/openclaw)) | Per-session-type tool allowlists, gateway-as-router |
| **AutoAgent** ([kevinrgu/autoagent](https://github.com/kevinrgu/autoagent)) | `program.md` regularizer, `# === FIXED ADAPTER BOUNDARY ===` sentinel, `results.tsv` ledger |
| **Claude Agent SDK** ([code.claude.com](https://code.claude.com/docs/en/agent-sdk/overview)) | `AgentDefinition`, hook lifecycle, permission modes |
| **Anthropic harness paper** ([anthropic.com](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)) | Initializer→Coding split, git-as-session-journal |
| **Composio** ([composio.dev](https://composio.dev/)) | Session+auth tool registry over 1,000+ apps |
| **Fowler** ([martinfowler.com](https://martinfowler.com/articles/harness-engineering.html)) | *Guides* (feedforward) + *Sensors* (feedback) vocabulary |
| **Justin's repos** (autonomous-sdr, coo-agent, Orgo) | `.claude/` filesystem contract, `ErrorType` + `CircuitBreaker`, eval-gated A/B promotion |

---

## Roadmap

- [ ] **PyPI publishing on tag** — wire the GH Actions workflow to `twine upload` automatically when `git tag v*.*.*` is pushed
- [ ] **Sphinx / mkdocs API reference site** — auto-generated from docstrings; deployed to `forge-harness.dev`
- [ ] **Real `OnnxMiniLM` default embedder** — local, free, no network round-trips for the genome
- [ ] **Real OTel default exporter** — ship spans to Honeycomb out of the box when `OTEL_EXPORTER_OTLP_ENDPOINT` is set
- [ ] **Composio MCP entry enabled by default** in `examples/operator_real/mcp.json` when `COMPOSIO_API_KEY` is present
- [ ] **TS SDK adapter** — for projects that want forge primitives from Node (the Claude Agent SDK route)
- [ ] **Browser-Use + Airtop tier-2 adapters** — first-class browser automation
- [ ] **Plugin system for new consensus algorithms** — Raft, Byzantine, weighted-by-cost-tier
- [ ] **More heartbeats** — daily standup, weekly retro, monthly retrospective templates
- [ ] **End-to-end Notion / Linear / Slack examples** via Composio adapter

Open an issue if you want to drive any of these.

---

## Contributing

forge stays small on purpose. The kernel is under 200 lines. Every layer above L0 is opt-in. PRs that complicate the kernel without proving value get pushed back; PRs that close a real gap land fast.

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, layer rules, and the release workflow.

---

## A note on the name

forge: where raw materials become tools. It started as a working title and stuck. The original project named `forge` on PyPI is something else entirely — we're `forge-harness` on PyPI, `forge` everywhere else. If you build something with this and tell us about it, we'll add it to a community gallery.

---

## License

MIT. See [LICENSE](LICENSE).

Built with ⚒️ by [Justin Bell](https://github.com/jbellsolutions). Synthesized from 16 sources, 70 tests, 10 commits, $0.11 of live API spend during the build, and one frustrating evening fighting macOS xattrs.
