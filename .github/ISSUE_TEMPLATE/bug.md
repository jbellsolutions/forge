---
name: Bug report
about: Something in forge isn't working as documented.
title: "[bug] "
labels: bug
---

## What happened

<!-- One-paragraph description. -->

## Reproduction

```python
# Minimal forge script that triggers the bug.
```

```bash
# Or the CLI invocation, if it's a CLI bug.
forge ...
```

## Expected vs. actual

- Expected: …
- Actual: …

## Environment

- forge version: <!-- `pip show forge-harness` -->
- Python version: <!-- `python --version` -->
- OS: <!-- macOS 15.x / Ubuntu 24.04 / etc. -->
- `forge doctor` output:

```
<paste here>
```

## Layer

Which layer is affected? (L0 kernel / L1 memory / L2 tools / L3 healing /
L4 swarm / L5 skills / L7 observability / recursion / CLI / MCP server)

## Additional context

<!-- Stack traces, trace files (`traces/<run_id>/*.jsonl`), screenshots. -->
