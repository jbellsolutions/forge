"""Provider abstract base. Vendor SDKs are imported only by concrete subclasses."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..kernel.profile import ProviderProfile
from ..kernel.types import AssistantTurn, Message


class Provider(ABC):
    def __init__(self, profile: ProviderProfile) -> None:
        self.profile = profile

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
    ) -> AssistantTurn:
        """Run one model call and return an AssistantTurn (text + tool_calls + usage)."""
        ...
