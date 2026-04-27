# forge — Self-Improvement Reporting + Industry Intel Loop

## Context

forge already self-improves (recursion proposer + EvalGate + autosynth). The
gap is **visibility** and **external signal**:

1. **Visibility** — when forge mutates itself, promotes skills, trips denial
   loops, or rolls back a candidate, none of that surfaces. Justin wants a
   daily/weekly Slack digest of "what forge learned today."
2. **External signal** — forge today only reads its own traces. The user
   already does a daily industry-update routine across Anthropic, OpenAI,
   open-source, Composio, MCP, etc. We want forge to ingest that signal
   and feed it into its own recursion loop, so the harness stays cutting-edge
   instead of drifting from local-context-only mods.
3. **Active auto-research, not just passive feed reading** — at least
   weekly (daily lightweight, weekly heavy), forge should run an
   **AutoAgent-style cycle**: spawn a sub-agent with **web-search +
   web-fetch tools** and a system prompt grounded in the AutoAgent
   regularizer, instruct it to investigate what Claude / OpenAI / Meta-
   Harness / Composio / open-source SDKs have published since the last
   cycle, synthesize findings, and feed them into `recurse_once` as
   first-class intel context. Reference: https://github.com/kevinrgu/autoagent
   — review during implementation for any patterns forge hasn't already
   absorbed (forge already uses the regularizer; check for tool-during-
   proposal, multi-step verification, counterfactual scoring patterns).
4. **Visibility + control via a Railway-hosted, simple, light-mode dashboard.**
   A web UI live on the public internet (not localhost — needs to survive
   laptop sleep / restart and be reachable from anywhere). Locked
   constraints from the user:
   - **Hosted on Railway**, not locally — Railway URL is the entry point.
   - **Backed by a real database** (Postgres on Railway addon). Forge local
     runtime stays the source of truth for `~/.forge/` filesystem
     artifacts; a sync pushes deltas to the cloud DB.
   - **Three nav tabs only**: `Workspace` · `Changelog` · `Genome`.
     - **Workspace** (single page, no internal tabs): agents list on the
       left grouped by project (or by use-case if no project assigned),
       orchestrator chat on the right. Click any agent → side panel with
       full detail (system prompt, tools, recent runs, telemetry) and
       — where v1 supports it — fields to make changes; otherwise the
       user asks the orchestrator to make the change.
     - **Changelog**: time-ordered feed of every improvement run. Daily
       digest entries, recursion ledger rows, skill creations + promotions,
       intel pull summaries, auto-research outputs, kept/rolled mods.
       Reads from the same artifacts the Slack delivery does — single
       source of truth, multiple views.
     - **Genome**: visualization of the cross-project `ReasoningBank` at
       `~/.forge/genome.json` (synced to cloud). Shows recent additions,
       top-confidence memories, tag clouds, search.
   - **Orchestrator = the "Papa/Mama Bear" agent**: one persona that holds
     full context across every project + every agent + every recent
     improvement. Can answer questions, spawn agents, scaffold new
     projects, propose updates to existing agents. Mutations flow through
     a `pending_actions` queue (cloud) that local forge polls + applies on
     a 5-minute heartbeat (so the cloud orchestrator can issue real
     local-runtime changes without needing remote shell access).
   - **Light mode default**, very simple visual style.
   - This explicitly reverses the prior ETHOS non-goal "Not a UI" and
     also softens "Not a hosted service" — documented in CHANGELOG and
     ETHOS.md as a v1 concession to make self-improvement legible.

User-locked decisions (from clarifying questions):
- **Intel autonomy**: store + inject + **auto-recurse daily, eval-gated**.
  EvalGate / score / rollback still guard every mod — nothing ships unless
  it beats baseline. Expected cost ~$0.10/day.
- **Slack delivery**: use the **existing Slack MCP connector** (no new SDK
  dep), launched via forge's existing `MCPClientPool` pattern.
- **Report detail**: **full transparency** — recursion deltas, kept/rolled
  candidates, denial-loop triggers, skill promotions, error classes.

## Build on existing primitives (do NOT re-author)

| Need | Reuse |
|---|---|
| Daily/weekly cadence | `forge/scheduler/heartbeat.py::run_all` (markdown-as-cron) |
| Telemetry rollup | `forge/observability/telemetry.py::Telemetry.summary()` |
| Session aggregation | `forge/observability/dashboard.py::summarize(home)` |
| Recursion outcomes | `forge/recursion/loop.py::ResultsLedger` (TSV) |
| Skill events | `forge/skills/skill.py::SkillStore.runs(name, version)` |
| Skill promotions | `forge/skills/eval_gate.py::promote_if_passing` (already logs) |
| Denial loops | `forge/healing/denial.py::DenialTracker._by_agent` |
| Memory growth | `forge/memory/genome.py::genome()` (size + recent additions) |
| Vault writes | `forge/memory/obsidian.py::ObsidianVault` |
| MCP client launch | `forge/tools/mcp_client.py::MCPClientPool, load_mcp_servers` |
| Recursion proposer | `forge/recursion/llm_proposer.py::propose_with_llm` (extend with optional `intel_context` param) |
| Recursion driver | `forge/recursion/loop.py::recurse_once` (extend to thread intel through) |

## New code (additive, no layer-ordering changes)

### A. Self-improvement reporting (L7 observability layer)

**New file: `forge/observability/digest.py`** (~120 lines)
- `@dataclass DailyDigest` and `@dataclass WeeklyDigest`: counts, deltas,
  cost, tokens, top denials, top errors by `ErrorType`, skills created /
  promoted / rolled-back, recursion ledger rows for the period, genome
  size delta, top 5 vault notes added.
