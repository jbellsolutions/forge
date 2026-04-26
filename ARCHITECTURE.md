# forge — Architecture

The 8-layer harness, layer by layer. Read this before contributing.

## Layer map

```
┌──────────────────────────────────────────────────────────────────┐
│ L7  Observability    TraceStore · Telemetry · OTel · dashboard   │
├──────────────────────────────────────────────────────────────────┤
│ L6  Use-case         personas · heartbeats · examples/*          │
├──────────────────────────────────────────────────────────────────┤
│ L5  Skills           SkillStore · EvalGate · autosynth · search  │
├──────────────────────────────────────────────────────────────────┤
│ L4  Swarm            Topology × Consensus · Spawner · Roles      │
├──────────────────────────────────────────────────────────────────┤
│ L3  Healing          ErrorType · CircuitBreaker · attach_healing │
├──────────────────────────────────────────────────────────────────┤
│ L2  Tools            ToolRegistry · MCP · CLI · computer/browser │
├──────────────────────────────────────────────────────────────────┤
│ L1  Memory           ReasoningBank · GitJournal · ObsidianVault  │
├──────────────────────────────────────────────────────────────────┤
│ L0  Kernel           AgentLoop · HookBus · ProviderProfile       │
└──────────────────────────────────────────────────────────────────┘
                              ▲
                              │
                  ┌───────────┴───────────┐
                  │ Recursion (cross-cut) │
                  │ TraceAnalyzer +       │
                  │ propose_with_llm +    │
                  │ recurse_once()        │
                  └───────────────────────┘
```

**Layer ordering rule:** L0 imports nothing above. L1–L7 may import only
from layers strictly below. The hook bus is the cross-cutting seam — higher
layers subscribe; they don't reach down through internals.

## L0 — Kernel (`forge/kernel/`)

The agent loop, hook lifecycle, and provider abstraction.

- `loop.py::AgentLoop` — drives `Message → ToolCall → ToolResult → Message`.
  Walks message history backward to extract the last non-empty assistant
  text on `max_turns` exit (fixes the empty-verdict bug when the loop
  terminates mid-tool-call).
- `hooks.py::HookBus` — fires `SessionStart`, `PreToolUse`, `PostToolUse`,
  `Stop`, `PreCompact`, `SessionEnd`. Each hook returns a `Verdict`:
  `READY` / `WARNING` / `BLOCKED` / `SAFETY_BLOCKED`. `SAFETY_BLOCKED` is
  bypass-immune — no `permission_mode`/AUTO escalation can downgrade it.
  Dry-run is a first-class mode: hooks can short-circuit a tool call before
  side effects.
- `profile.py::ProviderProfile` + `load_profile()` — YAML-driven model adapter.
  Profile declares: prompt format, tool-call protocol, max tokens, cost tier,
  failover chain. Kernel never imports a vendor SDK directly.

## L1 — Memory (`forge/memory/`)

- `reasoning_bank.py::ReasoningBank` — vector store with the 5-stage loop:
  `RETRIEVE → JUDGE → DISTILL → CONSOLIDATE → ROUTE`. Pluggable embedders
  (hash / OpenAI / Voyage / ONNX MiniLM).
- `git_journal.py::GitJournal` — Anthropic-paper "git as session journal":
  resume by reading `git diff HEAD~N`.
- `obsidian.py::ObsidianVault` — wiki-link parser + backlinks graph +
  frontmatter. Notes are first-class.
- `genome.py::genome()` — process-wide singleton at `~/.forge/genome.json`.
  Cross-project learnings compound here.
- `claude_dir.py::ClaudeDir` — filesystem contract for per-project state.

## L2 — Tools (`forge/tools/`)

Three-tier fall-through (lifted from `coo-agent/SOUL.md`):

1. **MCP** (cleanest, structured) — `mcp_client.py::MCPClientPool` over the
   official `mcp` SDK; `composio_adapter.py` over the Composio SDK.
2. **Computer / Browser** — `builtin/browser.py` + computer-use shims.
3. **CLI shell** — `CLISubprocessTool` family (`ClaudeCodeTool`, `CodexCLITool`,
   `GeminiCLITool`). Even when the kernel runs DeepSeek, it can shell out to
   `claude code -p "<task>"` for hard refactors. **This is the model-
   agnosticism unlock.**

`ToolRegistry` enforces per-agent allow/deny. `Tool` self-describes via
JSONSchema (OpenHarness pattern).

## L3 — Healing (`forge/healing/`)

