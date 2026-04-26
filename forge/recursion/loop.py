"""Recursive self-modification orchestrator.

  recurse_once(home, provider, score_fn) ->
    1. read traces under <home>/traces/
    2. ask `provider` for HarnessDiffs via propose_with_llm
    3. fork <home> -> <home>.candidate
    4. apply diffs to the candidate
    5. score base + candidate via score_fn
    6. keep_or_rollback: copy candidate over home, or discard
    7. write a row to <home>/results.tsv

Score function signature: Callable[[Path], float] — runs against a working copy.
"""
from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable

from ..providers.base import Provider
from .llm_proposer import ResultsLedger, propose_with_llm
from .proposer import HarnessDiff, apply, fork, keep_or_rollback

log = logging.getLogger("forge.recursion.loop")

ScoreFn = Callable[[Path], float]


@dataclass
class RecurseResult:
    diffs: list[HarnessDiff]
    base_score: float
    candidate_score: float
    kept: bool
    notes: str = ""
    candidate_path: Path | None = None
    applied: list[HarnessDiff] = field(default_factory=list)


async def recurse_once(
    home: str | Path,
    provider: Provider,
    score_fn: ScoreFn,
    *,
    margin: float = 0.0,
    suffix: str = "candidate",
    ledger_path: str | Path | None = None,
) -> RecurseResult:
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    traces = home / "traces"
    traces.mkdir(exist_ok=True)

    # 1-2. Read traces, ask the model for diffs.
    diffs = await propose_with_llm(provider, traces)
    if not diffs:
        _ledger(home, ledger_path).append(
            candidate=suffix, base_score=0.0, candidate_score=0.0, kept=False,
            notes="no diffs proposed",
        )
        return RecurseResult(
            diffs=[], base_score=0.0, candidate_score=0.0, kept=False,
            notes="no diffs proposed",
        )

    # 3. Fork.
    cand = fork(home, suffix=suffix)

    # 4. Apply.
    applied: list[HarnessDiff] = []
    for d in diffs:
        if apply(d, cand):
            applied.append(d)

    # 5. Score.
    base_score = score_fn(home)
    cand_score = score_fn(cand)

    # 6. Keep or rollback.
    kept = keep_or_rollback(base_score, cand_score, margin=margin)
    notes = f"applied={len(applied)}/{len(diffs)}"
    if kept:
        # Replace home with candidate atomically-ish (best effort on local fs).
        backup = home.with_name(home.name + ".rollback")
        if backup.exists():
            shutil.rmtree(backup)
        shutil.move(str(home), str(backup))
        shutil.move(str(cand), str(home))
        notes += "; promoted candidate over base"
    else:
        # Discard candidate.
        shutil.rmtree(cand, ignore_errors=True)
        notes += "; rolled back"

    # 7. Ledger row.
    _ledger(home, ledger_path).append(
        candidate=suffix, base_score=base_score, candidate_score=cand_score,
        kept=kept, notes=notes,
    )
    return RecurseResult(
        diffs=diffs, base_score=base_score, candidate_score=cand_score,
        kept=kept, notes=notes, candidate_path=cand if kept else None, applied=applied,
    )


def _ledger(home: Path, ledger_path: str | Path | None) -> ResultsLedger:
    return ResultsLedger(ledger_path or (home / "results.tsv"))
