# CLAUDE.md — forge contributor guide

Project-level instructions for Claude Code sessions working on forge.

## What this repo is

`forge` is a Python SDK for an 8-layer model-agnostic agent harness.
Read `ETHOS.md` and `ARCHITECTURE.md` before making non-trivial changes.
Read `CONTRIBUTING.md` for dev setup and PR process.

## Session checklist

Run these at the start of every session:

```bash
source .venv/bin/activate
forge doctor          # environment audit — must be green
pytest -q             # 70+ tests, no API keys needed
```

If `forge doctor` reports `.pth` markers missing on macOS, the bash
wrapper at `.venv/bin/forge` (exporting `PYTHONPATH`) is the workaround;
`python -m forge.cli` works directly.

## Hard constraints (NEVER)

- **NEVER** import a vendor SDK at module top-level. Lazy-import inside
  the constructor of the class that needs it.
- **NEVER** add an L0 import from a higher layer (`forge.kernel` may not
  import `forge.swarm`, `forge.skills`, etc.).
- **NEVER** modify lines below `# === FIXED ADAPTER BOUNDARY ===` in any
  file that contains it. That sentinel is the recursion proposer's contract.
- **NEVER** compact or summarize trace files (`traces/<run_id>/*.jsonl`)
  before the recursion proposer reads them. Trace fidelity is sacred.
- **NEVER** ship credentials or `.env` in commits. `~/.forge/.env` is
  gitignored on purpose.
- **NEVER** bypass the eval gate (`MIN_SAMPLES=50`, `CONFIDENCE_MARGIN=0.05`)
  for skill or harness mod promotion.
- **NEVER** remove a symbol from `forge/__init__.py.__all__` without a
  CHANGELOG breaking-change entry.

## Hard requirements (ALWAYS)

- **ALWAYS** use `from __future__ import annotations` at the top of every
  module.
- **ALWAYS** add type hints to public functions.
- **ALWAYS** add a test under `tests/test_<layer>.py` when adding a new
  primitive.
- **ALWAYS** update `CHANGELOG.md` under "Unreleased" for user-facing changes.
- **ALWAYS** mirror new public symbols in both the layer's `__init__.py`
  and `forge/__init__.py.__all__`.

## Workflow

1. **State the plan** before writing code (file list + risk + edge cases).
2. **Make the change** in the smallest reviewable diff.
3. **Run** `pytest -q` and `forge doctor`.
4. **Update** `CHANGELOG.md` if user-facing.
5. **Commit** with a message that describes the *why*, not the *what*.

## Common tasks

| Task | Where |
|---|---|
| Add a model provider | `forge/providers/profiles/<name>.yaml` (+ optional adapter shim) |
| Add an L2 tool | `forge/tools/builtin/<name>.py` + register in `tools/__init__.py` |
| Add a consensus algo | `forge/swarm/consensus.py` (extend enum + scorer) |
| Add a hook | Subscribe to `HookBus` from your module — do not modify `kernel/hooks.py` |
| Add an MCP tool exposure | `forge/mcp_server.py` (current count: 12) |
| Tune circuit thresholds | `forge/healing/circuit_breaker.py` constants — bump CHANGELOG |

## Tool permissions (Claude Code defaults)

Default: full access. forge's own L3 healing layer enforces dry-run and
cost gates at runtime, so the tool layer doesn't need to be locked down
at the IDE level.

If you're working on the recursion proposer specifically (`forge/recursion/
llm_proposer.py`), be extra careful — it uses real Sonnet calls and writes
real diffs. Test against `tests/test_recursion_loop.py` first.

## Model selection

For Claude Code's own work in this repo:

- **Haiku**: file reading, grep, `git status`, running `pytest`, simple Q&A.
- **Sonnet**: code generation, debugging, refactors, PR reviews.
- **Opus**: architecture decisions, multi-file analysis, decisions that
  touch >3 layers, anything involving the recursion proposer.

When spawning subagents, specify the model explicitly. Default subagent
model is Haiku.

## Repo map (quick reference)

```
forge/                    # the SDK
  kernel/                 # L0
  memory/                 # L1
  tools/                  # L2
  healing/                # L3
  swarm/                  # L4
  skills/                 # L5
  observability/          # L7
  recursion/              # cross-cutting self-mod
  providers/              # provider profiles + adapters
  mcp_server.py           # forge-as-MCP
  cli.py                  # `forge` console script
examples/                 # L6 reference verticals
tests/                    # mirrors forge/ structure
docs/                     # additional design notes
```

## When in doubt

- Read `ARCHITECTURE.md` for the layer ordering rule.
- Read `ETHOS.md` for what gets a PR rejected vs. landed fast.
- Read `CONTRIBUTING.md` for dev setup and release process.
- Open a draft PR early; small reviewable diffs win.
