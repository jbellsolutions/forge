"""Mock provider for tests + smoke-runs without an API key.

Scriptable: pass a sequence of canned AssistantTurns; the provider replays them.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

from ..kernel.profile import ProviderProfile
from ..kernel.types import AssistantTurn, Message, ToolCall
from .base import Provider


class MockProvider(Provider):
    """Replays scripted turns. Use `MockProvider.scripted([...])` to construct."""

    def __init__(self, profile: ProviderProfile, script: list[AssistantTurn] | None = None) -> None:
        super().__init__(profile)
        self._script: Iterator[AssistantTurn] = iter(script or [])

    @classmethod
    def scripted(cls, profile: ProviderProfile, script: list[AssistantTurn]) -> MockProvider:
        return cls(profile, script)

    @classmethod
    def echo_then_done(cls, profile: ProviderProfile, message: str = "hello forge") -> MockProvider:
        """Convenience: turn 1 calls echo(message); turn 2 returns final text."""
        tc = ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name="echo", arguments={"text": message})
        script = [
            AssistantTurn(text="", tool_calls=[tc], usage={"input_tokens": 10, "output_tokens": 5}),
            AssistantTurn(text=f"echoed: {message}", tool_calls=[], usage={"input_tokens": 12, "output_tokens": 6}),
        ]
        return cls(profile, script)

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
    ) -> AssistantTurn:
        try:
            return next(self._script)
        except StopIteration:
            return AssistantTurn(text="(mock script exhausted)", tool_calls=[],
                                 usage={"input_tokens": 0, "output_tokens": 0})
