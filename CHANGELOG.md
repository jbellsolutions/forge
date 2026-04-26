# Changelog

All notable changes to forge are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and forge adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) starting with v0.1.0.

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
