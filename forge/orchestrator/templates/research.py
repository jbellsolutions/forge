"""Research template — vertical with web tools + intel pipeline access."""
from __future__ import annotations

FILES: dict[str, str] = {
    "examples/{name}/__init__.py": "",
    "examples/{name}/run.py": '''"""Research vertical: {description}.

Spawns a sub-agent with web_search + web_fetch enabled and the AutoAgent
regularizer in its system prompt. Use as a starting point for any
research-style use case.
"""
from __future__ import annotations
import asyncio

from forge import (
    AgentDef, AgentLoop, HookBus, Telemetry, ToolRegistry,
    WebFetchTool, WebSearchTool, attach_healing, load_profile,
)
from forge.providers import make_provider


SYSTEM = """\\
You are the {name} research agent. {description}.

Method:
- Search the web for relevant signals (web_search).
- Fetch top results (web_fetch) to confirm.
- Apply the AutoAgent regularizer: only surface findings that would still
  matter if THIS specific question vanished.
"""


async def main() -> None:
    hooks = HookBus()
    Telemetry(path=".forge/{name}/telemetry.jsonl").attach(hooks)
    attach_healing(hooks)

    tools = ToolRegistry()
    tools.register(WebSearchTool())
    tools.register(WebFetchTool())

    agent = AgentDef(name="{name}", instructions=SYSTEM, profile="anthropic-haiku")
    provider = make_provider("anthropic-haiku")

    loop = AgentLoop(agent=agent, provider=provider, tools=tools, hooks=hooks,
                     max_turns=8)
    result = await loop.run("Investigate today's signals.")
    print(result.final_text)


if __name__ == "__main__":
    asyncio.run(main())
''',
}
