"""L4 swarm — topology + consensus + sub-agent spawning."""
from .consensus import Verdict as ConsensusVerdict, reach
from .roles import DEFAULT_ROLES, RoleAssignment, RoleCouncilSpawner
from .spawner import DEPTH_BUDGET_DECAY, SpawnDepthExceeded, Spawner, SwarmResult
from .topology import Consensus, SwarmSpec, Topology

__all__ = [
    "Consensus", "ConsensusVerdict", "reach",
    "DEFAULT_ROLES", "RoleAssignment", "RoleCouncilSpawner",
    "DEPTH_BUDGET_DECAY", "SpawnDepthExceeded",
    "Spawner", "SwarmResult", "SwarmSpec", "Topology",
]
