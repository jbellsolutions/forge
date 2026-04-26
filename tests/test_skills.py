"""Phase 6 — skills."""
from __future__ import annotations

from pathlib import Path

from forge.skills import (
    SkillRun, SkillSearchIndex, SkillStore,
    autosynth, default_proposer, evaluate, promote_if_passing,
)


def _seed_runs(store: SkillStore, name: str, version: str, n: int, score: float):
    for i in range(n):
        store.log_run(SkillRun(
            skill=name, version=version,
            input_hash=SkillStore.hash_input(f"in_{i}"),
            output=f"out_{i}", outcome_score=score,
        ))


def test_skill_store_versioning(tmp_path: Path):
    store = SkillStore(tmp_path / "skills")
    store.write_skill("decide", "v1 body", version="v1")
    assert store.current_version("decide") == "v1"
    store.write_skill("decide", "v2 body", version="v2")
    assert store.current_version("decide") == "v1"
    store.set_current("decide", "v2")
    assert store.read_skill("decide") == "v2 body"
    assert sorted(store.versions("decide")) == ["v1", "v2"]


def test_eval_gate_blocks_below_min_samples(tmp_path: Path):
    store = SkillStore(tmp_path / "skills")
    store.write_skill("d", "v1", version="v1")
    store.write_skill("d", "v2", version="v2")
    _seed_runs(store, "d", "v1", 60, 0.4)
    _seed_runs(store, "d", "v2", 5, 0.9)
    r = evaluate(store, "d", "v2")
    assert not r.promoted
    assert "insufficient" in r.reason


def test_eval_gate_blocks_below_margin(tmp_path: Path):
    store = SkillStore(tmp_path / "skills")
    store.write_skill("d", "v1", version="v1")
    store.write_skill("d", "v2", version="v2")
    _seed_runs(store, "d", "v1", 60, 0.50)
    _seed_runs(store, "d", "v2", 60, 0.51)  # margin 0.01 < 0.05
    r = evaluate(store, "d", "v2")
    assert not r.promoted
    assert "margin" in r.reason


def test_eval_gate_promotes_when_margin_clears(tmp_path: Path):
    store = SkillStore(tmp_path / "skills")
    store.write_skill("d", "v1", version="v1")
    store.write_skill("d", "v2", version="v2")
    _seed_runs(store, "d", "v1", 60, 0.40)
    _seed_runs(store, "d", "v2", 60, 0.55)  # margin 0.15 > 0.05
    r = promote_if_passing(store, "d", "v2")
    assert r.promoted
    assert store.current_version("d") == "v2"


def test_autosynth_writes_new_version(tmp_path: Path):
    store = SkillStore(tmp_path / "skills")
    store.write_skill("d", "# d\n", version="v1")
    _seed_runs(store, "d", "v1", 20, 0.7)
    res = autosynth(store, "d", proposer=default_proposer, min_runs=10)
    assert res is not None and res.new_version == "v2"
    assert "Lessons learned" in store.read_skill("d", "v2")


def test_skill_search_returns_matching_skill(tmp_path: Path):
    store = SkillStore(tmp_path / "skills")
    store.write_skill("notion_brief", "# notion brief skill", version="v1")
    store.write_skill("daily_decision", "# daily decision skill", version="v1")
    idx = SkillSearchIndex(store)
    hits = idx.search("decision", k=2)
    assert hits and hits[0].name == "daily_decision"
