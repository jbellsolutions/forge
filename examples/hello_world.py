"""Phase 0 smoke: kernel + hook bus + provider profile + 1 tool, end-to-end.

    python examples/hello_world.py                          # mock provider
    python examples/hello_world.py --provider anthropic     # real Anthropic call
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running without install
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forge.kernel import AgentDef, AgentLoop, HookBus, HookContext, PermissionMode
from forge.observability import TraceStore
from forge.providers import make_provider
from forge.providers.mock import MockProvider
from forge.providers import load_profile
from forge.tools import ToolRegistry
from forge.tools.builtin.echo import EchoTool


async def main(provider_name: str) -> int:
    # Tools
    tools = ToolRegistry()
    tools.register(EchoTool())

    # Hooks: trace every event + a demo pre-tool gate
    hooks = HookBus()
    trace = TraceStore(root=".forge/traces")
    trace.attach(hooks)

    @hooks.on_pre_tool
    def _gate(ctx: HookContext) -> None:
        if ctx.tool_call and "DROP TABLE" in str(ctx.tool_call.arguments).upper():
            ctx.block("destructive SQL detected")

    # Provider
    profile = load_profile(provider_name)
    if profile.vendor == "mock":
        provider = MockProvider.echo_then_done(profile, message="hello forge")
    else:
        provider = make_provider(provider_name)

    # Agent
    agent = AgentDef(
        name="hello-agent",
        instructions=(
            "You are a smoke-test agent. Use the `echo` tool exactly once with "
            "the text 'hello forge', then reply with the echoed result."
        ),
        profile=provider_name,
        permission_mode=PermissionMode.AUTO,
    )

    loop = AgentLoop(agent, provider, tools, hooks=hooks, max_turns=4)
    result = await loop.run("Say hello via the echo tool.")

    print("=" * 60)
    print(f"final: {result.final_text!r}")
    print(f"turns: {result.turns}  usage: {result.usage}")
    if result.halted_reason:
        print(f"halted: {result.halted_reason}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--provider", default="mock", help="profile name (mock | anthropic)")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.provider)))
