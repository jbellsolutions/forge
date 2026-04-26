"""Operator template — minimal mock vertical, mirrors examples/operator/."""
from __future__ import annotations

FILES: dict[str, str] = {
    "examples/{name}/__init__.py": "",
    "examples/{name}/run.py": '''"""Operator: {description}.

Run with: python examples/{name}/run.py
"""
from __future__ import annotations
import asyncio

from forge import (
    AgentDef, AgentLoop, HookBus, Telemetry, ToolRegistry, load_profile,
    attach_healing,
)
from forge.providers.mock import MockProvider
from forge.tools.builtin.echo import EchoTool


async def main() -> None:
    hooks = HookBus()
    Telemetry(path=".forge/{name}/telemetry.jsonl").attach(hooks)
    attach_healing(hooks)

    tools = ToolRegistry()
    tools.register(EchoTool())

    agent = AgentDef(name="{name}", instructions="You are the {name} operator.",
                     profile="mock")
    profile = load_profile("mock")
    provider = MockProvider.scripted(profile, [])

    loop = AgentLoop(agent=agent, provider=provider, tools=tools, hooks=hooks)
    result = await loop.run("Hello {name}.")
    print(f"[{name}] {{result.final_text}}")


if __name__ == "__main__":
    asyncio.run(main())
''',
    "examples/{name}/heartbeats/morning.md": """---
schedule: "0 9 * * *"
agent: {name}
---

# Morning brief for {name}

{description}.
""",
}
