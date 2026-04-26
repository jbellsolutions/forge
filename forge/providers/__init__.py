"""Provider adapters. Vendor SDKs imported lazily by concrete classes."""
from __future__ import annotations

from ..kernel.profile import ProviderProfile, load_profile
from .base import Provider
from .mock import MockProvider


def make_provider(profile_name: str, **kwargs) -> Provider:
    """Factory: load profile by name, return matching adapter."""
    profile = load_profile(profile_name)
    vendor = profile.vendor
    if vendor == "mock":
        return MockProvider(profile, **kwargs)
    if vendor == "anthropic":
        from .anthropic import AnthropicProvider
        return AnthropicProvider(profile, **kwargs)
    if vendor == "openai_compat":
        from .openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(profile, **kwargs)
    raise ValueError(f"unknown vendor {vendor!r} in profile {profile_name!r}")


__all__ = ["Provider", "MockProvider", "ProviderProfile", "load_profile", "make_provider"]
