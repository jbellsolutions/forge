"""Skill autosynthesizer — propose a v(N+1) from successful run traces.

Lifted from Hermes's "agent writes skills post-task" + Justin's eval-gated A/B.
The proposer is a callable: given (current_body, recent_runs) -> candidate_body.
A null-safe default proposer just appends a "Lessons learned" section drawn from
top-scoring runs; production swaps in a real LLM call.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .skill import SkillRun, SkillStore

Proposer = Callable[[str, list[SkillRun]], str]


def default_proposer(current_body: str, recent_runs: list[SkillRun]) -> str:
    """Naive proposer: distill top-quartile outputs into a 'Lessons learned' block."""
    if not recent_runs:
        return current_body
    top = sorted(recent_runs, key=lambda r: r.outcome_score, reverse=True)
    quartile = max(1, len(top) // 4)
    winners = top[:quartile]
    bullets = "\n".join(f"- ({r.outcome_score:+.2f}) {r.output[:200]}" for r in winners)
    addendum = f"\n\n## Lessons learned (auto-distilled)\n{bullets}\n"
    if "## Lessons learned" in current_body:
        # Replace existing section
        before, _, _after = current_body.partition("## Lessons learned")
        return before.rstrip() + addendum
    return current_body.rstrip() + addendum


@dataclass
class SynthResult:
    skill: str
    new_version: str
    body: str


def autosynth(
    store: SkillStore,
    skill: str,
    *,
    proposer: Proposer | None = None,
    min_runs: int = 10,
    positive_floor: float = 0.0,
) -> SynthResult | None:
    """Look at recent runs of the current version. If enough successful, propose v(N+1)."""
    proposer = proposer or default_proposer
    current = store.current_version(skill)
    runs = [r for r in store.runs(skill, version=current) if r.outcome_score > positive_floor]
    if len(runs) < min_runs:
        return None

    body = store.read_skill(skill, current)
    new_body = proposer(body, runs)
    if new_body == body:
        return None

    versions = store.versions(skill)
    next_n = max(int(v[1:]) for v in versions if v.startswith("v")) + 1
    new_version = f"v{next_n}"
    store.write_skill(skill, new_body, version=new_version)
    return SynthResult(skill=skill, new_version=new_version, body=new_body)