- `error_types.py::ErrorType` — 5-class taxonomy: `TRANSIENT` /
  `ENVIRONMENTAL` / `DATA` / `LOGIC` / `RESOURCE`. Regex classifier maps
  exception strings to types.
- `circuit_breaker.py::CircuitBreaker` — CLOSED → OPEN (3-fail trip) →
  HALF_OPEN (60-min cooldown, 50% recovery throughput). Ported from
  `social-sdr/scripts/self_heal.py`.
- `denial.py::DenialTracker` — prevents pathological denied-tool loops.
  After N denials of the same `(agent, tool, args)` within a window, the
  pre-tool hook emits `SAFETY_BLOCKED` (bypass-immune).
- `hooks.py::attach_healing()` — wires per-tool breakers + the
  `DenialTracker` into the L0 hook bus via `PreToolUse` / `PostToolUse`.
  Healing is a hook subscriber, not a kernel mod. Returns the
  `CircuitRegistry`; the bound tracker is exposed as `circuits.denials`.

## L4 — Swarm (`forge/swarm/`)

- `topology.py::Topology` — `SOLO` / `PARALLEL_COUNCIL` / `HIERARCHY` / `MESH`.
- `consensus.py::Consensus` — `MAJORITY` / `WEIGHTED` / `UNANIMOUS` / `QUEEN`.
- `spawner.py::Spawner` — runs a `SwarmSpec` and aggregates `SwarmResult`.
- `roles.py::RoleCouncilSpawner` — injects per-member system prompts
  (optimist / skeptic / pragmatist) so members actually disagree.

## L5 — Skills (`forge/skills/`)

- `skill.py::SkillStore` — versioned `SKILL.md` + per-version `runs.jsonl`.
- `eval_gate.py::EvalGate` — `MIN_SAMPLES=50`, `CONFIDENCE_MARGIN=0.05`.
  Ported verbatim from Orgo's `self_improve.py`.
- `autosynth.py` — proposes new/improved skills from outcome history.
- `search.py::SkillSearchIndex` — vector index over body + outcomes.

## L7 — Observability (`forge/observability/`)

- `trace.py::TraceStore` — full-fidelity JSONL per session.
  **Compaction allowed for the agent, never for the optimizer.**
- `telemetry.py::Telemetry` — token + cost per agent / skill / provider,
  with per-profile pricing tables.
- `otel.py::OTelExporter` — no-op when `opentelemetry` isn't installed.
- `dashboard/` — read-only CLI (`forge dashboard`).

## Recursion (cross-cutting, `forge/recursion/`)

The recursive self-modification loop (Meta-Harness invariant):

1. `TraceAnalyzer` reads `traces/*.jsonl` from the session home.
2. `propose_with_llm()` sends traces to a real provider with the AutoAgent
   regularizer in the system prompt: *"Would this still help if this
   specific task vanished?"*
3. Output diffs respect `# === FIXED ADAPTER BOUNDARY ===` — proposer
   may not modify lines below this sentinel.
4. `recurse_once()` forks, applies, scores both copies, decides keep-or-
   rollback, appends to `ResultsLedger` (TSV).

## Where MCP lives

Two-way: forge **consumes** MCP tools (`MCPClientPool` connects to any stdio
or HTTP MCP server) and forge **exposes** itself as MCP (`forge/mcp_server.py`
serves 12 tools: `forge_council`, `forge_recurse`, `forge_vault_*`,
`forge_memory_*`, `forge_skill_*`, `forge_doctor`, `forge_dashboard`).

## Filesystem contract

```
~/.forge/
  .env                       # vendor keys (auto-loaded)
  genome.json                # cross-project ReasoningBank
  vault/                     # default ObsidianVault root
  <session-home>/
    .claude/                 # per-session state
    traces/<run_id>/
      messages.jsonl
      tool_calls.jsonl
      artifacts/
    skills/<name>/
      SKILL.md
      runs.jsonl
    healing/
      circuits.json
    results-ledger.tsv       # recursion outcomes
```

## What changes between minor versions

Everything is pre-1.0. Breaking changes are allowed in minor bumps with a
CHANGELOG entry. The `__all__` symbols in `forge/__init__.py` are the
public contract — removing one bumps minor.

## What never changes

- Layer ordering (L0 imports nothing above).
- The hook bus shape (`SessionStart`, `PreToolUse`, `PostToolUse`,
  `SessionEnd` + `Verdict` enum).
- `# === FIXED ADAPTER BOUNDARY ===` sentinel — the recursion proposer
  contract.
- Trace fidelity (no upstream compaction before the optimizer reads).
