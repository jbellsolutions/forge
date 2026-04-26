"""Eval gate — promote a candidate version only if it beats current by margin.

Lifted from Justin's Orgo `self_improve.py`:
  MIN_SAMPLES = 50
  CONFIDENCE_MARGIN = 0.05
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .skill import SkillRun, SkillStore


MIN_SAMPLES = 50
CONFIDENCE_MARGIN = 0.05


@dataclass
class EvalReport:
    skill: str
    current: str
    candidate: str
    current_n: int
    candidate_n: int
    current_mean: float
    candidate_mean: float
    margin: float
    promoted: bool
    reason: str


def _mean(runs: list[SkillRun]) -> float:
    if not runs:
        return 0.0
    return statistics.fmean(r.outcome_score for r in runs)


def evaluate(
    store: SkillStore,
    skill: str,
    candidate: str,
    *,
    min_samples: int = MIN_SAMPLES,
    margin: float = CONFIDENCE_MARGIN,
) -> EvalReport:
    current = store.current_version(skill)
    cur_runs = store.runs(skill, version=current)
    cand_runs = store.runs(skill, version=candidate)

    cur_mean = _mean(cur_runs)
    cand_mean = _mean(cand_runs)
    delta = cand_mean - cur_mean

    if len(cand_runs) < min_samples:
        return EvalReport(
            skill, current, candidate, len(cur_runs), len(cand_runs),
            cur_mean, cand_mean, delta, False,
            f"insufficient samples ({len(cand_runs)} < {min_samples})",
        )
    if delta < margin:
        return EvalReport(
            skill, current, candidate, len(cur_runs), len(cand_runs),
            cur_mean, cand_mean, delta, False,
            f"margin {delta:+.3f} below threshold {margin}",
        )
    return EvalReport(
        skill, current, candidate, len(cur_runs), len(cand_runs),
        cur_mean, cand_mean, delta, True,
        f"margin {delta:+.3f} >= {margin} with N={len(cand_runs)}",
    )


def promote_if_passing(store: SkillStore, skill: str, candidate: str, **kwargs) -> EvalReport:
    report = evaluate(store, skill, candidate, **kwargs)
    if report.promoted:
        store.set_current(skill, candidate)
    return report
