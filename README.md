# forge

A model-agnostic, self-learning, self-healing agent harness.

Plug any model (Claude Opus, DeepSeek V4, GPT-5, Ollama). Spawn parallel councils, hierarchical swarms, recursive self-modification loops. Skills self-synthesize and pass an eval gate before promotion. Every action goes through a hook bus with a dry-run verdict. Traces are stored full-fidelity for replay and counterfactual diagnosis.

## Layers

```
L7  Observability  OTel · token+cost · dry-run verdict · replayable traces
L6  Use-case       Personas · skills · routers · heartbeats
L5  Self-improve   Skill autosynthesis · eval gate · skill search
L4  Swarm          Topology × consensus · sub-agent isolation
L3  Self-healing   ErrorType · CircuitBreaker · retry policy
L2  Tools          MCP → Computer/Browser → CLI shell · per-persona deny-list
L1  Memory         ReasoningBank · git journal · trace filesystem · .claude/
L0  Kernel         Agent loop · hook lifecycle · provider-as-profile
```

## Status

Phase 0 — kernel + hook bus + provider profile + smoke example. See `examples/hello_world.py`.

## Quickstart

```bash
pip install -e .
python examples/hello_world.py            # mock provider, no API key
ANTHROPIC_API_KEY=sk-... python examples/hello_world.py --provider anthropic
```

## Design decisions (locked)

- Python core, thin TS adapter where Claude SDK / browser MCP demands it
- Full tool access default, deny-list per persona (compensated by L3 hook gates)
- Greenfield repo — concepts imported from Ruflo / OpenHarness / Hermes / Meta-Harness
- Skills gated by `MIN_SAMPLES=50` + `CONFIDENCE_MARGIN=0.05` before promotion

See `/Users/home/.claude/plans/okay-so-if-i-immutable-seahorse.md` for full blueprint.
