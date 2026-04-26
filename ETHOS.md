# forge — Ethos

The design philosophy. What forge is, what it isn't, and the rules that govern
which PRs land.

## Mission

A **model-agnostic, self-learning, self-healing agent harness** that decouples
the chassis from the use case. The same kernel runs an SDR vertical, a COO
vertical, a code-agent vertical — swap the model by changing one YAML profile.

## Principles

1. **Small kernel, big seams.** L0 is ~2k lines on purpose. The hook bus is
   the extensibility seam. Everything else (swarm, recursion, skills, memory)
   is opt-in modules that subscribe to L0 — never reach across layers.
2. **Provider-as-profile.** No vendor SDK is imported by the kernel. Adding
   a model means writing a YAML profile, not editing core code.
3. **Trace-fidelity is sacred.** Full-fidelity execution traces are the
   training data for the recursion proposer. Compaction is allowed for the
   *agent's* context window, never for the optimizer.
4. **Eval-gated promotion.** Skills and harness mods are promoted only when
   `MIN_SAMPLES=50` runs show `CONFIDENCE_MARGIN ≥ 0.05` improvement. No vibes.
5. **Layer ordering enforced.** L0 may not import any higher layer; L1–L7
   may only import below. PRs that violate this get rejected on sight.
6. **Lazy vendor imports.** Optional SDKs (`anthropic`, `openai`, `mcp`,
   `composio`, `opentelemetry`) load inside the constructor that needs them.
   Base install stays pure-Python.

## Quality bar

- Type hints on every public function. `from __future__ import annotations`
  at the top of every module.
- Tests under `tests/test_<layer>.py`. Suite stays under 30s without API keys.
- Public API mirrored from `forge/__init__.py.__all__` — symbols here are
  the SemVer contract.
- `forge doctor` must stay green on a fresh clone.

## Non-goals

- **Not a chatbot framework.** forge is for agents that DO things — call
  tools, modify files, spawn councils, recurse on themselves. If you want
  conversational UX, build it on top.
- **Not a UI.** No web dashboard ships in the wheel. The `dashboard` CLI is
  read-only TSV/JSON output. Build your own viz layer.
- **Not a model provider.** forge routes; it doesn't host. Bring your own
  Anthropic / OpenAI / OpenRouter / Ollama key.
- **Not a multi-tenant platform.** Single-user, single-machine assumption.
  `~/.forge/genome.json` is one user's compounding learnings.
- **Not "agentic everything".** If a deterministic function works, use it.
  Ruflo's WASM-bypass tier exists because <1ms / $0 beats an LLM call.

## What gets a PR rejected

- Adding a new dependency to base install. Lazy-import or optional-extra it.
- Hardcoding a model name in the kernel.
- Importing from `forge.swarm`, `forge.skills`, etc. inside `forge.kernel`.
- Skill or harness mod that bypasses the eval gate.
- Tests that require network or API keys to pass without `@pytest.mark.live`.
- Compacting traces before the recursion proposer reads them.

## What gets a PR landed fast

- Closes a real verification gap from the README's live-verification table.
- Adds a provider profile (one YAML, optional adapter shim).
- Adds a tool to L2 with a tier classification + per-agent allowlist test.
- Adds a consensus algorithm to L4 with a 3-member test.
- Improves the recursion proposer's regularizer logic with a trace example.
