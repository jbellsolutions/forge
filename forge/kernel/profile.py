"""Provider-as-profile loader.

A profile is a YAML file declaring how to talk to a model: vendor, model id,
prompt format, tool-call protocol, max tokens, cost tier, failover chain.
The kernel never imports a vendor SDK directly — only the adapter listed in
the profile does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ProviderProfile:
    name: str
    vendor: str             # "anthropic" | "openai" | "deepseek" | "ollama" | "mock"
    model: str              # e.g. "claude-opus-4-5-20250101"
    max_tokens: int = 4096
    temperature: float = 0.7
    cost_tier: str = "premium"   # "free" | "cheap" | "balanced" | "premium"
    failover: list[str] = field(default_factory=list)  # ordered list of profile names
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> ProviderProfile:
        path = Path(path)
        data = yaml.safe_load(path.read_text())
        return cls(
            name=data["name"],
            vendor=data["vendor"],
            model=data["model"],
            max_tokens=data.get("max_tokens", 4096),
            temperature=data.get("temperature", 0.7),
            cost_tier=data.get("cost_tier", "premium"),
            failover=data.get("failover", []),
            extra=data.get("extra", {}),
        )


def load_profile(name: str, search_paths: list[Path] | None = None) -> ProviderProfile:
    """Load a profile by name. Searches forge/providers/profiles/ by default."""
    search_paths = search_paths or [
        Path(__file__).parent.parent / "providers" / "profiles",
    ]
    for p in search_paths:
        candidate = p / f"{name}.yaml"
        if candidate.exists():
            return ProviderProfile.from_yaml(candidate)
    raise FileNotFoundError(f"profile {name!r} not found in {search_paths}")
