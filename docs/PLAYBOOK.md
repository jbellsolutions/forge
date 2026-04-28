# PLAYBOOK — How to actually run forge

Operator-facing guide. Last updated 2026-04-27. Companion to `README.md`
(what forge is) and `ARCHITECTURE.md` (how it's built). This file is
**how you, the operator, get value out of it day to day.**

---

## TL;DR — the five commands you use

```bash
forge doctor                           # green-light the env; run before anything
forge new "<English description>"      # propose a swarm; one-click materialise
forge intel pull && forge intel research --budget daily   # absorb upstream
forge recurse --with-intel             # propose self-mods, gated by EvalGate
forge dashboard                        # see what it did
```

Everything else is variations on those five.

---

## Right now — post-push smoke check (5 minutes)

Run this once after the push lands:

```bash
git pull --rebase                       # pick up 1085ff6 + d297933
source .venv/bin/activate
forge doctor                            # MUST be green
pytest -q tests/test_swarm.py tests/test_swarm_spawn_depth.py
forge skill list                        # any skills installed?
forge intel show                        # any intel digested today?
forge dashboard                         # spin up the local UI on :8000
```

If `forge doctor` flags `.pth` markers missing on macOS, the bash wrapper
at `.venv/bin/forge` is the workaround. `python -m forge.cli` works directly.

If the dashboard fails to start with an Anthropic SDK error, you're on a
release before `5789fa0` — `pip install 'forge-harness[dashboard]'` has
the SDK in the extra now.

---

## The Daily Rhythm

forge is designed for one habit: **morning intel, evening review.**

### 07:00 — Daily intel + recurse (target: cron-installed; today: manual)

```bash
forge heartbeat run --dir examples/heartbeats   # runs daily_intel.md
# Equivalent to:
forge intel pull && forge intel research --budget daily && forge recurse --with-intel
```

What this does, in order:

1. **`forge intel pull`** — RSS/Atom/GitHub-releases sweep over the
   allowlist (Anthropic, OpenAI, Composio, MCP, AutoAgent, etc.).
   Dedupes against `<home>/intel/seen.json`. Writes per-source vault
   notes to your Obsidian vault. Top-3 high-relevance items distilled
   into the cross-project genome.
2. **`forge intel research --budget daily`** — Haiku sub-agent, ≤4
   turns / ≤8 tool calls / ≤$0.15. Regularizer-gated ("would this still
   matter if THIS specific release vanished?"). Output:
   `<home>/intel/research/<ts>-daily.md`.
3. **`forge recurse --with-intel`** — LLM proposer reads the day's
   intel digest, proposes a harness mod or skill version. **EvalGate
   (`MIN_SAMPLES=50`, `CONFIDENCE_MARGIN=0.05`) gates promotion.**
   Failed candidates roll back; successful ones land in `results.tsv`.

Total expected cost: **~$0.10/day.** That's the budget; cap it at the
provider profile.

### 18:00 — Glance at the dashboard

```bash
forge dashboard           # http://localhost:8000
```

Three tabs:
- **Workspace** — agents grouped by project, last-run status.
- **Changelog** — promoted skills + harness mods from `results.tsv`.
- **Genome** — cross-project facts in `<home>/genome/*.json`.

You're looking for: did anything get promoted today? If yes, glance at
the diff. If no, check `<home>/intel/research/<ts>-daily.md` to see
what the proposer considered and rejected.

### Anytime — sync to/from Railway

```bash
forge sync push     # local deltas → Railway dashboard
forge sync pull     # approved PendingActions → local
```

The dashboard is a **control plane**, not a UI surface. Approve actions
on the hosted dashboard; `forge sync pull` materialises them locally.

---

## The Weekly Rhythm

### Sunday afternoon — review accumulation

```bash
forge intel research --budget weekly      # Sonnet, ≤8 turns, deeper synthesis
forge skill list                          # what's installed
forge skill search "<keyword>"            # vector search over skills
forge report                              # build + deliver self-improvement digest
```

Look at the weekly research summary. It's the right input for **deciding
what to point forge at next week.** If a new harness like Hermes or
Codex is moving fast, that's a hint to add a provider profile or a
skill that uses it.

### Promotion sweep — autosynth + EvalGate

```bash
# For each skill in <home>/skills/<name>/:
forge skill autosynth <name>     # propose v_next from runs.jsonl
forge skill promote <name> v_next  # gated by EvalGate
```

`autosynth` reads `<home>/skills/<name>/<version>/runs.jsonl` (every
invocation logs a `SkillRun`) and proposes a refined `SKILL.md`.
**Promotion is eval-gated, never vibes-gated.** That's an ETHOS rule.

If a skill has fewer than `MIN_SAMPLES=50` runs, the gate refuses to
promote — go run the skill more, or kill it.

---

## Killer Apps — what to actually build

### 1. The "describe in English" swarm

```bash
forge new "DM me a Notion summary every morning at 8"
forge new "watch our Stripe failures and Slack me anything weird"
forge new "pull Apollo leads, qualify with Claude, DM hot ones"
```

`forge new` proposes the architecture (agents, roles, tools, schedule),
asks you where to run it, and scaffolds:
- **Local terminal**: `examples/<name>/run.py` — version-controlled, cron-able
- **Railway dashboard**: a `PendingAction`; one click and it materialises locally on next sync
- **Claude Code subagents**: `.claude/agents/<name>.md` — invoke via `/agents`

Pick one or all three. Same swarm, different runtimes.

### 2. forge as your MCP tool source

```bash
forge mcp        # stdio MCP server, exposes 12 forge tools
```

Wire this into Claude Code via `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "forge": {
      "command": "forge",
      "args": ["mcp"]
    }
  }
}
```

Now Claude Code can `forge.recurse`, `forge.intel.pull`, `forge.skill.search`,
`forge.swarm.run`, etc. directly. **This is the highest-leverage integration**:
it makes every Claude Code session forge-aware, including across projects.

### 3. Agents-spawning-agents (B.4, just landed)

```python
from forge import Spawner, ToolRegistry

# Top-level Spawner with a depth budget
parent = Spawner(
    tools=ToolRegistry(),
    max_turns=12,
    max_spawn_depth=2,  # NEW — allow 2 levels of nested Spawners
)

# Inside an agent's tool implementation, when it needs a sub-spawn:
child = parent.make_child(base_instructions="You're a deep-research sub-agent.")
# child.max_turns = int(12 * 0.5) = 6
# child.max_spawn_depth = 1
# grandchild can be made; great-grandchild raises SpawnDepthExceeded.
```

**When to use:**
- Deep research tasks where the top agent fans out specialised sub-agents
  per source / hypothesis / claim
- Hierarchical decomposition where each level halves the per-call budget
  (`DEPTH_BUDGET_DECAY=0.5`) — prevents fork-bomb economics
- Parallel verification pipelines

**When NOT to use:**
- Topology fan-out (HIERARCHY queen→workers, PARALLEL_COUNCIL) — those
  agents are already members of the *current* Spawner, not children.
  `max_spawn_depth` only governs Spawner *nesting*, not breadth.
- Default tasks. Default `max_spawn_depth=0` is the right starting
  point. Only raise it when you have a specific recursive pattern.

### 4. The recursion loop — make forge improve itself overnight

```bash
forge recurse-loop -n 5         # 5 self-mod cycles, EvalGate-gated
```

Drop this in launchd / cron at 02:30 nightly:

```bash
cp forge/scheduler/launchd.plist.template ~/Library/LaunchAgents/com.forge.recurse.plist
# Edit FORGE_BIN and FORGE_HOME paths
launchctl load ~/Library/LaunchAgents/com.forge.recurse.plist
```

Or use `forge/scheduler/cron.crontab.template` on Linux.

Each cycle: proposer reads recent traces → proposes a harness mod or
skill bump → eval against the held-out skill runs → keep or roll. The
trace fidelity rule (**never compact `traces/<run_id>/*.jsonl` before
the proposer reads them**) is non-negotiable; the proposer is reading
the actual tape.

### 5. Skill obsession

Before writing custom code for any capability that feels like it should
already exist:

```bash
forge skill search "deploy to fly.io"
forge skill search "qualify lead"
forge skill search "summarise PR"
```

If a skill exists, use it. **Don't reinvent — that's the fastest way
to a rejected PR.** If nothing fits, scaffold:

```python
from forge import SkillStore

store = SkillStore(root=session_home / "skills")
store.write_skill("name", body=skill_md, version="v1")
store.set_current("name", "v1")
# Now every invocation logs a SkillRun → autosynth + EvalGate machinery
# starts accumulating evidence for v2.
```

---

## Best Practices

### Do

- **Run `forge doctor` at session start.** It catches `.pth` markers,
  missing creds, broken provider profiles before they cost you a turn.
- **Let EvalGate run.** `MIN_SAMPLES=50`, `CONFIDENCE_MARGIN=0.05` are
  hard rules. Bypassing them strips the whole self-mod premise.
- **Mirror new public symbols** in both the layer's `__init__.py` AND
  `forge/__init__.py.__all__`. CHANGELOG.md gets the breaking-change
  entry. (See B.4 commit `1085ff6` for the canonical pattern.)
- **Use `from __future__ import annotations` at the top of every
  module.** Type hints on public functions, always.
- **Add a test under `tests/test_<layer>.py` when adding a primitive.**
  See `tests/test_swarm_spawn_depth.py` for the pattern.
- **Lazy-import vendor SDKs.** Inside the constructor of the class
  that needs them, never at module top-level. (See `forge/swarm/spawner.py`
  for the pattern.)
- **Trace fidelity is sacred.** Never compact `traces/<run_id>/*.jsonl`
  before the recursion proposer reads them.

### Don't

- **Don't add an L0 import from a higher layer.** `forge.kernel` cannot
  import from `forge.swarm`, `forge.skills`, etc. The layer ordering
  is enforced.
- **Don't modify lines below `# === FIXED ADAPTER BOUNDARY ===`.** That
  sentinel is the recursion proposer's contract.
- **Don't add a parallel skill registry.** forge has *one* skill source
  of truth: `<home>/skills/<name>/{SKILL.md,runs.jsonl}`. No
  `.claude/skill-mastery/` or other mirrors.
- **Don't ship credentials.** `~/.forge/.env` is gitignored on purpose.
- **Don't bypass the eval gate.** Ever. (Yes, even when you're sure.)

### Cost ceilings (from intel design)

| Loop | Provider | Cost ceiling |
|---|---|---|
| Daily intel research | Haiku | ≤$0.15/day |
| Weekly intel research | Sonnet | ≤$0.50/week |
| Recursion proposer | Sonnet | ≤$0.30/cycle |
| Total daily budget | mixed | ~$0.10–0.20/day |

If a profile drifts above these, the cost guard in `forge/healing/circuit_breaker.py`
trips and refuses further calls until reset. Bump CHANGELOG when you
tune those constants.

---

## Failure Modes — what breaks and how to spot it

| Symptom | Likely cause | Fix |
|---|---|---|
| `forge intel pull` returns 0 new items after a normal day | Last run was a `--dry-run` that wrote to `seen.json` | Open follow-up #1 in `.claude/memory/project.md` — patch `pull_intel` to gate `persist_seen` on dry-run |
| Tests hang silently in full-suite run | macOS launchd worker issue, pre-existing | Run targeted slice: `pytest tests/test_swarm.py -q`. Not from any specific commit. |
| `forge dashboard` 500s on first request | Anthropic SDK not in `[dashboard]` extra | `pip install 'forge-harness[dashboard]'` (fixed in `5789fa0`) |
| Provider call rejects with "metadata key" error | Anthropic vs OpenAI key naming drift | Check orchestrator uses provider's metadata keys for tool_use turns (fixed in `9bceffa`) |
| `forge recurse` keeps proposing the same diff | Trace files were compacted; proposer has no signal | Restore `traces/<run_id>/` from backup; never compact pre-proposer |
| `SpawnDepthExceeded` at unexpected level | Forgot to bump `max_spawn_depth` for the recursive pattern | Default is 0; raise to N where N is the deepest legitimate nest |

---

## Where forge lives on your disk

```
~/.forge/
├── .env                       # creds — NEVER commit
├── intel/
│   ├── seen.json              # dedup state
│   ├── <date>.json            # daily intel pull
│   └── research/<ts>-daily.md # research summaries
├── skills/
│   └── <name>/<version>/
│       ├── SKILL.md
│       └── runs.jsonl         # every invocation; feeds autosynth + EvalGate
├── genome/
│   └── *.json                 # cross-project facts
├── results.tsv                # promotion log
├── traces/<run_id>/*.jsonl    # SACRED — proposer reads these
└── vault/                     # Obsidian vault (intel notes)
```

Back up `~/.forge/skills/` and `~/.forge/traces/` weekly. The rest is
regenerable.

---

## Track Status — what's next on the roadmap

After today's push (commits `1085ff6` + `d297933`):

| Track | Status | Next move |
|---|---|---|
| **B.4 spawn-depth** | ✅ Shipped 2026-04-27 | Use it. Build a recursive-research example under `examples/`. |
| **B.1 cron installer** | 🟡 Templates exist, no `forge heartbeat install` subcommand yet | ~40 LOC in `forge/scheduler/install.py`. Local, dogfoods forge. **Highest leverage next change.** |
| **B.2 intel sources** | 🟡 Verified IDs ready (Hermes/Codex/Aider/etc.) | Add to `forge/intel/sources.default.yaml`; extend `DOMAIN_ALLOWLIST` |
| **B.3 provider profiles** | 🟡 Verified IDs: GPT-5.5, DeepSeek v4, Qwen 3.6, MiMo V2.5 Pro, Opus 4.7 | One YAML per provider in `forge/providers/profiles/` |
| **B.5 wire intel→recurse→genome on cron** | 🔵 Blocked on B.1 | Fires once heartbeat is installed |
| **B.6 plugin-style hooks** | 🔵 Stretch | Thin shim over existing `HookBus` |
| **Track A — Paperclip plugin** | ❌ Deferred | Paperclip plugin SDK is a design spec, not a shipped product. Re-evaluate when V1+ ships. |

---

## Maximizing — the high-leverage moves

**This week:**
1. Install the launchd plist. Make the daily heartbeat real.
2. Wire forge as an MCP server in Claude Code. Every Claude session is
   now forge-aware.
3. Run `forge new` once a day for a week. Build the muscle of describing
   swarms in English and approving them. The friction drops fast.

**This month:**
1. Ship B.1 (cron installer) — `forge heartbeat install` as a real
   subcommand. Removes the manual launchd step.
2. Ship B.2 + B.3 with verified IDs only. Drop "Qwen 2.6" / "Xiaomi V2 Pro"
   misnomers in favour of `Qwen3.6-27B` / `MiMo-V2.5-Pro`.
3. Build one nontrivial swarm vertical under `examples/` that uses the
   new spawn-depth — the recursive-research pattern is the obvious one.

**This quarter:**
1. Let recurse-loop run nightly for a month. Look at `results.tsv`.
   The harness should be measurably better than today, by your own
   eval-gated metrics.
2. Re-evaluate Track A only after Paperclip ships plugin SDK V1+ with
   a stability commitment. Until then, the standalone dashboard wins.

---

## When in doubt

1. `forge doctor` — does it pass?
2. `pytest -q` — does the slice you touched stay green?
3. `.claude/MEMORY.md` → `.claude/memory/project.md` — what was decided
   in prior sessions?
4. `~/.claude/plans/alright-so-there-was-golden-pike.md` — current plan
   with verification table and decisions.
5. `ETHOS.md` — what gets a PR rejected vs landed fast.

If forge stops being fun to operate, you've drifted from the ETHOS.
Strip back to the five commands at the top of this file and rebuild.
