# forge — Agents

Agent personas and verticals shipped under `examples/`. forge ships a chassis;
these are the reference builds that exercise it.

## How an agent is defined in forge

Three pieces:

1. **`AgentDef`** (`forge.kernel.AgentDef`) — name, system prompt, allowed
   tools, provider profile reference.
2. **Provider profile** — YAML at `forge/providers/profiles/*.yaml` declaring
   the model + protocol.
3. **Optional persona YAML** — use-case identity (tone, constraints, KPIs).

Sub-agents are spawned via `Spawner` with a `SwarmSpec`: topology +
consensus + members. Each member gets its own `AgentDef` and runs in
isolation; the parent tracks via `parent_tool_use_id`.

## Reference verticals

### `examples/operator/` — mock vertical

Minimal end-to-end. Mock provider, mock tools, in-process MCP adapter for
tests. Use this as the "hello world" template when adding a new vertical.

- Topology: `SOLO`
- Provider: `mock`
- Tools: `EchoTool`, `FSReadTool`
- Verifies: kernel + hook bus + provider abstraction

### `examples/operator_real/` — live vertical

Real Anthropic + real MCP filesystem server + a 3-member council.

- Topology: `PARALLEL_COUNCIL` (3 members)
- Members:
  - `anthropic` (Sonnet, balanced) — pragmatist
  - `anthropic-haiku` — skeptic (cheap, fast counter-arguments)
  - `anthropic-contrarian` (Sonnet @ temp 1.0) — optimist
- Consensus: `MAJORITY`
- Tools: official `@modelcontextprotocol/server-filesystem` rooted at
  `~/.forge/vault` + native forge tools (`ObsidianVault`, `ShellTool`)
- Verifies: live MCP transport, role injection, telemetry, healing
- Cost: ~$0.10/run on a typical heartbeat task

### `examples/recursion_demo/` — self-mod cycle

The Meta-Harness proof-of-work. Populates `traces/` with synthetic failing
traces, calls `propose_with_llm()` against live Sonnet, parses real diffs
(retune_circuit / deny_tool / patch_yaml), forks the working copy, applies,
scores, decides keep-or-rollback, appends a row to `ResultsLedger`.

- Verifies: AutoAgent regularizer in proposer system prompt, FIXED ADAPTER
  BOUNDARY enforcement, ledger writes, rollback semantics

## Role injection (`RoleCouncilSpawner`)

When you spin up a council on a contested decision, inject distinct roles
or members will collapse to the same answer. Built-in roles:

| Role | Bias | Use when |
|---|---|---|
| `optimist` | Argues *for* the proposal, surfaces upside | Risk-averse defaults are killing high-EV moves |
| `skeptic` | Argues *against*, surfaces failure modes | About to ship something irreversible |
| `pragmatist` | Time/cost-bounded, picks the boring win | Decision is being over-engineered |

Pass via `RoleAssignment(member_idx=0, role="optimist")` in the `SwarmSpec`.

## Adding a vertical

1. New dir under `examples/<name>/`.
2. `run.py` with `if __name__ == "__main__":` entry point.
3. Optional `mcp.json` for MCP server config (see `operator_real/mcp.json`).
4. Optional `heartbeats/*.md` if it runs on a schedule (see
   `forge/scheduler/`).
5. README section in the vertical's dir describing what it exercises and
   what verification looks like.

The verification bar for any new vertical: it must exercise at least one
non-trivial L2 tool and persist at least one trace under `traces/<run_id>/`.

## Sub-agent isolation

forge follows the Claude SDK `AgentDefinition` pattern. Each sub-agent:

- Has its own scoped `ToolRegistry` (deny-list per persona).
- Has its own scoped system prompt (no parent prompt leakage).
- Gets a fresh hook bus subscription (its `PreToolUse`/`PostToolUse` fire
  but parent hooks see the child via `parent_tool_use_id`).
- Persists its own trace under `traces/<parent_run_id>/<child_run_id>/`.

This is what lets a council of 3 disagree productively — they're not just
3 prompts to one model; they're 3 isolated agents with isolated memory
and isolated tool surfaces.

## Heartbeats (markdown-as-cron)

`forge/scheduler/` ships templates for crontab, launchd, and GitHub Actions.
Heartbeat bodies are markdown files under `<example>/heartbeats/*.md`. The
scheduler reads frontmatter for cadence, the body is the prompt.

Example: `examples/operator_real/heartbeats/morning_council.md` — runs
daily at 9am, kicks a 3-member council on the day's priorities, writes
results to the Obsidian vault.

## Skill obsession (for agents built on forge)

When you build an agent on forge — or when forge's own contributors add a
new vertical — the first instinct should be: **does a skill already do this?**
The L5 system (`SkillStore` + `SkillSearchIndex` + `autosynth` + `EvalGate`)
exists so agents and humans don't re-author the same capability twice.

For an agent at runtime, expose skill discovery as a tool the agent can call:

```python
from forge import SkillSearchIndex, SkillStore

store = SkillStore(root=session_home / "skills")
index = SkillSearchIndex(store)

# Inside your agent's tool surface:
def find_skill_for(task: str) -> list[str]:
    return [s.name for s in index.search(task, k=3)]
```

Wire `find_skill_for` into your `ToolRegistry` and the agent will check
before reaching for raw shell or LLM-only reasoning. Promotion of a new
skill version goes through the same `EvalGate` that protects the harness
itself — `MIN_SAMPLES=50`, `CONFIDENCE_MARGIN=0.05`. No vibes promotions.

This obsession lives in *one* place — forge's own L5. If you find yourself
adding a parallel skill registry on top of forge, stop: that's the failure
mode this section exists to prevent.
