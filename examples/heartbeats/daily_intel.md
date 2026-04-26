---
schedule: "0 7 * * *"
command: "forge intel pull && forge intel research --budget daily && forge recurse --with-intel"
priority: A
---

# Daily intel + auto-research + recurse-with-intel

Three-step morning cycle, runs ~1h before the daily report (08:00):

1. `forge intel pull` — passive RSS / Atom / GitHub-releases / changelog
   fetch from the configured allowlist (Anthropic / OpenAI / Composio /
   MCP / AutoAgent). Dedup vs `<home>/intel/seen.json`. Persists to
   `<home>/intel/<date>.json`, writes per-source vault notes, distills
   top-3 high-relevance items into the cross-project genome.

2. `forge intel research --budget daily` — AutoAgent-style sub-agent
   (Haiku, ≤4 turns, ≤8 tool calls, ≤$0.15) with `web_search` +
   `web_fetch` + `intel_store_item` enabled. Investigates each tracked
   entity, regularizer-gated ("would this still matter if THIS specific
   release vanished?"), produces a markdown summary at
   `<home>/intel/research/<ts>-daily.md`.

3. `forge recurse --with-intel` — runs the recursion proposer with the
   day's intel digest + auto-research summary injected as `intel_context`.
   AutoAgent regularizer in the proposer's system prompt still gates;
   intel is context, not license. EvalGate / score / rollback decide
   whether the candidate ships.

Total expected cost: ~$0.10/day. Result lands in `results.tsv`; the
08:00 daily report picks it up automatically.

## Success criteria
- `<home>/intel/<YYYY-MM-DD>.json` updated
- `<home>/intel/auto-research.tsv` gains a row
- `<home>/results.tsv` gains a row (kept or rolled — both fine)
- Heartbeat returncode == 0
