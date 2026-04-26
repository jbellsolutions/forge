"""Phase 1 — provider profile loading + factory."""
from __future__ import annotations

from forge.providers import load_profile, make_provider
from forge.providers.base import Provider


def test_loads_known_profiles():
    for name in ("mock", "anthropic", "anthropic-haiku",
                 "openrouter-deepseek", "openai-gpt4", "ollama-llama3"):
        p = load_profile(name)
        assert p.name == name
        assert p.vendor in {"mock", "anthropic", "openai_compat"}


def test_factory_returns_provider_for_mock():
    p = make_provider("mock")
    assert isinstance(p, Provider)


def test_unknown_vendor_raises(tmp_path):
    import pytest
    from pathlib import Path
    from forge.kernel.profile import ProviderProfile

    bogus = ProviderProfile(name="bogus", vendor="fake", model="x")
    fake_dir = tmp_path / "p"
    fake_dir.mkdir()
    import yaml
    (fake_dir / "bogus.yaml").write_text(yaml.dump({"name": "bogus", "vendor": "fake", "model": "x"}))
    # Patch search path
    from forge.kernel import profile as prof_mod
    orig_search = prof_mod.load_profile
    def patched(name):
        return ProviderProfile.from_yaml(fake_dir / f"{name}.yaml")
    # Monkeypatch via direct import in factory:
    import forge.providers as providers_mod
    real_load = providers_mod.load_profile
    providers_mod.load_profile = patched
    try:
        with pytest.raises(ValueError):
            providers_mod.make_provider("bogus")
    finally:
        providers_mod.load_profile = real_load
