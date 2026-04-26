# TODOS

Tracked future work. Source-of-truth is this file plus GitHub Issues; the
codebase itself is currently free of `TODO` / `FIXME` / `HACK` markers
(grep verified at v0.1.1).

## Near-term (0.2.x)

- [ ] OpenRouter live verification — DeepSeek + Qwen paths exercised end-to-end with telemetry rows.
- [ ] Ollama local-model live verification (currently profile-only).
- [ ] Composio "tool-using council" example beyond the basic 1,048-app discovery smoke test.
- [ ] `forge dashboard` HTML export option (today: TSV/JSON only).
- [ ] Schema validation pass for every YAML profile under `forge/providers/profiles/` at import time.
- [ ] Property-based tests for `CircuitBreaker` state transitions (hypothesis).

## Medium-term (0.3.x)

- [ ] Hierarchy + Mesh topologies wired with consensus algorithms (today: SOLO and PARALLEL_COUNCIL are exercised; HIERARCHY/MESH are typed but lightly tested).
- [ ] Raft + BFT consensus implementations (today: MAJORITY/WEIGHTED/UNANIMOUS/QUEEN).
- [ ] WASM Agent Booster tier (Ruflo pattern) — LLM-bypass for deterministic transforms, <1ms / $0.
- [ ] Skill autosynth driven by live LLM proposer (today: rule-based proposer + manual skill drafting).
- [ ] OTel exporter wired to a real backend in CI (today: no-op when `opentelemetry` absent).

## Long-term

- [ ] Recursion proposer trained on a corpus of real harness mods + their ledger outcomes.
- [ ] Cross-machine genome sync (today: single-user, single-machine `~/.forge/genome.json`).
- [ ] First-class TS adapter for the kernel (today: Python-only; CLIs-as-tools cover the gap).
- [ ] `forge new <vertical>` scaffolder.

## Won't do

See `ETHOS.md` non-goals. Not adding: web UI, hosted service,
multi-tenancy, chatbot framing, "agentic everything" for deterministic
transforms.
