"""Swarm-design step — text in, structured SwarmDesign out.

Calls the configured provider with a tightly-scoped JSON-only prompt.
Robust to:
- No API key → returns a deterministic single-agent fallback skeleton
- LLM returns malformed JSON → strips fences, retries parse, ultimately
  falls back to single-agent skeleton with a warning in `notes`
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any

from ..kernel.types import Message
from ..providers import make_provider


@dataclass
class AgentSpec:
    name: str            # snake_case, file-safe
    role: str            # one-line role label ("qualifier", "summarizer", …)
    instructions: str    # system prompt body
    profile: str = "anthropic"           # provider profile (must exist in forge)
    tools: list[str] = field(default_factory=list)   # tool names — best-effort match against ToolRegistry


@dataclass
class SwarmDesign:
    name: str                  # project slug — snake_case
    description: str           # 1-2 sentence human description
    agents: list[AgentSpec] = field(default_factory=list)
    schedule: str | None = None        # cron expression or None for on-demand
    consensus: str = "none"            # "none" | "majority" | "weighted" — for multi-agent councils
    topology: str = "single"           # "single" | "parallel_council" | "pipeline"
    notes: str = ""                    # design rationale + any fallback warnings

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SwarmDesign":
        agents = [
            AgentSpec(
                name=str(a.get("name", "agent")).strip().replace("-", "_").replace(" ", "_"),
                role=str(a.get("role", "")),
                instructions=str(a.get("instructions", "")),
                profile=str(a.get("profile", "anthropic")),
                tools=list(a.get("tools") or []),
            )
            for a in (d.get("agents") or [])
        ]
        if not agents:
            agents = [_default_single_agent(d.get("description", ""))]
        return cls(
            name=_slug(d.get("name", "swarm")),
            description=str(d.get("description", "")),
            agents=agents,
            schedule=d.get("schedule"),
            consensus=str(d.get("consensus", "none")),
            topology=str(d.get("topology", "single")),
            notes=str(d.get("notes", "")),
        )


# ---------------------------------------------------------------------------

DESIGN_PROMPT = """\
You design agent swarms. The user wants:

<description>
{description}
</description>

Return ONLY a JSON object — no prose, no code fences — matching this schema:
{{
  "name": "<snake_case project name>",
  "description": "<1-2 sentence summary>",
  "topology": "single" | "parallel_council" | "pipeline",
  "consensus": "none" | "majority" | "weighted",
  "schedule": "<cron expression>" or null,
  "agents": [
    {{
      "name": "<snake_case>",
      "role": "<one-line label>",
      "instructions": "<system prompt body, 2-6 sentences>",
      "profile": "anthropic" | "anthropic-haiku" | "openai-gpt4" | "openrouter-deepseek",
      "tools": ["tool_name", ...]
    }}
  ],
  "notes": "<design rationale: why this topology, why these agents>"
}}

Rules:
- Prefer ONE agent unless the user asked for council/debate/multi-perspective work
- Tools must be from this allowlist (best-effort; unknown tools ignored later):
  fs_read, fs_write, web_search, web_fetch, slack_send_message, slack_search,
  notion_search, gmail_search, gcal_list_events, exec_shell
- Use anthropic-haiku for cheap routine work, anthropic for complex reasoning
- schedule: only set if the user explicitly asked for recurring/daily/weekly behavior
"""


async def design_swarm(description: str, *, profile: str = "anthropic-haiku") -> SwarmDesign:
    """Ask the LLM to propose a swarm. Falls back to a single-agent skeleton
    if no provider is reachable or the LLM returns garbage."""
    description = description.strip()
    if not description:
        raise ValueError("description must not be empty")

    try:
        provider = make_provider(profile)
    except Exception as e:  # noqa: BLE001
        return _fallback(description, f"provider unavailable: {e}")

    prompt = DESIGN_PROMPT.format(description=description)
    try:
        turn = await provider.generate(
            messages=[Message(role="user", content=prompt)],
            tools=None, max_tokens=2000,
        )
    except Exception as e:  # noqa: BLE001
        return _fallback(description, f"LLM call failed: {e}")

    raw = (turn.text or "").strip()
    raw = _strip_fences(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return _fallback(description, f"LLM returned non-JSON: {e}; raw[:200]={raw[:200]!r}")

    try:
        design = SwarmDesign.from_dict(data)
    except Exception as e:  # noqa: BLE001
        return _fallback(description, f"design schema error: {e}")
    if not design.notes:
        design.notes = f"designed by {profile}"
    return design


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fences(s: str) -> str:
    """Tolerate models that wrap JSON in ```json ... ``` despite instructions."""
    return _FENCE_RE.sub("", s).strip()


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", s.strip().lower())
    return re.sub(r"_+", "_", s).strip("_") or "swarm"


def _default_single_agent(description: str) -> AgentSpec:
    return AgentSpec(
        name="agent",
        role="generalist",
        instructions=(description or "Perform the user's task.").strip(),
        profile="anthropic",
        tools=[],
    )


def _fallback(description: str, reason: str) -> SwarmDesign:
    name = _slug(description.split(".")[0][:40] or "swarm")
    return SwarmDesign(
        name=name,
        description=description[:200],
        agents=[_default_single_agent(description)],
        schedule=None,
        topology="single",
        consensus="none",
        notes=f"FALLBACK ({reason}) — review and edit before running.",
    )