- `def build_digest(home: Path, period: Literal["day","week"], at: datetime | None = None) -> Digest`
  reads existing artifacts:
  - `<home>/results.tsv` → recursion rows in window
  - `<home>/skills/<name>/runs.jsonl` → skill outcomes in window
  - `<home>/traces/<sid>/events.jsonl` → denial events (`verdict in {BLOCKED, SAFETY_BLOCKED}`) in window
  - `Telemetry` rollup via `dashboard.summarize(home)` filtered by ts
  - `genome().distill_history` (if exists) → otherwise diff genome size
- Returns a structured object PLUS `.to_markdown()` and `.to_json()` views.
- **Privacy invariant**: digest contains counts, names, and outcome scores —
  NEVER full message content from `messages.jsonl`. Documented at top of file.

**New file: `forge/observability/delivery.py`** (~140 lines)
- `class Delivery(ABC)`: `async def send(self, digest: Digest) -> None`
- `class MarkdownFileDelivery(Delivery)`: writes to `<home>/digests/<period>-<date>.md`. The default; always available; the no-key fallback.
- `class SlackMCPDelivery(Delivery)`: lazy-imports nothing — uses forge's
  own `MCPClientPool`. Constructor: `(server_config: dict, channel: str, tool_name: str = "slack_send_message")`. `send` connects, calls the configured tool with `{channel, text: digest.to_markdown()}`, disconnects. If the call fails it transparently falls back to `MarkdownFileDelivery` and re-raises only after that succeeds.
- `def make_delivery(home: Path) -> Delivery`: factory. Reads
  `~/.forge/delivery.yaml` (`channel: slack-mcp | file`, `mcp_server: <name>`,
  `slack_channel: "#forge-updates"`). If missing → returns `MarkdownFileDelivery`.

**New CLI subcommand in `forge/cli.py`** (~30 lines added):
- `forge report --period {day,week} [--home PATH] [--to file|slack-mcp|auto] [--at YYYY-MM-DD]`
  - Builds digest, sends via configured delivery. `--to auto` reads `delivery.yaml`. Always also writes the markdown file (cheap audit trail).

**New heartbeat: `examples/heartbeats/daily_report.md`**
- Frontmatter: `schedule: "0 8 * * *"`, `agent: report`. Body invokes
  `forge report --period day --to auto`. Mondays additionally trigger
  `--period week`.

### B. Industry intel + active auto-research + auto-recurse (new top-level module)

**Two cycles, different budgets:**
- **Daily lightweight** (~$0.10 budget): RSS/changelog pull + dedup +
  short auto-research turn (≤4 tool calls) + `recurse_once` with intel.
- **Weekly heavy** (~$0.50–$1.00 budget, default Mondays): full AutoAgent-
  style sub-agent run with web-search + web-fetch enabled, ≤20 turns,
  investigates each tracked SDK's changelog/release notes, synthesizes
  a "what changed in the field this week" report, then feeds that into
  `recurse_once`. The weekly digest fed to Slack also includes the
  research summary so Justin sees the field-wide deltas.

**New module: `forge/intel/`** (mirrors layer position of `forge/recursion/` — cross-cutting; imports from L1, L2, L7; is allowed to import the recursion layer since intel feeds into it).

- `forge/intel/__init__.py` — re-exports `IntelItem`, `pull_intel`, `inject_into_recursion`.
- `forge/intel/sources.py` (~80 lines): default sources list inline (Anthropic
  changelog, OpenAI blog RSS, Composio releases, MCP changelog, OpenAgents repo
  releases, AnthropicQuickstarts, Hermes/Ruflo/Meta-Harness GitHub release
  feeds). User overrides via `~/.forge/intel/sources.yaml`. Each source has
  `kind: rss|atom|github_releases|json_changelog|html`, `url`, `tags`.
  **Domain allowlist** enforced on every URL — typo'd source can't pivot to
  arbitrary endpoints.
- `forge/intel/fetch.py` (~100 lines): `async pull_intel(home: Path, sources: list[Source]) -> list[IntelItem]`. Uses stdlib `urllib.request` (no new dep) with timeout + small retry. Parses RSS/Atom via stdlib `xml.etree`, GitHub releases via JSON, plain HTML via simple regex extract of `<title>`/`<h1>`. Dedup against `~/.forge/intel/seen.json` (by `(source, url)` hash).
- `forge/intel/normalize.py` (~60 lines): `IntelItem(source, title, url, summary, ts, tags)` dataclass. Truncates summaries to 400 chars. Runs through a 1-shot Haiku call (cheapest profile, ~fractions-of-a-cent) to produce a neutral 2-sentence relevance summary tagged with `relevance ∈ {high, med, low}` for forge keywords (`agent harness`, `mcp`, `tool use`, `swarm`, `eval gate`, `reasoning bank`, etc.). High/med survive; low gets dropped. **Falls back to raw title if Haiku unavailable** (no key) — no hard dep.
- `forge/intel/digest.py` (~80 lines): `IntelDigest` dataclass + `build_intel_digest(items: list[IntelItem]) -> IntelDigest`. Groups by source + tag, ranks by relevance, caps at top 12 items. Has `.to_recursion_context() -> str` that renders a compact bullet list for injection.
- `forge/intel/store.py` (~50 lines): persists IntelItems to `~/.forge/intel/<YYYY-MM-DD>.json` AND writes them as Notes into `ObsidianVault` under `intel/<source>/<title>.md` with frontmatter (so backlinks graph picks them up) AND distills the top-3 high-relevance items into `genome()` for cross-project compounding.

**Web tools (new L2 builtins) — gives the auto-research sub-agent real reach:**

