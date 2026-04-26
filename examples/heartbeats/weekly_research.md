---
schedule: "0 6 * * 1"
command: "forge intel research --budget weekly --profile anthropic && forge recurse --with-intel"
priority: A
---

# Weekly heavy auto-research

Mondays at 6am, before the daily intel pull at 7am and the report at 8am.

Heavier AutoAgent cycle on Sonnet:
- ≤20 turns, ≤40 tool calls, ≤$1.00 budget
- Investigates each tracked SDK (Claude / OpenAI / Composio / MCP /
  Meta-Harness / AutoAgent) for changes since the last weekly run
- Regularizer-gated to filter hype from durable shifts
- Outputs a richer summary at `<home>/intel/research/<ts>-weekly.md`
- Feeds that summary into `recurse --with-intel`; the recursion proposer
  may emit harness mods grounded in field-wide deltas (still gated by
  EvalGate)

The Monday daily report at 08:00 includes both this weekly summary and
any kept candidate from the recurse step.

## Success criteria
- Weekly summary written to `<home>/intel/research/`
- New row in `<home>/intel/auto-research.tsv` with `label=weekly`
- `<home>/results.tsv` gains a row from the subsequent recurse
