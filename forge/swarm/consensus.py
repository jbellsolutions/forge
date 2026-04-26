"""Consensus algorithms over a set of agent outputs."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .topology import Consensus


@dataclass
class Verdict:
    winner: str
    votes: dict[str, int]
    method: Consensus
    rationale: str


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def majority(outputs: list[str]) -> Verdict:
    counts = Counter(_normalize(o) for o in outputs)
    winner_norm, n = counts.most_common(1)[0]
    # find first original matching
    winner = next(o for o in outputs if _normalize(o) == winner_norm)
    return Verdict(
        winner=winner, votes=dict(counts), method=Consensus.MAJORITY,
        rationale=f"plurality {n}/{len(outputs)}",
    )


def weighted(outputs: list[tuple[str, float]]) -> Verdict:
    """Each item: (output, weight). Weights summed per normalized output."""
    weights: dict[str, float] = {}
    samples: dict[str, str] = {}
    for o, w in outputs:
        k = _normalize(o)
        weights[k] = weights.get(k, 0.0) + w
        samples.setdefault(k, o)
    winner_norm = max(weights, key=weights.get)  # type: ignore[arg-type]
    return Verdict(
        winner=samples[winner_norm],
        votes={k: int(v * 100) for k, v in weights.items()},
        method=Consensus.WEIGHTED,
        rationale=f"weighted total {weights[winner_norm]:.2f}",
    )


def unanimous(outputs: list[str]) -> Verdict | None:
    if len({_normalize(o) for o in outputs}) == 1 and outputs:
        return Verdict(
            winner=outputs[0], votes={_normalize(outputs[0]): len(outputs)},
            method=Consensus.UNANIMOUS, rationale="all agree",
        )
    return None


def reach(outputs: list[Any], method: Consensus) -> Verdict:
    if method == Consensus.MAJORITY:
        return majority([str(o) for o in outputs])
    if method == Consensus.WEIGHTED:
        return weighted(outputs)  # type: ignore[arg-type]
    if method == Consensus.UNANIMOUS:
        v = unanimous([str(o) for o in outputs])
        if v:
            return v
        # Fall back to majority with rationale flag.
        v = majority([str(o) for o in outputs])
        v.rationale = "no unanimity; fell back to majority"
        return v
    if method == Consensus.QUEEN:
        # Queen's output expected first.
        winner = str(outputs[0]) if outputs else ""
        return Verdict(winner=winner, votes={_normalize(winner): 1},
                       method=Consensus.QUEEN, rationale="queen's verdict")
    raise ValueError(f"unknown consensus {method}")
