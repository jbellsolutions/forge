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

## § 2026-04-27 — Hermes 0.11 reaction; B.4 spawn-depth landed

### What landed this session

- **`Spawner.max_spawn_depth`** committed as `1085ff6`. Plumbing on
  `forge/swarm/spawner.py`: Spawners can `make_child()` with depth budget,
  raising `SpawnDepthExceeded` on overflow. Per-level `max_turns` decays via
  `DEPTH_BUDGET_DECAY = 0.5`. Default `max_spawn_depth=0` preserves existing
  behaviour. New public exports: `DEPTH_BUDGET_DECAY`, `SpawnDepthExceeded`.
  6 new tests in `tests/test_swarm_spawn_depth.py` (all green; targeted +
  adjacent swarm tests verified post-commit).
- Plan saved at `~/.claude/plans/alright-so-there-was-golden-pike.md` —
  updated with verification table + Track A no-go decision.

### Verification pass — upstream IDs from the Hermes 0.11 video

| Item | Status | Verified ID |
|---|---|---|
| Hermes repo | ✅ | `NousResearch/hermes-agent` v0.11.0 (2026-04-23) |
| GPT-5.5 | ✅ | OpenAI 2026-04-23. API: `gpt-5.5` ($5/$30 per M); `gpt-5.5-pro` ($30/$180) |
| DeepSeek v4 | ✅ | 2026-04-24 preview. `deepseek-v4-pro` (1.6T/49B), `deepseek-v4-flash` (284B/13B), 1M ctx, on OpenRouter |
| Qwen 2.6 | ❌ wrong number | Actually **Qwen 3.6** family — `Qwen3.6-27B`, `Qwen3.6-Max-Preview` (Apr 2026) |
| Xiaomi V2 Pro | ⚠️ wrong name | Actually **`MiMo-V2-Pro`** (1T/42B, $1/M input, 2026-03-18) and **`MiMo-V2.5-Pro`** (public beta 2026-04-22) |
| Claude Opus 4.7 | ✅ | This session is running on it |

### Track A — DEFERRED (locked, not "pending direction")

`paperclipai/paperclip/doc/plugins/PLUGIN_SPEC.md` opens with: "This is not
part of the V1 implementation contract... It is the full target architecture
for the plugin system that should follow V1." **Translation: there is no
Paperclip plugin SDK shipped today — it's a design document.** The
`paperclip-create-plugin` skill's "alpha SDK" self-description was optimistic.

Decision: keep `forge/dashboard/` as the user-facing UI. Re-evaluate Track A
only when Paperclip ships plugin SDK V1+ with a stability commitment.
**Why:** standing forge's only dashboard on a non-existent plugin runtime is
strictly worse than the original "alpha SDK" risk. Original 2026-04-26
DEFERRED rationale (single-operator vs multi-team) still applies.
**How to apply:** if user revisits the Paperclip pivot, first check
`paperclipai/paperclip` for a shipped, versioned plugin SDK; if still spec-only,
push back and propose deep-link integration instead of plugin coupling.

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
