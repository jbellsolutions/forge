---
name: forge — model-agnostic agent harness
description: Self-learning, self-healing harness + Python SDK to build agent swarms. Lives at github.com/jbellsolutions/forge, published as `forge-harness` on PyPI.
type: project
last_updated: 2026-04-27
---

# forge — Project Memory

The single source of truth for "what has actually been built and decided" on this
repo. Append, don't rewrite. Use § dividers between sessions.

---

## § 2026-04-26 — Initial build through to live Railway deploy

### What forge is now

Eight-layer model-agnostic agent harness in Python. Top-level surface:

- **SDK** (`from forge import …`) — primitives for building agent swarms (HookBus,
  ToolRegistry, RoleCouncilSpawner, AgentDef, AgentLoop, recurse_once, etc.).
- **CLI** (`forge`) — `doctor`, `run`, `recurse`, `intel pull|research|show`,
  `report`, `dashboard`, `sync push|pull-and-apply|daemon`, `new`, `heartbeat`,
  `mcp` (stdio MCP server).
- **Dashboard** — Railway-hosted FastAPI app (Workspace · Changelog · Genome).
- **`forge new "<description>"`** — LLM-driven swarm scaffolder, writes to
  terminal / .claude/agents/ / dashboard PendingAction.

### Deploy state

- **Live URL:** https://forge-web-production-da97.up.railway.app
- **Railway project:** `forge-dashboard` (id `d8c3eab5-f6dd-4433-a4f7-f46e0c01d720`)
- **Web service:** `forge-web` (id `6d162c95-2172-4493-a42b-9ea025478dd3`)
- **Postgres service:** `Postgres` (provisioned via Railway addon)
- **Secrets file:** `/Users/home/.forge/railway-secrets.env` (chmod 600) — holds
  `DASHBOARD_PASSWORD`, `SESSION_SECRET`, `SYNC_SHARED_SECRET`. Anthropic key
  read from `~/.forge/.env`.
- **First sync push verified:** 1 project + 4 genome memories landed in cloud.

### Sections shipped (10 atomic commits, `4ec6c7e` → `25309ab`)

| Section | What | Status |
|---|---|---|
| A | Reporting (`forge.observability.{digest,delivery}`, `forge report`) | ✅ |
| B-1 | Intel pipeline (`forge.intel.{sources,fetch,normalize,digest,store}`, `forge intel pull|show`) | ✅ |
| B-2 | Recursion proposer extension (`intel_context` kwarg, byte-identical when None) | ✅ |
| B-3 | Web tools + auto-research (`WebSearchTool`, `WebFetchTool`, `run_auto_research`) | ✅ |
| C-1 | Dashboard scaffold (FastAPI + SQLModel + Alembic + auth + 3 tabs) | ✅ |
| C-2 | Orchestrator (Papa Bear) + PendingActions (chat + Approve/Reject) | ✅ |
| C-3 | Local↔cloud sync (`forge.sync.{state,push,pull}`) | ✅ |
| C-4 | Railway deploy (Dockerfile + Procfile + railway.json) | ✅ |
| Scaffolder | `forge new` LLM swarm-design + 3 output backends | ✅ |

### Tests
- 173/173 green (`pytest -q`)
- Up from 70 at session start

### Live verification done
- `forge intel pull` — 156 items live, 66 high-relevance
- `forge intel research --budget daily` — 4 turns / 8 tool calls, summary written
- `forge new` × 2 round-trips through dashboard endpoint
- All 4 dashboard routes return correct codes (healthz=200; auth-gated routes 401→200 with cookie)

### Decisions on record

**Paperclip dashboard migration: DEFERRED** (2026-04-26)
- Considered swapping FastAPI dashboard for paperclipai/paperclip
- Verdict: keep custom dashboard. Paperclip optimizes for multi-team production
  orchestration; forge v1 is single-operator. ~600 lines of FastAPI is right-sized.
- Revisit trigger: graduating to multi-team / multi-swarm-per-team, OR specific
  governance/cost-control features become load-bearing.
- Cheap-wins shortlist (no migration needed):
  1. Token-budget UI per agent (lift paperclip's cost-panel pattern)
  2. Step-through view for multi-agent runs (paperclip's task timeline)
  3. Per-agent audit log inline on agent-detail panel

**Dashboard direct-edit allowlist (v1):** only `instructions` and `tools_denied`.
Everything else flows through orchestrator → PendingAction → Approve.

**Intel autonomy:** auto-recurse daily, eval-gated. EvalGate guards every mod;
nothing ships unless it beats baseline. ~$0.10/day.

### Open follow-ups

1. **Intel dry-run side-effect bug** — `forge intel pull --dry-run` writes to
   `<home>/intel/seen.json` so the next non-dry-run finds 0 new items. Filed as
   spawn-task chip earlier this session. Fix: thread `persist_seen=not args.dry_run`
   kwarg through `pull_intel`.
2. **Daily intel + auto-research heartbeat not yet running** — heartbeats exist
   under `examples/heartbeats/` but cron isn't installed. User-driven.
3. **AutoAgent repo review** (`https://github.com/kevinrgu/autoagent`) — one-time
   30-min scan for patterns forge hasn't absorbed (tool-during-proposal, multi-step
   verification, counterfactual scoring, regularizer self-tuning).

### Hard architectural rules (also in CLAUDE.md and ETHOS.md)

- **NEVER** import a vendor SDK at module top-level — lazy-import inside the
  class that needs it. Keeps base install ≈ stdlib-only.
- **NEVER** import upward across layers. `forge.kernel` (L0) may not import
  `forge.swarm`, `forge.skills`, etc.
- **Privacy invariant on digests**: digest output never contains raw message
  content from `messages.jsonl`. Counts, names, scores only. Tested by grep.
- **Sync token check**: every `/sync/*` endpoint verifies `X-Forge-Sync-Token`.
  Open mode (no DASHBOARD_PASSWORD) logs a loud warning and refuses to silently
  expose a public deploy.
