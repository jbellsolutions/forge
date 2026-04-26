"""Agent loop. The L0 kernel.

Flow per turn:
  1. Provider.generate(messages, tools) -> AssistantTurn
  2. For each tool_call:
     a. fire pre-tool hooks; check verdict
     b. if READY/WARNING: registry.execute(tool_call) -> ToolResult
     c. if BLOCKED: synthesize a refusal ToolResult
     d. fire post-tool hooks (may rewrite result)
     e. append tool result to messages
  3. If no tool calls, return final assistant text.

Stops on: no more tool calls, max_turns reached, or BLOCKED verdict with halt-on-block=True.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from ..providers.base import Provider
from ..tools.registry import ToolRegistry
from .hooks import HookBus, HookContext
from .types import AgentDef, AssistantTurn, Message, ToolCall, ToolResult, Verdict

log = logging.getLogger("forge.loop")


@dataclass
class LoopResult:
    final_text: str
    messages: list[Message]
    turns: int
    usage: dict[str, int] = field(default_factory=dict)
    halted_reason: str | None = None


class AgentLoop:
    def __init__(
        self,
        agent: AgentDef,
        provider: Provider,
        tools: ToolRegistry,
        hooks: HookBus | None = None,
        max_turns: int = 10,
    ) -> None:
        self.agent = agent
        self.provider = provider
        self.tools = tools
        self.hooks = hooks or HookBus()
        self.max_turns = max_turns

    async def run(self, user_input: str, session_id: str | None = None) -> LoopResult:
        sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        ctx = HookContext(session_id=sid, agent_name=self.agent.name)
        await self.hooks.fire_session_start(ctx)

        messages: list[Message] = [
            Message(role="system", content=self.agent.instructions),
            Message(role="user", content=user_input),
        ]
        usage_total = {"input_tokens": 0, "output_tokens": 0}
        halted_reason: str | None = None

        turn = 0
        for turn in range(1, self.max_turns + 1):
            tool_schemas = self.tools.schemas_for(self.agent)
            assistant_turn: AssistantTurn = await self.provider.generate(
                messages=messages,
                tools=tool_schemas,
                max_tokens=4096,
            )
            usage_total["input_tokens"] += assistant_turn.usage.get("input_tokens", 0)
            usage_total["output_tokens"] += assistant_turn.usage.get("output_tokens", 0)

            messages.append(Message(role="assistant", content=assistant_turn.text or "",
                                    metadata={"raw_tool_calls": [tc.__dict__ for tc in assistant_turn.tool_calls]}))

            if not assistant_turn.tool_calls:
                # Final answer.
                break

            for tc in assistant_turn.tool_calls:
                tool_ctx = HookContext(
                    session_id=sid, agent_name=self.agent.name, tool_call=tc,
                )
                verdict = await self.hooks.fire_pre_tool(tool_ctx)

                if verdict == Verdict.BLOCKED:
                    result = ToolResult(
                        tool_call_id=tc.id, name=tc.name,
                        content=f"BLOCKED by hook: {'; '.join(tool_ctx.notes) or 'no reason'}",
                        is_error=True,
                    )
                else:
                    try:
                        result = await self.tools.execute(tc, agent=self.agent)
                    except Exception as e:  # noqa: BLE001
                        log.exception("tool %s raised", tc.name)
                        result = ToolResult(
                            tool_call_id=tc.id, name=tc.name,
                            content=f"ERROR: {type(e).__name__}: {e}",
                            is_error=True,
                        )

                tool_ctx.tool_result = result
                await self.hooks.fire_post_tool(tool_ctx)
                # Post-hook may have replaced the result.
                result = tool_ctx.tool_result or result

                messages.append(Message(
                    role="tool", content=result.content, name=result.name,
                    tool_call_id=result.tool_call_id,
                    metadata={"is_error": result.is_error, **result.metadata},
                ))
        else:
            halted_reason = f"max_turns reached ({self.max_turns})"

        # Extract last assistant text as final answer.
        final_text = ""
        for m in reversed(messages):
            if m.role == "assistant":
                final_text = m.content if isinstance(m.content, str) else ""
                break

        end_ctx = HookContext(session_id=sid, agent_name=self.agent.name,
                              extra={"messages": messages, "usage": usage_total})
        await self.hooks.fire_session_end(end_ctx)

        return LoopResult(
            final_text=final_text, messages=messages, turns=turn,
            usage=usage_total, halted_reason=halted_reason,
        )
