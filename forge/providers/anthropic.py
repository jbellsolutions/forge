"""Anthropic adapter. Translates Forge messages/tools <-> Anthropic Messages API."""
from __future__ import annotations

import os
import uuid
from typing import Any

from ..kernel.profile import ProviderProfile
from ..kernel.types import AssistantTurn, Message, ToolCall
from .base import Provider


class AnthropicProvider(Provider):
    def __init__(self, profile: ProviderProfile, api_key: str | None = None) -> None:
        super().__init__(profile)
        try:
            import anthropic  # type: ignore
        except ImportError as e:
            raise ImportError(
                "anthropic SDK not installed. `pip install forge[anthropic]`"
            ) from e
        self._client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
    ) -> AssistantTurn:
        system, anth_messages = _to_anthropic(messages)
        anth_tools = [_tool_to_anthropic(t) for t in tools] if tools else []

        kwargs: dict[str, Any] = {
            "model": self.profile.model,
            "max_tokens": max_tokens,
            "messages": anth_messages,
        }
        if system:
            kwargs["system"] = system
        if anth_tools:
            kwargs["tools"] = anth_tools

        # SDK is sync; run in threadpool to keep loop responsive.
        import asyncio
        resp = await asyncio.to_thread(self._client.messages.create, **kwargs)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)
            elif getattr(block, "type", None) == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id, name=block.name, arguments=dict(block.input or {}),
                ))

        usage = {
            "input_tokens": getattr(resp.usage, "input_tokens", 0),
            "output_tokens": getattr(resp.usage, "output_tokens", 0),
        }
        return AssistantTurn(
            text="".join(text_parts), tool_calls=tool_calls,
            raw={"id": resp.id, "stop_reason": resp.stop_reason}, usage=usage,
        )


def _to_anthropic(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Forge messages -> (system_text, anthropic message list)."""
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    def flush_pending() -> None:
        nonlocal pending_tool_results
        if pending_tool_results:
            out.append({"role": "user", "content": pending_tool_results})
            pending_tool_results = []

    for m in messages:
        if m.role == "system":
            if isinstance(m.content, str):
                system_parts.append(m.content)
            continue

        if m.role == "tool":
            pending_tool_results.append({
                "type": "tool_result",
                "tool_use_id": m.tool_call_id or "",
                "content": m.content if isinstance(m.content, str) else str(m.content),
                "is_error": bool(m.metadata.get("is_error", False)),
            })
            continue

        flush_pending()

        if m.role == "user":
            out.append({"role": "user", "content": m.content if isinstance(m.content, str) else m.content})
        elif m.role == "assistant":
            blocks: list[dict[str, Any]] = []
            if isinstance(m.content, str) and m.content:
                blocks.append({"type": "text", "text": m.content})
            for tc in m.metadata.get("raw_tool_calls", []) or []:
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id"), "name": tc.get("name"),
                    "input": tc.get("arguments", {}),
                })
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})

    flush_pending()
    return "\n".join(system_parts), out


def _tool_to_anthropic(schema: dict[str, Any]) -> dict[str, Any]:
    """Forge tool schema -> Anthropic tool spec.

    Forge schema: {name, description, parameters: <JSONSchema>}
    Anthropic:    {name, description, input_schema: <JSONSchema>}
    """
    return {
        "name": schema["name"],
        "description": schema.get("description", ""),
        "input_schema": schema.get("parameters", {"type": "object", "properties": {}}),
    }
