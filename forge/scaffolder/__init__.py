"""forge.scaffolder — describe a swarm in English, get a swarm.

This is the user-facing entry point that turns a free-text description
("an SDR that pulls Apollo leads, qualifies them with Claude, and DMs the
hot ones to Slack daily at 8am") into:

1. A SwarmDesign — structured agents, roles, tools, schedule
2. Output in one of three modes:
   - terminal   : examples/<name>/run.py + heartbeats (run via `forge run`)
   - claude     : .claude/agents/<name>.md per agent (drop into any Claude
                  Code session as subagents)
   - dashboard  : POSTs a propose_start_project PendingAction to the
                  Railway-hosted dashboard for Approve flow

The design step uses a real LLM (the same provider system the rest of forge
uses); fall back to a deterministic single-agent skeleton if no key is set.
"""
from __future__ import annotations

from .design import SwarmDesign, AgentSpec, design_swarm
from .writers import (
    write_terminal_project,
    write_claude_subagents,
    propose_dashboard_action,
)

__all__ = [
    "SwarmDesign", "AgentSpec", "design_swarm",
    "write_terminal_project", "write_claude_subagents",
    "propose_dashboard_action",
]
