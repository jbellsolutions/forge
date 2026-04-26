"""LLM-driven proposer for recursive self-modification.

Reads raw traces (Meta-Harness invariant — no summarization), wraps them in a
proposer prompt, and asks the model to emit HarnessDiff JSON.

Lifts AutoAgent patterns:
- `program.md` regularizer line: "would this still help if this specific task vanished?"
- `# === FIXED ADAPTER BOUNDARY ===` sentinel — the LLM is told NOT to cross it
- `results.tsv` — flat append-only scoreboard the LLM reads + writes
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from ..providers.base import Provider
from ..kernel.types import AssistantTurn, Message
from .proposer import HarnessDiff, TraceAnalyzer

log = logging.getLogger("forge.recursion.llm")


# Lifted verbatim from AutoAgent's program.md regularizer.
PROGRAM_DIRECTIVE = """\
# Forge Self-Modification Directive

## Mission
Improve the harness's outcome score on the active task suite without breaking
the FIXED ADAPTER BOUNDARY contract.

## Primary metric
- pass_count: number of tasks that complete successfully
## Secondary metric
- mean_outcome_score: across all logged skill runs

## Regularizer (READ THIS BEFORE PROPOSING)
> Would this proposed change still help if this specific failing task vanished tomorrow?
> If the answer is "no" — DO NOT PROPOSE IT. We are not overfitting to a single trace.

## Hard constraints
- DO NOT modify code below the `# === FIXED ADAPTER BOUNDARY ===` sentinel.
- DO NOT propose changes to provider profiles unless errors clearly originate there.
- Each proposed diff MUST cite a trace path and a failure pattern.

## Output contract
Return ONLY a JSON array of objects. The harness understands EXACTLY these op shapes:

retune_circuit — tighten a CircuitBreaker for a misbehaving tool:
  {"rationale":"...","target":".forge/healing/circuits.json","op":"retune_circuit",
   "payload":{"tool":"<exact tool name from symptoms>","fail_threshold":2,"cooldown_seconds":1800}}

deny_tool — add a tool to the default persona's deny-list:
  {"rationale":"...","target":".claude/personas/_default.yaml","op":"deny_tool",
   "payload":{"tool":"<exact tool name from symptoms>"}}

patch_yaml — append a stanza to a YAML file (last resort):
  {"rationale":"...","target":"<relative path>","op":"patch_yaml",
   "payload":{"yaml":"key: value"}}

Use ONLY these targets and payload keys. Tool names must match those in symptoms.
Empty array `[]` means: I see no safe change to propose.
"""


PromptBuilder = Callable[[str, dict], str]


def default_prompt(directive: str, symptoms: dict) -> str:
    return (
        f"{directive}\n\n"
        f"## Trace symptoms (observed)\n```json\n{json.dumps(symptoms, indent=2)}\n```\n\n"
        f"## Task\nPropose 0-3 HarnessDiffs honoring the regularizer.\n"
    )


def parse_diffs(text: str) -> list[HarnessDiff]:
    """Tolerant JSON-array extraction — strips fences, finds first `[...]` block."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.warning("LLM proposer returned non-JSON; got %r", text[:200])
        return []
    out: list[HarnessDiff] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            out.append(HarnessDiff(
                rationale=item["rationale"],
                target=item["target"],
                op=item["op"],
                payload=item.get("payload", {}),
            ))
        except KeyError:
            continue
    return out


async def propose_with_llm(
    provider: Provider,
    traces_root: str | Path,
    *,
    prompt_builder: PromptBuilder = default_prompt,
    directive: str = PROGRAM_DIRECTIVE,
) -> list[HarnessDiff]:
    """Read traces, ask the model, return parsed HarnessDiffs."""
    symptoms = TraceAnalyzer(traces_root).symptoms()
    prompt = prompt_builder(directive, symptoms)
    turn: AssistantTurn = await provider.generate(
        messages=[
            Message(role="system", content="You are forge's recursive self-mod proposer."),
            Message(role="user", content=prompt),
        ],
        tools=[],
        max_tokens=2048,
    )
    return parse_diffs(turn.text)


# === FIXED ADAPTER BOUNDARY ===
# Code BELOW this line is the immutable trace -> diff IO contract.
# The recursive proposer must NEVER edit anything past this sentinel.
# Lift from AutoAgent: physically separate proposer-mutable code from boundaries.

class ResultsLedger:
    """Append-only flat scoreboard. The recursion gate's only persistence.

    Lifted from AutoAgent's results.tsv. Format: tab-separated, one row per
    candidate evaluation. Schema is fixed below the boundary.
    """
    HEADER = "timestamp\tcandidate\tbase_score\tcandidate_score\tdelta\tkept\tnotes"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(self.HEADER + "\n")

    def append(
        self,
        *, candidate: str, base_score: float, candidate_score: float,
        kept: bool, notes: str = "",
    ) -> None:
        import time as _t
        delta = candidate_score - base_score
        row = "\t".join([
            f"{_t.time():.3f}", candidate,
            f"{base_score:.4f}", f"{candidate_score:.4f}",
            f"{delta:+.4f}", "1" if kept else "0",
            notes.replace("\t", " "),
        ])
        with self.path.open("a", encoding="utf-8") as f:
            f.write(row + "\n")

    def rows(self) -> list[dict]:
        lines = self.path.read_text().splitlines()
        if len(lines) < 2:
            return []
        header = lines[0].split("\t")
        return [dict(zip(header, r.split("\t"))) for r in lines[1:] if r.strip()]
