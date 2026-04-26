"""L4 swarm — topology + consensus + sub-agent spawning."""
from .consensus import Verdict as ConsensusVerdict, reach
from .spawner import Spawner, SwarmResult
from .topology import Consensus, SwarmSpec, Topology

__all__ = [
    "Consensus", "ConsensusVerdict", "reach",
    "Spawner", "SwarmResult", "SwarmSpec", "Topology",
]
