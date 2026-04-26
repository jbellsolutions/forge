# Changelog

All notable changes to forge are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and forge adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) starting with v0.1.0.

## [Unreleased]

### Added
- **Industry intel — passive pull pipeline (`forge.intel`)** — daily
  ingestion of RSS / Atom / GitHub releases / JSON changelogs / HTML
  pages from a hard-coded `DOMAIN_ALLOWLIST` (anthropic / openai /
  github.com/{anthropics,openai,modelcontextprotocol,ComposioHQ,kevinrgu}
  / mcp / huggingface / etc). Stdlib-only fetching (`urllib`,
  `xml.etree`, `json`); no `requests`, no `feedparser`. Public surface:
  `IntelItem`, `Source`, `pull_intel`, `IntelDigest`, `build_intel_digest`,
  `store_items`, `load_sources`, `is_allowed`. New CLI: `forge intel
  pull|show`. Default 10 sources covering Claude / OpenAI / Composio /
  MCP / AutoAgent — overridable via `~/.forge/intel/sources.yaml`.
  Dedup across runs via `<home>/intel/seen.json`. Items persisted three
  ways: `<home>/intel/<YYYY-MM-DD>.json` (machine-read), `<home>/vault/
  intel/<source>/<slug>.md` (Obsidian backlinks graph picks them up),
  and top-3 high-relevance items distilled into `genome()` for cross-
  project compounding. Live verification: 156 items pulled across 10
  sources; 66 high / 70 med relevance; 20 low (dropped from digest).
- **`Element.__bool__` correctness fix** — Atom feed parser uses
  `is not None` checks instead of `el.find(...) or el.find(...)`,
  which Python 3.14 short-circuits incorrectly when an element has
  no children (e.g. self-closing `<link href="..."/>`). Caught by
  the test fixture; would have silently dropped Atom items in
  production.
- **Self-improvement reporting (L7)** — daily/weekly digest aggregating
  recursion ledger outcomes, skill creations + promotions + rollbacks,
  denial-loop events, telemetry rollup, genome growth, and intel highlights.
  Public surface: `Digest`, `build_digest`, `Delivery`, `MarkdownFileDelivery`,
  `SlackMCPDelivery`, `make_delivery`, `deliver`. New CLI: `forge report
  --period day|week --to file|slack-mcp|auto`. Heartbeat:
  `examples/heartbeats/daily_report.md`. Privacy invariant enforced:
  digest output never contains message content or vendor key prefixes;
  regex-asserted in `tests/test_digest.py`. Slack delivery uses the
  user's existing Slack MCP server via `MCPClientPool`; fails gracefully
  to file delivery on any import / pool / tool-call error so the digest
  is never lost.
- **`heartbeat.run_one` accepts `command:` frontmatter** — runs an
  arbitrary command (e.g. `forge report ...`) in addition to the
  existing `agent:` mode. Backward-compatible.
- **L3 `DenialTracker`** (`forge.DenialTracker`) — prevents pathological
  denied-tool loops. Records (agent, tool, args) → recent denials; after
  `max_repeats=3` denials within `window_seconds=600`, subsequent calls
  emit `Verdict.SAFETY_BLOCKED` (bypass-immune). Auto-wired by
  `attach_healing()` and exposed as `circuits.denials`. Lifted from
  Claude Code's `permissions.ts` denial state tracking.
- **`Tool.concurrency_safe`** ClassVar (default `False`) — declares whether
  a tool has no observable side effects on shared state and may be batched
  in parallel. `FSReadTool` marked `True`. Surfaced in `Tool.schema()`
  for downstream orchestrators. Lifted from Claude Code's
  `Tool.isConcurrencySafe`.
- **`FSWriteTool` read-before-write contract** — refuses to overwrite an
  existing file unless the agent's `FSReadTool` recorded a fresh read of
  it (or the caller passes `force=True`). Closes a stale-overwrite race
  between parallel sub-agents. Read state lives on the paired
  `FSReadTool._read_state`. Lifted from Claude Code's `FileEditTool`
  `readFileState` check.
- **`HookBus.on_stop` / `on_pre_compact`** — two new lifecycle events.
  `Stop` fires when the loop is about to terminate a turn (final
  reflection seam for the recursion proposer). `PreCompact` fires before
  the agent's working context is compacted (does not affect TraceStore,
  which is full-fidelity by invariant).
- **`Verdict.SAFETY_BLOCKED`** — bypass-immune tier; stands regardless of
  `permission_mode`/AUTO escalation. New `HookContext.safety_block(msg)`
  helper. Severity ranking now `READY < WARNING < BLOCKED < SAFETY_BLOCKED`;
  most-restrictive wins across multiple hooks. Lifted from Claude Code's
  bypass-immune safety-check class.
- "Skill obsession" guidance in `CLAUDE.md` and `AGENTS.md` — tells contributors
  and runtime agents to search forge's L5 (`SkillStore` + `SkillSearchIndex` +
  `autosynth` + `EvalGate`) before re-authoring a capability. Documentation
  only; no parallel skill registry, no new code. Fills the AGI-1 skill-master
  Phase 5 (Obsession Injection) intent using forge's own L5 primitives instead
  of a duplicate `.claude/skill-mastery/` store.

