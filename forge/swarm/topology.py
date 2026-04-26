"""Topology + consensus primitives. Lifted from Ruflo's swarm config model."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Topology(str, Enum):
    SOLO = "solo"                      # one agent, no peers
    PARALLEL_COUNCIL = "parallel"      # N agents, run concurrently, consensus over outputs
    HIERARCHY = "hierarchy"            # queen + workers (sequential delegation)
    MESH = "mesh"                      # full peer-to-peer (placeholder for now)


class Consensus(str, Enum):
    MAJORITY = "majority"              # plurality wins
    WEIGHTED = "weighted"              # weighted vote (e.g. by model cost tier)
    UNANIMOUS = "unanimous"
    QUEEN = "queen"                    # only the queen's verdict counts (hierarchy)


@dataclass
class SwarmSpec:
    topology: Topology = Topology.SOLO
    consensus: Consensus = Consensus.MAJORITY
    members: list[str] = field(default_factory=list)   # agent profile names
    queen: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
