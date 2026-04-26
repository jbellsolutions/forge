"""Custom template — empty stub the user (or orchestrator) fills in."""
from __future__ import annotations

FILES: dict[str, str] = {
    "examples/{name}/__init__.py": "",
    "examples/{name}/run.py": '''"""Custom vertical: {description}.

Fill in tool registry + agent definition + orchestration to taste.
"""
from __future__ import annotations
import asyncio

from forge import AgentLoop, HookBus, ToolRegistry
# TODO: import your provider, tools, agent definition.


async def main() -> None:
    hooks = HookBus()
    tools = ToolRegistry()
    # agent = AgentDef(name="{name}", instructions="...", profile="...")
    # provider = make_provider("...")
    # loop = AgentLoop(agent=agent, provider=provider, tools=tools, hooks=hooks)
    # print(await loop.run("Your kick-off message."))
    print("[{name}] custom scaffold — fill me in.")


if __name__ == "__main__":
    asyncio.run(main())
''',
    "examples/{name}/README.md": """# {name}

{description}

## Notes
- Fill in tools, provider, and the kick-off prompt in `run.py`.
- Add a heartbeat under `examples/{name}/heartbeats/*.md` if scheduled.
""",
}