- `forge/tools/builtin/web_search.py` (~80 lines): `WebSearchTool`. Pluggable backend: `tavily` (preferred — free tier, agent-friendly JSON), `brave`, `duckduckgo`. Reads backend choice + API key from `~/.forge/.env`. Lazy-imports the chosen client. **`concurrency_safe = True`** (read-only). Falls back to `urllib`-based DuckDuckGo lite endpoint if no key present (no hard dep). Tier `mcp` (network).
- `forge/tools/builtin/web_fetch.py` (~50 lines): `WebFetchTool`. Wraps stdlib `urllib.request` with timeout + size cap + domain allowlist (defaults to a safe public-docs list, expandable via env). Returns the `<title>` + first 8KB of cleaned text. **`concurrency_safe = True`**. Tier `mcp`.
- Both register in `forge/tools/__init__.py` and surface in `Tool` / `ToolRegistry` with deny-list semantics so personas without web access don't get them by default.

**Auto-research sub-agent (the AutoAgent loop):**

- `forge/intel/auto_research.py` (~180 lines):
  - `async def run_auto_research(home: Path, *, profile: str = "anthropic-haiku", budget: AutoResearchBudget) -> AutoResearchResult`
  - Spawns a fresh `AgentLoop` with a tightly-scoped `ToolRegistry`: only `WebSearchTool`, `WebFetchTool`, `forge_memory_remember` shim (writes to genome), and `intel_store_item` (writes to today's intel JSON). No file write, no shell — research is read-only against the world and write-only into intel artifacts.
  - System prompt: derived from the AutoAgent paper. Includes the same regularizer wording forge's recursion proposer already uses ("only surface findings that would still matter if THIS specific task vanished — i.e. is this a durable shift or noise?"). Prompt instructs the agent to: list the tracked SDKs, search each for changes since `<last_run_ts>`, fetch the top result per SDK, summarize, store as IntelItems with `relevance` tag, then emit a final "would-this-still-matter" rationale per item.
  - `AutoResearchBudget` dataclass: `max_turns`, `max_cost_usd`, `max_tool_calls`. Daily defaults: `(4, 0.15, 8)`. Weekly defaults: `(20, 1.00, 40)`. Telemetry-enforced via existing `Telemetry.attach(hooks)`; if `cost_usd >= max_cost_usd` mid-run, a `PreToolUse` hook returns `Verdict.SAFETY_BLOCKED` and the loop terminates cleanly.
  - Output: `AutoResearchResult{ items_added: int, sources_investigated: list[str], summary_md: str, ledger_row: dict }`. Appends a row to `~/.forge/intel/auto-research.tsv` (parallel to recursion's `results.tsv`) with `(ts, profile, turns, tool_calls, cost_usd, items, kept_after_recurse)`.
  - The summary_md feeds directly into `recurse_once(..., intel_context=summary_md)`.

- **AutoAgent repo review (one-time during implementation, ~30 min)**: clone https://github.com/kevinrgu/autoagent locally, scan for patterns forge doesn't have. Already absorbed: regularizer wording. Specifically look for: (a) tool-use during proposal phase (vs forge's current "read static traces, propose"), (b) multi-step verification before commit, (c) counterfactual scoring formulas, (d) self-tuning of the regularizer threshold. Lift any one of these as a follow-up task — do NOT block this build on it. Document findings inline in `forge/intel/auto_research.py` docstring.

**Recursion proposer extension** (small, additive — does NOT break callers):

- `forge/recursion/llm_proposer.py::propose_with_llm` gains optional kwarg
  `intel_context: str | None = None` (default `None` — old behavior).
  When supplied, prepended to the system prompt under a header:
  ```
  Recent industry signals (informational only):
  <context>
  AutoAgent regularizer still applies: only propose mods that would help
  even if these specific signals vanished from the context.
  ```
  Regularizer wording unchanged. Intel is context, not a license.
- `forge/recursion/loop.py::recurse_once` gains optional kwarg
  `intel_context: str | None = None`, threaded through to the proposer.

**New CLI subcommands in `forge/cli.py`** (~80 lines added):
- `forge intel pull [--home PATH] [--sources PATH] [--dry-run]` — passive RSS/changelog fetch + normalize + persist.
- `forge intel research [--home PATH] [--budget daily|weekly] [--profile PROF]` — runs `run_auto_research` with the given budget. Default `daily`.
- `forge intel show [--home PATH] [--at YYYY-MM-DD]` — print today's combined intel + auto-research digest as markdown.
- `forge recurse --with-intel` flag — reads today's intel digest + last auto-research summary, passes both as `intel_context`.

**New heartbeats:**
- `examples/heartbeats/daily_intel.md` — frontmatter `schedule: "0 7 * * *"`, `agent: intel`. Body invokes:
  1. `forge intel pull` (passive RSS/changelog)
  2. `forge intel research --budget daily` (lightweight active loop)
  3. `forge recurse --with-intel`
  4. Result lands in `results.tsv`; the 08:00 daily report picks it up.
- `examples/heartbeats/weekly_research.md` — frontmatter `schedule: "0 6 * * 1"` (Mondays 6am), `agent: intel`. Body invokes:
  1. `forge intel research --budget weekly --profile anthropic` (heavy active loop, Sonnet, ~$1 budget)
  2. `forge recurse --with-intel` (proposer sees the rich weekly summary)
  3. The Monday daily report picks up both the weekly summary AND any kept candidate.

### C. Dashboard + Orchestrator + Cloud Sync (Railway-hosted)

**Architecture (split-brain, deliberate):**

```
   ┌────────────────────┐       ┌──────────────────────────┐
   │   LOCAL forge      │       │   RAILWAY (public URL)   │
   │   ~/.forge/...     │       │                          │
   │   filesystem TOT   │◀────▶│   FastAPI dashboard      │
   │                    │ sync  │   + Postgres (DATABASE_URL)│
   │   forge sync push  │──────▶│                          │
   │   forge sync pull  │◀──────│   pending_actions table  │
   │   (5-min heartbeat)│       │   ◀──── orchestrator chat│
   └────────────────────┘       └──────────────────────────┘
```

- Local forge is the runtime + filesystem source of truth.
- Cloud Postgres is the network-accessible mirror + control plane.
- Dashboard is read against Postgres + write to `pending_actions`.
- Local `forge sync pull-actions` heartbeat applies pending mutations.
- This keeps tool execution, vault, traces, recursion local (where the
  files and CLIs live) while making visibility + orchestrator chat
  cloud-hosted (so Justin can use it from anywhere).

**Stack — deliberately boring, no build pipeline:**
- Backend: **FastAPI** + **Uvicorn** (production-ready, async, OpenAPI auto-docs at `/docs` for self-debugging). Lazy-imported, optional `[dashboard]` extra.
- DB: **Postgres** on Railway (free addon). ORM: **SQLModel** (FastAPI-native, type-safe). Migrations: **Alembic** (autogenerated). Local dev / tests use SQLite (SQLModel supports both).
- Frontend: server-rendered Jinja2 HTML + **HTMX** + **Tailwind CSS via CDN**. Zero npm. Light mode default (`bg-slate-50 text-slate-900`).
- Auth: single shared password via `DASHBOARD_PASSWORD` env var (bcrypt-hashed at startup); session cookies. Optional `--token` query string for embedding scenarios.
- Deploy: Railway nixpacks autodetect Python; `Procfile` declares the web entry; `railway.json` pins the build. Postgres provisioned via Railway addon. CI workflow under `.github/workflows/deploy-dashboard.yml` does Railway deploy on tagged release.

**`forge/dashboard/` — FastAPI app (~600 lines split across files):**

- `forge/dashboard/__init__.py` — re-exports `app` (the FastAPI instance), `db_init`, `Settings`.
- `forge/dashboard/settings.py` (~40 lines): pydantic-settings reading `DATABASE_URL`, `DASHBOARD_PASSWORD`, `ANTHROPIC_API_KEY` (orchestrator), `RAILWAY_STATIC_URL`.
- `forge/dashboard/db.py` (~150 lines): SQLModel models:
  - `Project(id, name, slug, created_at)` — projects group agents.
  - `AgentRow(id, project_id, name, profile, instructions, tools_allowed, tools_denied, status, created_at, last_seen_at, total_runs, total_cost_usd)` — mirror of every `AgentDef` known.
  - `RunRow(id, agent_id, session_id, started_at, ended_at, tool_calls, tool_errors, blocked, input_tokens, output_tokens, cost_usd)` — mirror of `SessionStat`.
  - `ChangelogEntry(id, ts, kind ∈ {recursion, skill_promo, skill_create, intel_pull, auto_research, mod_kept, mod_rolled, denial_loop, circuit_open}, title, body_md, ref_path)`.
  - `GenomeMemory(id, mem_id, text, tags, confidence, ts)` — mirror of `~/.forge/genome.json`.
  - `PendingAction(id, kind ∈ {spawn_agent, update_agent, start_project, run_recurse}, payload_json, status ∈ {pending, applied, rejected, expired}, proposed_by, proposed_at, applied_at, applied_diff_json)`.
  - `OrchestratorMessage(id, session_id, role, content, ts)` — chat history.
- `forge/dashboard/server.py` (~150 lines): FastAPI route table. **Three tabs**, single page for tab 1:
  - `GET /` → redirects to `/workspace`.
  - `GET /workspace` — split-pane: agents grouped by project on the left, orchestrator chat on the right. Same page; no internal tabs.
  - `GET /workspace/agents/{id}` — HTMX-loaded right-side panel with agent detail (system prompt, tools, last 20 runs, telemetry, trace links, "ask orchestrator to change" CTA). For v1, fields the user can edit directly: `instructions` and `tools_denied` only. Everything else flows through the orchestrator.
  - `POST /workspace/agents/{id}/edit` — apply a v1-allowed direct edit; logged as `ChangelogEntry(kind="agent_edit")`.
  - `POST /orchestrator/turn` — SSE streaming chat turn against the orchestrator persona. The orchestrator may emit `propose_*` actions which appear inline as cards with Approve/Reject buttons.
  - `POST /actions/{action_id}/approve` — flips `pending_actions.status='approved'`. Local sync picks up on next pull.
  - `POST /actions/{action_id}/reject` — flips to `rejected`.
  - `GET /changelog` — feed of `ChangelogEntry` rows, paginated, filterable by kind.
  - `GET /genome` — paginated `GenomeMemory` browse + search. Tag-cloud sidebar.
  - `GET /healthz` — liveness for Railway.
  - `POST /sync/push` — local forge POSTs deltas here (auth via shared secret). Body is JSON of new agents / runs / changelog entries / genome updates since `since_ts`.
  - `GET /sync/pending` — local forge polls here for `status='approved'` PendingActions.
  - `POST /sync/applied/{action_id}` — local reports the applied diff back so the dashboard can display it.
- `forge/dashboard/templates/` — Jinja2 HTML files: `base.html`, `workspace.html`, `agent_panel.html`, `changelog.html`, `genome.html`, `chat_message.html`, `pending_action_card.html`, `login.html`.
- `forge/dashboard/static/htmx.min.js` (vendored) + `dashboard.js` (~50 lines for SSE + chat scroll).
- `forge/dashboard/auth.py` (~60 lines): bcrypt password check, signed-cookie session, login/logout endpoints, dependency function for protected routes.
- `forge/dashboard/migrations/` — Alembic config + initial revision.
- `Procfile` (repo root): `web: alembic upgrade head && uvicorn forge.dashboard.server:app --host 0.0.0.0 --port $PORT`
- `railway.json` (repo root): Python builder, no extra config needed (Railway auto-detects).

**`forge/sync/` — local↔cloud bridge (~200 lines):**

- `forge/sync/__init__.py` — re-exports `push_deltas`, `pull_pending_actions`, `apply_pending`.
- `forge/sync/state.py` (~40 lines): tracks `last_pushed_ts` per kind in `<home>/.forge/sync-state.json`.
- `forge/sync/push.py` (~80 lines): scans local artifacts (agents YAML in `<home>/agents/`, sessions in `<home>/traces/`, changelog events derived from `results.tsv` + skill promotions + denial events, genome JSON) since `last_pushed_ts`, POSTs JSON batch to `<RAILWAY_URL>/sync/push` with shared-secret header. Idempotent (server upserts by stable IDs).
- `forge/sync/pull.py` (~80 lines): GETs `/sync/pending`, returns approved `PendingAction`s. `apply_pending(action)` dispatches: `spawn_agent` → writes `<home>/agents/<name>.yaml`; `update_agent` → patches the YAML; `start_project` → scaffolds `examples/<name>/`; `run_recurse` → invokes `recurse_once` with optional intel context. POSTs the diff back via `/sync/applied`. All applies route through the standard `HookBus` (so `DenialTracker`, `CircuitBreaker`, `SAFETY_BLOCKED` all apply uniformly).
- New heartbeat: `examples/heartbeats/sync.md` — `schedule: "*/5 * * * *"`. Body: `forge sync push && forge sync pull-and-apply`.

**`forge/orchestrator/` — the Papa/Mama Bear agent (~280 lines):**

- `forge/orchestrator/__init__.py` — re-exports `OrchestratorAgent`, `propose_spawn`, `propose_update`, `propose_start_project`, `propose_run_recurse`.
- `forge/orchestrator/persona.md` — system prompt. Includes:
  - Full workspace context (rendered server-side from DB at chat-turn time): every Project + every AgentRow + open PendingActions + last 7 days of Changelog + top-confidence Genome memories.
  - The AutoAgent regularizer ("only propose mods that would still help if the user's specific request vanished").
  - Skill obsession (search SkillStore before authoring new logic).
  - Hard rule: `NEVER mutate state directly; always emit a propose_* tool call. The user must click Approve in the dashboard before anything happens.`
  - Voice: helpful, concise, asks one clarifying question max before proposing.
- `forge/orchestrator/agent.py` (~140 lines): `class OrchestratorAgent`. Constructor: `(db_session, profile="anthropic")`. `async chat_turn(session_id, user_msg) -> stream` — runs one `AgentLoop` turn against the persona with a tightly-scoped tool surface (`list_agents`, `agent_status`, `recent_changelog`, `genome_search`, `propose_spawn`, `propose_update`, `propose_start_project`, `propose_run_recurse`, web tools). Persists chat to `OrchestratorMessage`. Streams via SSE.
- `forge/orchestrator/actions.py` (~80 lines):
  - `propose_spawn(project, name, instructions, profile, tools_allowed, tools_denied) -> action_id` — INSERTs `PendingAction` row.
  - `propose_update`, `propose_start_project`, `propose_run_recurse` — same shape.
  - All return the new `action_id` so the orchestrator can reference it in chat. The dashboard automatically renders an Approve card for any pending action created in the current chat turn.
- `forge/orchestrator/templates/{operator,research,sdr,custom}.py` — project scaffolds. Each is a small Python module that, when applied locally, writes `examples/<name>/run.py`, `examples/<name>/heartbeats/*.md`, etc. Templates are lifted from existing `examples/operator/` + `examples/operator_real/`.

**New CLI in `forge/cli.py` (~50 lines):**
- `forge dashboard serve [--port N] [--host HOST] [--db DB_URL]` — local-dev entry that runs uvicorn against a local SQLite (so the user can test changes without deploying).
- `forge sync push [--home PATH] [--url URL] [--token TOK]` — one-shot delta push.
- `forge sync pull-and-apply [--home PATH] [--url URL] [--token TOK]` — one-shot pending-action pull + local apply.
- `forge sync daemon` — convenience: loops the above two every 5 min until interrupted.

### D. Tests (mirror existing layout)

- `tests/test_digest.py` (~140 lines): synthetic SkillStore + ResultsLedger + Telemetry inputs → assert digest dict shape, markdown rendering, no message-content leakage (regex-asserts `"role"` not in output).
- `tests/test_delivery.py` (~120 lines): MarkdownFileDelivery writes correct path + body. SlackMCPDelivery uses an in-process MCP adapter (forge already has `forge/tools/mcp_adapter.py` for tests); fail-path falls back to file.
- `tests/test_intel_fetch.py` (~120 lines): monkeypatched `urllib.request.urlopen` returning canned RSS/Atom/JSON. Asserts dedup against `seen.json`, asserts domain allowlist refuses out-of-list URL.
- `tests/test_intel_inject.py` (~80 lines): assert `propose_with_llm(intel_context="...")` adds the regularizer paragraph to the system prompt, asserts no-intel call is byte-identical to pre-change (backward-compat regression).
- `tests/test_web_tools.py` (~100 lines): `WebSearchTool` and `WebFetchTool` against monkeypatched `urlopen`; assert domain allowlist refusal, size cap, timeout. Assert `concurrency_safe=True` on both.
- `tests/test_auto_research.py` (~150 lines): `run_auto_research` with mock provider scripted to call `WebSearchTool` + `WebFetchTool` + `intel_store_item`; assert IntelItems written, ledger row appended, budget breach triggers `Verdict.SAFETY_BLOCKED` and clean termination. No live API call.
- `tests/test_dashboard.py` (~160 lines): boots the FastAPI app via `httpx.AsyncClient` against in-memory SQLite. Asserts all 3 nav tabs render with light-mode classes, `/orchestrator/turn` round-trips a mock-provider chat, `/actions/{id}/approve` requires a valid pending action + auth, `/healthz` returns 200, mutating endpoints reject GET.
- `tests/test_dashboard_auth.py` (~80 lines): bcrypt password check, login round-trip, protected routes 401 without session cookie.
- `tests/test_dashboard_db.py` (~100 lines): SQLModel CRUD for Project, AgentRow, ChangelogEntry, GenomeMemory, PendingAction. Idempotent upsert by stable ID.
- `tests/test_orchestrator.py` (~140 lines): `OrchestratorAgent.chat_turn` against the mock provider scripted to call `propose_spawn`. Assert PendingAction row inserted, asserted spawn does NOT mutate any AgentRow until approval flow completes. Round-trip a `propose_start_project` against a tiny vertical template; confirm pending row carries the right payload.
- `tests/test_sync.py` (~140 lines): full local↔cloud round-trip against in-memory SQLite. `push_deltas` reads synthetic local artifacts, posts via FastAPI test client; assert DB rows match. `pull_pending_actions` returns approved actions; `apply_pending` writes the right local files. Idempotent on retry.
- `tests/test_winning_patterns.py` already covers the proposer; that suite must stay green.

### D. Public surface updates

- `forge/__init__.py` adds re-exports (under L7 observability and a new
  "Intel" group): `Delivery`, `MarkdownFileDelivery`, `SlackMCPDelivery`,
  `make_delivery`, `DailyDigest`, `WeeklyDigest`, `build_digest`,
  `IntelItem`, `IntelDigest`, `pull_intel`, `build_intel_digest`. Adds to
  `__all__`. (~16 new symbols.)
- `CHANGELOG.md` under `[Unreleased]` documents both modules.
- `ARCHITECTURE.md` adds a "Reporting + Intel" subsection under the
  recursion cross-cut (since intel feeds into recursion).
- `forge/observability/__init__.py` re-exports digest + delivery.
- New `forge/intel/__init__.py` re-exports the intel surface.

### E. Configuration shipped (sample files only — user copies to live)

- `forge/intel/sources.default.yaml` — 7 sources, all on a domain allowlist
  (anthropic.com, openai.com, github.com/anthropics/*, github.com/openai/*,
  github.com/ComposioHQ/*, github.com/modelcontextprotocol/*, ai.googleblog.com).
- `forge/observability/delivery.example.yaml` — sample delivery config with both
  `slack-mcp` and `file` blocks; comments explain how to wire to the user's
  existing Slack MCP server entry.
- README gets a new "Daily Reports + Intel" section (~40 lines) documenting
  the feature, how to enable Slack MCP delivery, and the privacy invariant.

## Files to create / modify (precise)

**Create:**
- `forge/observability/digest.py`
- `forge/observability/delivery.py`
- `forge/observability/delivery.example.yaml`
- `forge/intel/__init__.py`
- `forge/intel/sources.py`
- `forge/intel/sources.default.yaml`
- `forge/intel/fetch.py`
- `forge/intel/normalize.py`
- `forge/intel/digest.py`
- `forge/intel/store.py`
- `forge/intel/auto_research.py`
- `forge/tools/builtin/web_search.py`
- `forge/tools/builtin/web_fetch.py`
- `forge/dashboard/__init__.py`
- `forge/dashboard/settings.py`
- `forge/dashboard/db.py`
- `forge/dashboard/server.py`
- `forge/dashboard/auth.py`
- `forge/dashboard/migrations/env.py` + initial Alembic revision
- `forge/dashboard/templates/{base,workspace,agent_panel,changelog,genome,chat_message,pending_action_card,login}.html`
- `forge/dashboard/static/htmx.min.js`
- `forge/dashboard/static/dashboard.js`
- `forge/sync/__init__.py`
- `forge/sync/state.py`
- `forge/sync/push.py`
- `forge/sync/pull.py`
- `forge/orchestrator/__init__.py`
- `forge/orchestrator/persona.md`
- `forge/orchestrator/agent.py`
- `forge/orchestrator/actions.py`
- `forge/orchestrator/templates/{operator,research,sdr,custom}.py`
- `Procfile` (repo root) — Railway web entry
- `railway.json` (repo root) — Railway build config
- `.github/workflows/deploy-dashboard.yml` — auto-deploy on tagged release
- `examples/heartbeats/sync.md`
- `examples/heartbeats/daily_report.md`
- `examples/heartbeats/daily_intel.md`
- `examples/heartbeats/weekly_research.md`
- `tests/test_digest.py`
- `tests/test_delivery.py`
- `tests/test_intel_fetch.py`
- `tests/test_intel_inject.py`
- `tests/test_web_tools.py`
- `tests/test_auto_research.py`
- `tests/test_dashboard.py`
- `tests/test_dashboard_auth.py`
- `tests/test_dashboard_db.py`
- `tests/test_orchestrator.py`
- `tests/test_sync.py`

**Modify:**
- `forge/__init__.py` (re-exports + `__all__` — adds `Delivery`, `MarkdownFileDelivery`, `SlackMCPDelivery`, `make_delivery`, `DailyDigest`, `WeeklyDigest`, `build_digest`, `IntelItem`, `IntelDigest`, `pull_intel`, `build_intel_digest`, `run_auto_research`, `AutoResearchBudget`, `WebSearchTool`, `WebFetchTool` ≈ 18 symbols)
- `forge/observability/__init__.py` (re-exports digest + delivery)
- `forge/tools/__init__.py` (re-exports web tools)
- `forge/tools/builtin/__init__.py` (register web tools)
- `forge/cli.py` (`report`, `intel pull|research|show` subcommands; `--with-intel` flag on `recurse`; `dashboard --serve [...]` flag)
- `forge/recursion/llm_proposer.py` (optional `intel_context` kwarg — additive, defaults preserve byte-identical behavior)
- `forge/recursion/loop.py` (thread `intel_context` through)
- `CHANGELOG.md` (`[Unreleased]`)
- `ARCHITECTURE.md` (Reporting + Intel + Auto-Research subsection under recursion cross-cut)
- `README.md` (Daily Reports + Intel + Active Auto-Research section)
- `pyproject.toml` (no runtime deps added to base install; new optional extras: `[intel]` = `tavily-python`; `[dashboard]` = `fastapi`, `uvicorn[standard]`, `sqlmodel`, `alembic`, `jinja2`, `bcrypt`, `pydantic-settings`, `psycopg[binary]`, `httpx` (test client). All opt-in.)
- `ETHOS.md` (note the explicit reversal of two prior non-goals: "Not a UI" and "Not a hosted service." The Railway dashboard is now a first-class module — concession to the principle that invisible self-improvement isn't real.)

## Verification

End-to-end check after build, in this order — each must be green:

1. **Suite stays green**: `pytest -q` → 82 → ~92 (4 new test files). No
   pre-existing test changes.
2. **forge doctor still ok**: `forge doctor` → green, all profiles load.
3. **`__all__` resolves**: `python -c "import forge; assert all(hasattr(forge,s) for s in forge.__all__)"`.
4. **Markdown delivery (offline)**: `forge report --period day --to file` →
   writes `~/.forge/digests/day-<date>.md`; cat the file; verify no message
   content from traces appears.
5. **Intel pull (live but cheap)**: `forge intel pull --dry-run` → fetches
   from default sources, prints count + path that would be written. Then
   `forge intel pull` (no --dry-run) → writes today's intel JSON + vault notes
   + genome additions.
6. **Intel show**: `forge intel show` → markdown digest of today's items.
7. **Web tools online**: `python -c "from forge import WebSearchTool, WebFetchTool; ..."` smoke + a single live call against a known-public URL via `WebFetchTool` (no key required for the urllib fallback search).
8. **Auto-research daily (live, ~$0.10)**: `forge intel research --budget daily` → spawns the auto-research sub-agent on Haiku, ≤4 turns, ≤8 tool calls, ≤$0.15 budget; ledger row in `auto-research.tsv`; intel items added to today's JSON + vault. Inspect the agent's trace under `<home>/traces/<sid>/` and confirm web tool calls fire and the regularizer rationale appears in the final assistant message.
9. **Auto-research weekly (live, ~$0.50–1.00)**: `forge intel research --budget weekly --profile anthropic` → richer summary; manually verify quality of the SDK-by-SDK section (does it actually mention recent Claude / OpenAI / Composio / Meta-Harness movements?).
10. **Auto-recurse with intel (live, ~$0.10)**: `forge recurse --with-intel` →
    ledger row appended; system prompt of the proposer (visible in trace)
    contains the intel-context block + regularizer paragraph.
11. **Slack MCP delivery (live, requires user has the connector wired)**:
    `forge report --period day --to slack-mcp` → message lands in configured
    channel; if the MCP server is unreachable, falls back to file delivery
    with a CHANGELOG-style note in stderr.
12. **Heartbeat dry-run**: `forge heartbeat run --dir examples/heartbeats` →
    all three heartbeats (daily_intel, daily_report, weekly_research) discovered + executed; logs land under `<home>/heartbeat-logs/`.
13. **Live recursion smoke still works**: `python examples/recursion_demo/run.py`
    runs end-to-end exactly as before (regression guard for the proposer
    extension being backwards-compatible).
14. **Privacy invariant**: grep digest output files for `"role":` and
    `"content":` (the JSONL message field shapes) → must be 0 matches.
15. **Budget enforcement**: synthetic mock test where the auto-research mock provider's cost projection exceeds `max_cost_usd` mid-run; assert the loop terminates with a `SAFETY_BLOCKED` verdict in the trace and writes a partial ledger row marked `truncated=true`.
16. **Dashboard boots locally first**: `forge dashboard serve --db sqlite:///dev.db` → open `http://127.0.0.1:8000/` in a browser. Login with `DASHBOARD_PASSWORD`. Verify all 3 nav tabs (Workspace / Changelog / Genome) render in light mode (no dark backgrounds), HTMX agent-panel loads inline without full page reload, and `/healthz` returns 200.
17. **Railway deploy**: `railway up` (or git-push to a Railway-linked branch) provisions Postgres + deploys. Capture the public URL. Run Alembic migrations on the Railway shell (`railway run alembic upgrade head`). Set env vars: `DASHBOARD_PASSWORD`, `ANTHROPIC_API_KEY`, `SYNC_SHARED_SECRET`. Open the Railway URL in a browser → login → all 3 tabs render against the empty Postgres.
18. **Local sync push**: with the dashboard live, run `forge sync push --url <RAILWAY_URL> --token <SECRET>` from the laptop. Refresh the dashboard → existing agents appear in Workspace under their projects (default project: `forge`); existing recursion ledger rows appear in Changelog; existing genome memories appear in Genome.
19. **Orchestrator round-trip (live, ~$0.05)**: in the dashboard chat, type "spawn me an agent that summarizes my Notion daily." Verify the orchestrator emits a `propose_spawn` PendingAction; the dashboard renders an Approve card inline. Click Approve → `pending_actions.status` flips to `approved`. Within 5 min the local `forge sync pull-and-apply` heartbeat picks it up; `<home>/agents/notion_summarizer.yaml` appears locally; the next sync push surfaces the new AgentRow on the dashboard. (To accelerate verification, run `forge sync pull-and-apply` manually.)
20. **Orchestrator project scaffold (live, ~$0.10)**: ask the orchestrator to "start a new SDR vertical called `outbound_v2`." Approve. Verify `examples/outbound_v2/run.py` is scaffolded locally on the next sync, a heartbeat markdown is added if requested, and the scaffold runs (mock provider) without errors.
21. **Mutation gating + reject path**: in the chat, propose a spawn → reject it → confirm `pending_actions.status='rejected'` and the local sync does NOT apply it. Confirm `Verdict.SAFETY_BLOCKED` from `DenialTracker` fires if the orchestrator hits the same propose 3+ times.
22. **Direct edit (v1-allowed fields)**: in the agent panel, edit `instructions` → save → `ChangelogEntry(kind="agent_edit")` appears in the Changelog tab. Edit fields outside the v1 allow-list → form rejects with "ask the orchestrator instead."
23. **Genome tab**: search by tag in the Genome tab → results paginate. Click a memory → see full text + confidence + ts.
24. **Auth gate**: open the Railway URL in an incognito browser → must hit `/login`. Wrong password 3x → backoff (the `auth.py` rate limit). Right password → workspace loads.
25. **Idempotent sync**: re-run `forge sync push` 5 times in a row → no duplicate AgentRows, no duplicate ChangelogEntries (upsert by stable ID).

## Out of scope (explicit)

- No new model providers.
- No worktree-per-sub-agent (deferred from earlier).
- No PackManager / multi-pack composition (premature).
- No Telegram / email / Discord delivery (Slack MCP only as scoped).
- No automatic version bumps or PyPI re-publish — this is a `[Unreleased]`
  CHANGELOG entry; user decides when to cut 0.2.0.
- No multi-user / multi-tenant. v1 is single-operator (Justin) auth via
  one shared password.
- No SSO / OAuth — `DASHBOARD_PASSWORD` is the only gate in v1.
- v1 direct-edit fields limited to `instructions` and `tools_denied`.
  Everything else (profile swap, allowed_tools, project move, deletion)
  flows through the orchestrator + Approve flow. v2 can expand the
  allow-list once we have telemetry on what's actually used.
- No dark mode in v1 (user explicitly requested light mode).
- No streaming logs / live-tail of running agents in the dashboard v1
  (Changelog is post-hoc only). v2 can add a `/agents/{id}/live` page if
  needed.
- No remote shell / direct file editing from the dashboard. The
  orchestrator can only propose; the local sync applies. This preserves
  "no remote control plane" as a hard security boundary — a compromised
  Railway deploy can only enqueue actions for review, never execute
  arbitrary code on the laptop.

## Build order (suggested — independent enough to parallelize after step 2)

1. **Reporting primitives** (Section A): `digest.py` + `delivery.py` + `forge report` CLI + heartbeats. ~1 day.
2. **Recursion proposer extension** (small, gates everything else): add `intel_context` kwarg to `propose_with_llm` + `recurse_once`. Backward-compat regression test. ~2 hours.
3. **Intel passive pull** (Section B part 1): `forge/intel/sources|fetch|normalize|digest|store.py` + `forge intel pull|show` CLI. ~1 day.
4. **Web tools + auto-research** (Section B part 2): `WebSearchTool`, `WebFetchTool`, `auto_research.py`, `forge intel research` CLI, weekly heartbeat. ~1.5 days.
5. **Dashboard scaffold** (Section C part 1): FastAPI app + SQLModel + Alembic + auth + 3 nav tabs rendering against synthetic data. ~2 days.
6. **Orchestrator + Pending Actions** (Section C part 2): `OrchestratorAgent` + `propose_*` actions + Approve/Reject UI + chat history persistence. ~1.5 days.
7. **Local↔cloud sync** (Section C part 3): `forge sync push|pull-and-apply` + 5-min heartbeat + idempotent upsert. ~1 day.
8. **Railway deploy** (Section C part 4): `Procfile` + `railway.json` + Postgres provisioning + env vars + smoke against the live URL. ~half day.
9. **Live verification ladder** (25 steps above) + small fixes. ~half day.
10. **Commit + push** every section in its own atomic commit; CHANGELOG `[Unreleased]` updated as we go. Final commit cuts the section list into the README.

## Status
- [x] Phase 1 — Explore: forge primitives mapped, gaps confirmed
- [x] Phase 2 — Design: user-decision points locked via two AskUserQuestion rounds + two free-text scope expansions
- [x] Phase 3 — Review: this plan
- [x] Phase 4 — Implement (sections A, B-1/2/3, C-1/2/3/4 + scaffolder all shipped)
- [x] Phase 5 — Verify (173/173 tests, live Railway deploy + first sync push verified)
- [x] Phase 6 — Commit + push to `main`; Railway deployed at https://forge-web-production-da97.up.railway.app

---

## Addendum 2026-04-26 — Dashboard framework evaluation (deferred)

Considered swapping the custom FastAPI dashboard for **paperclipai/paperclip**
(Node + React + Postgres orchestration platform, "open-source orchestration
for zero-human companies").

**Verdict: keep custom FastAPI dashboard.** Reasoning:

- paperclip optimizes for *production orchestration at company scale across
  many teams* (governance, cost ceilings, multi-tenant audit). forge v1 is
  *single-operator with chat-driven design + approval queue*.
- Migration cost: 2–3 months (full React rewrite, lose HTMX simplicity).
- Overlap with what's already built: the chat + approval queue only. Genome,
  Changelog, and the local↔cloud sync bridge are forge-specific and would
  re-implement on top of paperclip.
- User motivation when asked: "just exploring, no specific dissatisfaction."

**Revisit trigger:** if forge graduates from single-operator to
multi-team / multi-swarm-per-team, OR if specific governance/cost-control
features become load-bearing. Until then, the ~600-line FastAPI dashboard
is the right size for the workload.

**Cheap-wins shortlist** (if and when interest returns to dashboard polish,
in priority order — none require migration):

1. Token-budget UI per agent (lift the pattern from paperclip's cost panel).
2. Step-through view for multi-agent runs (paperclip's "task timeline").
3. Per-agent audit log inline on the agent-detail panel.

These are 1–2 day inserts into the existing dashboard, not a rewrite.
