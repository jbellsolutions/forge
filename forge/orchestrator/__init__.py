"""forge.orchestrator — the Papa Bear agent.

Re-exports the single entry point + action proposers. The persona prompt
lives at `forge/orchestrator/persona.md` and is read at every chat turn.
Project scaffolds live under `forge/orchestrator/templates/`.
"""
from __future__ import annotations

from .actions import (
    propose_run_recurse,
    propose_spawn,
    propose_start_project,
    propose_update,
)

# OrchestratorAgent depends on the dashboard package; only import it lazily
# so importing forge.orchestrator without the [dashboard] extra still works
# enough to access the action helpers and templates.
def _import_agent():
    from .agent import OrchestratorAgent
    return OrchestratorAgent


__all__ = [
    "propose_spawn", "propose_update",
    "propose_start_project", "propose_run_recurse",
    "_import_agent",
]
