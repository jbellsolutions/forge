"""Sub-agent spawner. Runs SwarmSpec and returns a Verdict + per-agent results."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from ..kernel.hooks import HookBus
from ..kernel.loop import AgentLoop, LoopResult
from ..kernel.types import AgentDef, PermissionMode
from ..providers import make_provider
from ..tools.registry import ToolRegistry
from .consensus import Verdict, reach
from .topology import Consensus, SwarmSpec, Topology

log = logging.getLogger("forge.swarm")


@dataclass
class SwarmResult:
    spec: SwarmSpec
    members: list[tuple[str, LoopResult]]   # (agent_name, result)
    verdict: Verdict | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Spawner:
    def __init__(
        self,
        tools: ToolRegistry,
        hooks: HookBus | None = None,
        base_instructions: str = "You are a member of a forge swarm.",
        max_turns: int = 6,
    ) -> None:
        self.tools = tools
        self.hooks = hooks
        self.base_instructions = base_instructions
        self.max_turns = max_turns

    async def run(self, task: str, spec: SwarmSpec) -> SwarmResult:
        if spec.topology == Topology.SOLO:
            return await self._solo(task, spec)
        if spec.topology == Topology.PARALLEL_COUNCIL:
            return await self._parallel_council(task, spec)
        if spec.topology == Topology.HIERARCHY:
            return await self._hierarchy(task, spec)
        raise NotImplementedError(f"topology {spec.topology} not yet implemented")

    # ---- topologies ------------------------------------------------------

    async def _solo(self, task: str, spec: SwarmSpec) -> SwarmResult:
        member = spec.members[0] if spec.members else "anthropic"
        result = await self._run_member(member, task, role="solo")
        return SwarmResult(spec=spec, members=[(member, result)])

    async def _parallel_council(self, task: str, spec: SwarmSpec) -> SwarmResult:
        coros = [self._run_member(m, task, role="council-member") for m in spec.members]
        results = await asyncio.gather(*coros)
        members = list(zip(spec.members, results, strict=True))
        outputs = [r.final_text for _, r in members]
        verdict = reach(outputs, spec.consensus)
        return SwarmResult(spec=spec, members=members, verdict=verdict)

    async def _hierarchy(self, task: str, spec: SwarmSpec) -> SwarmResult:
        queen = spec.queen or (spec.members[0] if spec.members else "anthropic")
        # Queen plans the work
        plan_result = await self._run_member(
            queen, f"Decompose this task into 1-3 worker steps. Task: {task}",
            role="queen",
        )
        # Each worker executes one step (here: just rerun the task; topology hook for full DAG goes here)
        worker_coros = [
            self._run_member(m, task, role="worker")
            for m in spec.members if m != queen
        ]
        worker_results = await asyncio.gather(*worker_coros) if worker_coros else []
        members = [(queen, plan_result)] + list(zip(
            [m for m in spec.members if m != queen], worker_results, strict=True,
        ))
        # QUEEN consensus = queen's output wins
        verdict = reach([plan_result.final_text], Consensus.QUEEN)
        return SwarmResult(spec=spec, members=members, verdict=verdict)

    # ---- helpers ---------------------------------------------------------

    async def _run_member(self, profile_name: str, task: str, role: str) -> LoopResult:
        provider = make_provider(profile_name)
        agent = AgentDef(
            name=f"{role}:{profile_name}",
            instructions=f"{self.base_instructions}\nRole: {role}.",
            profile=profile_name,
            permission_mode=PermissionMode.AUTO,
        )
        loop = AgentLoop(agent, provider, self.tools, hooks=self.hooks, max_turns=self.max_turns)
        return await loop.run(task)
