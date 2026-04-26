"""SDR template — outbound sales-development vertical scaffold."""
from __future__ import annotations

FILES: dict[str, str] = {
    "examples/{name}/__init__.py": "",
    "examples/{name}/run.py": '''"""SDR vertical: {description}.

Scaffold only — wire your actual lead source + email sender. Skill autosynth
will improve the email-drafting skill over time once you have outcome data
(replies, meetings booked).
"""
from __future__ import annotations
import asyncio

from forge import (
    AgentDef, AgentLoop, HookBus, SkillStore, Telemetry, ToolRegistry,
    attach_healing, load_profile,
)
from forge.providers.mock import MockProvider


async def main() -> None:
    hooks = HookBus()
    Telemetry(path=".forge/{name}/telemetry.jsonl").attach(hooks)
    attach_healing(hooks)

    # Skills — populate runs.jsonl as you actually send emails.
    SkillStore(root=".forge/{name}/skills")

    tools = ToolRegistry()
    # TODO: register your CRM, email-sender, calendar tools here.

    agent = AgentDef(name="{name}-sdr",
                     instructions="You are an SDR for {name}. {description}.",
                     profile="anthropic-haiku")
    provider = MockProvider.scripted(load_profile("mock"), [])

    loop = AgentLoop(agent=agent, provider=provider, tools=tools, hooks=hooks)
    print(await loop.run("Draft 3 outbound messages for today."))


if __name__ == "__main__":
    asyncio.run(main())
''',
}
