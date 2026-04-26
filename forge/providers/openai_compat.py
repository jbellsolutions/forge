"""OpenAI-compatible provider. Works with any endpoint speaking the Chat Completions API:
- OpenAI proper
- OpenRouter (DeepSeek, Llama, Mistral, etc.)
- Ollama (local)
- Together, Groq, Fireworks, etc.

Profile.extra controls base_url and auth strategy.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

from ..kernel.profile import ProviderProfile
from ..kernel.types import AssistantTurn, Message, ToolCall
from .base import Provider


class OpenAICompatProvider(Provider):
    def __init__(self, profile: ProviderProfile, api_key: str | None = None) -> None:
        super().__init__(profile)
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as e:
            raise ImportError(
                "openai SDK not installed. `pip install forge[openai]`"
            ) from e
        extra = profile.extra or {}
        base_url = extra.get("base_url")
        env_key = extra.get("api_key_env", "OPENAI_API_KEY")
        key = api_key or os.getenv(env_key) or "ollama-no-key"
        kwargs: dict[str, Any] = {"api_key": key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
    ) -> AssistantTurn:
        oa_msgs = _to_openai(messages)
        oa_tools = [_tool_to_openai(t) for t in tools] if tools else None

        kwargs: dict[str, Any] = {
            "model": self.profile.model,
            "messages": oa_msgs,
            "max_tokens": max_tokens,
            "temperature": self.profile.temperature,
        }
        if oa_tools:
            kwargs["tools"] = oa_tools
            kwargs["tool_choice"] = "auto"

        resp = await asyncio.to_thread(self._client.chat.completions.create, **kwargs)
        choice = resp.choices[0].message

        tool_calls: list[ToolCall] = []
        for tc in choice.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        usage = {
            "input_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(resp.usage, "completion_tokens", 0) or 0,
        }
        return AssistantTurn(
            text=choice.content or "",
            tool_calls=tool_calls,
            raw={"id": resp.id, "finish_reason": resp.choices[0].finish_reason},
            usage=usage,
        )


def _to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            out.append({"role": "system", "content": m.content if isinstance(m.content, str) else str(m.content)})
        elif m.role == "user":
            out.append({"role": "user", "content": m.content if isinstance(m.content, str) else str(m.content)})
        elif m.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": m.content if isinstance(m.content, str) else ""}
            tcs = m.metadata.get("raw_tool_calls", []) or []
            if tcs:
                entry["tool_calls"] = [{
                    "id": tc.get("id"),
                    "type": "function",
                    "function": {"name": tc.get("name"), "arguments": json.dumps(tc.get("arguments", {}))},
                } for tc in tcs]
            out.append(entry)
        elif m.role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": m.tool_call_id,
                "content": m.content if isinstance(m.content, str) else str(m.content),
            })
    return out


def _tool_to_openai(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": schema["name"],
            "description": schema.get("description", ""),
            "parameters": schema.get("parameters", {"type": "object", "properties": {}}),
        },
    }
