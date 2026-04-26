"""Role-injecting Spawner subclass — gives each council member a distinct system prompt.

Without role differentiation, three identical Sonnet calls produce three near-identical
answers and consensus is fake. Roles force productive disagreement.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..kernel.loop import AgentLoop, LoopResult
from ..kernel.types import AgentDef, PermissionMode
from ..providers import make_provider
from .spawner import Spawner


DEFAULT_ROLES = {
    "optimist":   "You are the OPTIMIST. Argue why we should do this; weight upside higher than downside.",
    "skeptic":    "You are the SKEPTIC. Argue why we should NOT do this; weight downside higher than upside.",
    "pragmatist": "You are the PRAGMATIST. Recommend the lowest-regret next step. Do NOT hedge.",
}


@dataclass
class RoleAssignment:
    """Maps council position -> profile + role label."""
    profile: str
    role: str


class RoleCouncilSpawner(Spawner):
    """Spawner that injects per-member role instructions.

    Use `set_assignments([RoleAssignment(...), ...])` before `run()`. The order
    matches `SwarmSpec.members` order.
    """

    def __init__(self, *args, role_prompts: dict[str, str] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._roles = role_prompts or DEFAULT_ROLES
        self._assignments: list[RoleAssignment] = []
        self._idx = 0

    def set_assignments(self, assignments: list[RoleAssignment]) -> None:
        self._assignments = assignments
        self._idx = 0

    async def _run_member(self, profile_name: str, task: str, role: str) -> LoopResult:
        # Pull the next assignment if any; fall back to vanilla spawner behaviour.
        if self._assignments:
            assignment = self._assignments[self._idx % len(self._assignments)]
            self._idx += 1
            profile_name = assignment.profile
            role_prompt = self._roles.get(assignment.role, assignment.role)
            instructions = f"{self.base_instructions}\n{role_prompt}"
            agent_name = f"{assignment.role}:{profile_name}"
        else:
            role_prompt = role
            instructions = f"{self.base_instructions}\nRole: {role}."
            agent_name = f"{role}:{profile_name}"

        provider = make_provider(profile_name)
        agent = AgentDef(
            name=agent_name,
            instructions=instructions,
            profile=profile_name,
            permission_mode=PermissionMode.AUTO,
        )
        loop = AgentLoop(agent, provider, self.tools, hooks=self.hooks, max_turns=self.max_turns)
        return await loop.run(task)
