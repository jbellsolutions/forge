"""Embedder factory + plug-in to ReasoningBank/SkillSearchIndex."""
from __future__ import annotations

import pytest

from forge.memory.embeddings import hash_embedder, make_embedder
from forge.memory import ReasoningBank
from forge.skills import SkillStore, SkillSearchIndex


def test_hash_embedder_is_deterministic():
    e = hash_embedder()
    a = e("hello world")
    b = e("hello world")
    assert a == b
    assert len(a) == 256
    # Different texts produce different vectors
    c = e("totally different content here")
    assert a != c


def test_make_embedder_factory():
    e = make_embedder("hash")
    v = e("test")
    assert isinstance(v, list) and len(v) > 0
    with pytest.raises(ValueError):
        make_embedder("not-a-real-embedder")


def test_reasoning_bank_uses_injected_embedder(tmp_path):
    e = hash_embedder(dim=128)
    bank = ReasoningBank(path=tmp_path / "rb.json", embedder=e)
    m = bank.distill("test memory")
    bank.consolidate(m)
    assert len(bank._mems[m.id].embedding) == 128


def test_skill_search_uses_injected_embedder(tmp_path):
    store = SkillStore(tmp_path / "skills")
    store.write_skill("s1", "skill body", version="v1")
    idx = SkillSearchIndex(store, embedder=hash_embedder(dim=64))
    hits = idx.search("body", k=1)
    assert hits and hits[0].name == "s1"