### Fixed
- `HookBus.fire_pre_tool` now honors the `Verdict` returned by a hook handler,
  not just `ctx.verdict`. Earlier the return value was silently discarded,
  contradicting the documented "hooks return ready/warning/blocked" contract
  (ARCHITECTURE.md, CLAUDE.md). Both patterns are now accepted; across multiple
  hooks the most-restrictive verdict wins (BLOCKED > WARNING > READY).
- Two regression tests added (`test_hook_return_verdict_honored`,
  `test_hook_most_restrictive_wins`).

## [0.1.1] — 2026-04-26

Documentation-only patch. README rewritten as a full product narrative —
research story (16 sources, 3 clusters, 3-round analysis loops),
architecture explanation, live verification table with real numbers,
debug notes covering eight real fixes, full SDK API surface map,
architecture references with links, roadmap. PyPI project page now shows
the long-form description. No code changes.

## [0.1.0] — 2026-04-26

First public release. Full 8-layer harness, MCP server, Claude Code skill +
slash command, GitHub-published.

### Added
- **L0 kernel:** `AgentLoop`, `HookBus` lifecycle (`SessionStart` /
  `PreToolUse` / `PostToolUse` / `SessionEnd`), `Verdict` (READY / WARNING /
  BLOCKED), `AgentDef`, provider-as-profile YAML loader.
- **L1 memory:** `ReasoningBank` (RETRIEVE→JUDGE→DISTILL→CONSOLIDATE→ROUTE)
  with pluggable embedders (hash / OpenAI / Voyage / ONNX MiniLM); `GitJournal`
  for resumable sessions; `ObsidianVault` with wiki-link parsing, backlinks
  graph, and frontmatter; cross-project genome at `~/.forge/genome.json`;
  `ClaudeDir` filesystem contract.
- **L2 tools:** `ToolRegistry` with three-tier classification
  (mcp / computer_browser / cli), per-agent allow/deny enforcement; built-in
  `ShellTool`, `FSReadTool` / `FSWriteTool` (sandbox-anchored),
  `HttpFetchTool`, `EchoTool`, Obsidian tools, `CLISubprocessTool` family
  (`ClaudeCodeTool`, `CodexCLITool`, `GeminiCLITool`); real `MCPClientPool`
  over the official `mcp` SDK; `ComposioAdapter` over the Composio SDK;
  in-process MCP adapter for tests.
- **L3 healing:** `ErrorType` taxonomy + regex classifier; `CircuitBreaker`
  with CLOSED / OPEN / HALF_OPEN transitions; `CircuitRegistry`;
  `attach_healing(hooks)` to wire breakers into the hook bus.
- **L4 swarm:** `Topology` × `Consensus` enums; `Spawner` for solo /
  parallel-council / hierarchy; `RoleCouncilSpawner` injecting per-member
  system prompts (optimist / skeptic / pragmatist).
- **L5 skills:** `SkillStore` with versioned `SKILL.md` + per-version
  `runs.jsonl`; `EvalGate` (`MIN_SAMPLES=50`, `CONFIDENCE_MARGIN=0.05`);
  autosynth proposer; `SkillSearchIndex` over body + outcomes.
- **L7 observability:** `TraceStore` writing full-fidelity JSONL per session;
  `Telemetry` with per-profile pricing tables; `OTelExporter` (no-op when
  `opentelemetry` is not installed); read-only `dashboard` CLI.
- **Recursion:** `TraceAnalyzer`, rule-based `propose()`, LLM-driven
  `propose_with_llm()` honoring the AutoAgent regularizer ("would this still
  help if this specific task vanished?"), `# === FIXED ADAPTER BOUNDARY ===`
  sentinel, `ResultsLedger` (TSV); `recurse_once()` orchestrator.
- **CLI:** `forge` console script with subcommands `doctor`, `run`, `recurse`,
  `recurse-loop`, `dashboard`, `skill`, `vault`, `heartbeat`, `mcp`.
- **MCP server:** 12 tools (`forge_council`, `forge_recurse`, `forge_vault_*`,
  `forge_memory_*`, `forge_skill_*`, `forge_doctor`, `forge_dashboard`).
- **Claude Code integration:** slash command `~/.claude/commands/forge.md` +
  skill `~/.claude/skills/forge/SKILL.md`, both with auto-trigger triggers.
- **Schedulers:** crontab, launchd, GitHub Actions templates under
  `forge/scheduler/`.
- **Examples:** mock `operator` vertical, real-MCP `operator_real` (basic +
  tool-using council), `recursion_demo` for the full self-mod cycle.
- **Tests:** 70 passing across kernel, providers, tools, healing, swarm,
  memory, skills, observability, recursion, CLI.

### Notes
- macOS Sonoma+ sets `com.apple.provenance` xattr (UF_HIDDEN) on files which
  causes Python 3.14 to skip `.pth` editable-install markers. Workaround:
  `.venv/bin/forge` is a bash wrapper exporting `PYTHONPATH`; the editable
  install still works for direct `python -m forge.cli` invocations.
- The Anthropic + OpenRouter + Composio integrations are LIVE-VERIFIED:
  council emits real verdicts (~$0.10/run), recursion proposer emits
  regularizer-honoring diffs against real traces, Composio sees 1,048 apps,
  OpenRouter routes to DeepSeek-chat correctly.
