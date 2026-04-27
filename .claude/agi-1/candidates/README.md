# candidates/ — filesystem-based history for agi-learn and agi-council

Each `iter_NNNN/` directory is a full snapshot of one learning or council iteration.
Future iterations grep across all prior candidates to ground their reasoning — this
is the meta-harness pattern: proposers see full reasoning, not scalar summaries.

## Per-iteration files

| File | Written by | Purpose |
|---|---|---|
| `reasoning.md` | learner / council | Human-readable narrative |
| `score.json` | learner / agi-1 Phase 5 | `{"before": …, "after": …}` |
| `trace.log` | learner | Append-only grep-friendly stream |
| `insights-applied.json` | learner | Which insights were applied this run |
| `council-synthesis.json` | council | Full synthesis with `prior_ref` and counterfactual |
| `harness-snapshot.txt` | learner | sha256sum of every file touched |
| `REGRESSION.md` | learner (only on regressions) | Why this iter regressed |

## INDEX.json shape

```json
{"iterations":[{"id":"iter_0001","timestamp":"...","source":"learner|council|autoresearch","applied_count":N,"rejected_count":N,"score_delta":N,"reverted":false}]}
```

## Hard rules

1. Never delete an iter_NNNN directory. Reverted iterations stay on disk.
2. Never rewrite an iter_NNNN directory in place. Create a new iter with the fix.
3. INDEX.json is append-only unless correcting a bug in a prior entry.
