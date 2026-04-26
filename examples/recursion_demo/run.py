"""Recursion demo: full self-referencing self-modification cycle on REAL Anthropic.

Steps:
1. Plant synthetic failing traces (`bad_tool` errored 8x; `dangerous` blocked 4x)
   under ~/.forge/recursion-demo/traces/
2. Call propose_with_llm() against live Anthropic Sonnet — it reads the symptoms
   JSON, applies the AutoAgent regularizer ("would this still help if this task
   vanished?"), and emits HarnessDiff JSON.
3. recurse_once() forks the home dir, applies the diffs, scores both copies via
   a deterministic score_fn (counts how many breakers / deny-lists are present
   that match the symptoms), keeps or rolls back.
4. Writes a row to results.tsv. Prints the ledger.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from forge.kernel.types import AssistantTurn
from forge.providers import load_profile, make_provider
from forge.providers.mock import MockProvider
from forge.recursion import recurse_once

HOME = Path.home() / ".forge" / "recursion-demo"


def _build_provider():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        print("[recursion] using LIVE Anthropic Sonnet")
        return make_provider("anthropic")
    print("[recursion] ANTHROPIC_API_KEY empty; falling back to scripted mock")
    canned = AssistantTurn(
        text=(
            "Based on the symptoms (bad_tool errored 8x, dangerous_tool blocked 4x), "
            "honoring the regularizer:\n"
            "```json\n"
            "[\n"
            '  {"rationale":"bad_tool errored 8x — tighten breaker","target":".forge/healing/circuits.json",'
            '"op":"retune_circuit","payload":{"tool":"bad_tool","fail_threshold":2,"cooldown_seconds":1800}},\n'
            '  {"rationale":"dangerous_tool blocked 4x — deny by default","target":".claude/personas/_default.yaml",'
            '"op":"deny_tool","payload":{"tool":"dangerous_tool"}}\n'
            "]\n"
            "```"
        ),
        tool_calls=[], usage={"input_tokens": 250, "output_tokens": 90},
    )
    return MockProvider.scripted(load_profile("mock"), [canned])


def plant_synthetic_traces(home: Path) -> None:
    sd = home / "traces" / "session-001"
    sd.mkdir(parents=True, exist_ok=True)
    with (sd / "tool_calls.jsonl").open("w") as f:
        for i in range(8):
            f.write(json.dumps({
                "phase": "post", "name": "bad_tool", "is_error": True,
                "result": "connection reset", "id": f"call_{i}",
            }) + "\n")
        for i in range(4):
            f.write(json.dumps({
                "phase": "pre", "name": "dangerous_tool", "verdict": "blocked",
                "id": f"block_{i}",
            }) + "\n")
    with (sd / "events.jsonl").open("w") as f:
        f.write(json.dumps({"kind": "session_start", "agent": "demo"}) + "\n")
        f.write(json.dumps({"kind": "session_end", "agent": "demo",
                            "usage": {"input_tokens": 100, "output_tokens": 50}}) + "\n")


def score_fn(home: Path) -> float:
    """Higher is better. Reward presence of (a) a tightened circuit for bad_tool,
    (b) a deny-list entry covering dangerous_tool. Both came from the symptoms."""
    score = 0.0
    circuits = home / ".forge" / "healing" / "circuits.json"
    if circuits.exists():
        try:
            data = json.loads(circuits.read_text())
            entry = data.get("bad_tool")
            if entry and entry.get("fail_threshold", 99) <= 3:
                score += 0.5
        except json.JSONDecodeError:
            pass
    persona = home / ".claude" / "personas" / "_default.yaml"
    if persona.exists() and "dangerous_tool" in persona.read_text():
        score += 0.5
    return score


async def main() -> int:
    HOME.mkdir(parents=True, exist_ok=True)
    plant_synthetic_traces(HOME)

    provider = _build_provider()
    print(f"[recursion] home = {HOME}")
    print("[recursion] running propose_with_llm...")
    result = await recurse_once(HOME, provider, score_fn, margin=0.0)

    print(f"[recursion] diffs proposed: {len(result.diffs)}")
    for d in result.diffs:
        print(f"  - {d.op:18s} target={d.target}  rationale={d.rationale!r}")
    print(f"[recursion] base_score={result.base_score:.2f} candidate_score={result.candidate_score:.2f}")
    print(f"[recursion] kept={result.kept}  notes={result.notes}")

    ledger = HOME / "results.tsv"
    if ledger.exists():
        print("\n[recursion] ledger:")
        print(ledger.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
