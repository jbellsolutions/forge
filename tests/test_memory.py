"""Phase 5 — memory."""
from __future__ import annotations

from pathlib import Path

import pytest

from forge.memory import ClaudeDir, GitJournal, ReasoningBank


def test_claude_dir_bootstraps_layout(tmp_path: Path):
    cd = ClaudeDir(tmp_path / ".claude")
    assert (tmp_path / ".claude" / "GENOME.md").exists()
    assert (tmp_path / ".claude" / "MEMORY.md").exists()
    for sub in ("agents", "skills", "personas", "healing", "learning", "security"):
        assert (tmp_path / ".claude" / sub).is_dir()
    assert (tmp_path / ".claude" / "healing" / "circuits.json").exists()


def test_claude_dir_appends_observation(tmp_path: Path):
    import json
    cd = ClaudeDir(tmp_path / ".claude")
    cd.append_observation({"event": "test", "v": 1})
    cd.append_observation({"event": "test", "v": 2})
    obs = json.loads((tmp_path / ".claude" / "learning" / "observations.json").read_text())
    assert len(obs) == 2 and obs[1]["v"] == 2


def test_reasoning_bank_distill_consolidate_retrieve(tmp_path: Path):
    bank = ReasoningBank(path=tmp_path / "rb.json")
    m1 = bank.distill("council voted ship on shipping today", tags=["decision"])
    m2 = bank.distill("council voted wait on hiring loop", tags=["decision"])
    bank.consolidate(m1)
    bank.consolidate(m2)
    hits = bank.retrieve("shipping decision", k=2, min_confidence=0.0)
    assert hits, "expected retrieval hits"
    # The shipping memory should rank above the hiring memory
    assert "shipping" in hits[0].text


def test_reasoning_bank_judge_updates_confidence(tmp_path: Path):
    bank = ReasoningBank(path=tmp_path / "rb.json")
    m = bank.distill("test memory")
    bank.consolidate(m)
    initial = bank._mems[m.id].confidence
    bank.judge(m.id, +1.0)
    assert bank._mems[m.id].confidence > initial


def test_git_journal_init_and_checkpoint(tmp_path: Path):
    j = GitJournal(tmp_path / "journal")
    (tmp_path / "journal" / "note.md").write_text("hello")
    sha = j.checkpoint("add note")
    assert sha and len(sha) == 40
    log = j.log(2)
    assert "add note" in log
