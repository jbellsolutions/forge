<!-- Thanks for opening this. Read ETHOS.md and ARCHITECTURE.md if you haven't. -->

## What changed

<!-- One paragraph. The why, not the what. -->

## Layer

<!-- L0 kernel / L1 memory / L2 tools / L3 healing / L4 swarm / L5 skills /
L7 observability / recursion / CLI / MCP server / docs -->

## Layer ordering check

- [ ] L0 imports nothing above.
- [ ] Higher layers only import from layers strictly below.
- [ ] Vendor SDKs (`anthropic`, `openai`, `mcp`, `composio`, `opentelemetry`)
      are lazy-imported inside the constructor that needs them.

## Public API impact

- [ ] No public API change.
- [ ] Added a symbol — mirrored in layer `__init__.py` and
      `forge/__init__.py.__all__`.
- [ ] Removed/renamed a symbol — CHANGELOG entry under "Unreleased"
      describing the breaking change.

## Tests

- [ ] Added a test under `tests/test_<layer>.py`.
- [ ] `pytest -q` passes locally without API keys.
- [ ] `forge doctor` is green.

## Verification

<!-- How can a reviewer confirm this works? Live verification command,
expected output, ledger row, trace path. -->

## CHANGELOG

- [ ] Updated `CHANGELOG.md` under "Unreleased".
- [ ] N/A — internal-only, no user-facing change.
