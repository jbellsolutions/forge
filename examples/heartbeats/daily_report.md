---
schedule: "0 8 * * *"
command: "forge report --period day --to auto"
priority: A
---

# Daily report

Build the day's self-improvement digest from local artifacts (recursion
ledger, skill events, denial loops, telemetry, genome growth, today's
intel) and deliver via the configured channel (Slack MCP if
`<home>/delivery.yaml` is configured, otherwise markdown file at
`<home>/digests/day-<date>.md`).

The digest is privacy-scrubbed: counts + names + score deltas only,
never message content. See `forge/observability/digest.py` for the
exact invariant.

## Success criteria
- File written to `<home>/digests/day-<YYYY-MM-DD>.md`
- If Slack delivery configured, message lands in the channel
- No `"role"` or `"content"` substrings in the output
- Heartbeat returncode == 0
