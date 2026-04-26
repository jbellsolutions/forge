"""Phase 4 — swarm."""
from __future__ import annotations

import pytest

from forge.swarm import Consensus, SwarmSpec, Topology
from forge.swarm.consensus import majority, reach, unanimous, weighted


def test_majority_picks_plurality():
    v = majority(["ship", "ship", "wait"])
    assert v.winner == "ship"
    assert v.method == Consensus.MAJORITY


def test_unanimous_returns_none_on_disagreement():
    assert unanimous(["ship", "wait"]) is None


def test_weighted_respects_weights():
    v = weighted([("ship", 0.2), ("ship", 0.3), ("wait", 0.9)])
    assert v.winner == "wait"


def test_reach_falls_back_for_unanimous():
    v = reach(["ship", "ship", "wait"], Consensus.UNANIMOUS)
    assert v.winner == "ship"
    assert "majority" in v.rationale.lower()


def test_swarm_spec_defaults():
    s = SwarmSpec()
    assert s.topology == Topology.SOLO
    assert s.consensus == Consensus.MAJORITY
