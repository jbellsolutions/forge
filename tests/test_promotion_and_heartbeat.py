"""Memory promotion + heartbeat runner."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from forge.memory import ObsidianVault, ReasoningBank, promote
from forge.scheduler.heartbeat import run_all, run_one


def test_promote_writes_topic_for_high_confidence(tmp_path: Path):
    vault = ObsidianVault(tmp_path / "vault")
    bank = ReasoningBank(path=tmp_path / "rb.json")
    m = bank.distill("Critical learning about shipping on Fridays.", tags=["shipping"])
    bank.consolidate(m)
    # bump confidence + use count past thresholds
    bank.judge(m.id, +1.0)
    bank.judge(m.id, +1.0)
    bank.judge(m.id, +1.0)
    res = promote(bank, vault, threshold=0.6, min_used=2)
    assert m.id in res.promoted
    topic = vault.root / "topics"
    md_files = list(topic.glob("*.md"))
    assert md_files, "expected at least one promoted topic note"


def test_promote_idempotent_updates_existing(tmp_path: Path):
    vault = ObsidianVault(tmp_path / "vault")
    bank = ReasoningBank(path=tmp_path / "rb.json")
    m = bank.distill("Topic A", tags=["t"])
    bank.consolidate(m)
    for _ in range(3):
        bank.judge(m.id, +1.0)
    promote(bank, vault, threshold=0.6, min_used=2)
    res2 = promote(bank, vault, threshold=0.6, min_used=2)
    # On second call the same memory should be in `updated`, not `promoted`.
    assert m.id in res2.updated


def test_promote_skips_low_confidence(tmp_path: Path):
    vault = ObsidianVault(tmp_path / "vault")
    bank = ReasoningBank(path=tmp_path / "rb.json")
    m = bank.distill("Low-confidence noise")
    bank.consolidate(m)
    res = promote(bank, vault, threshold=0.9, min_used=10)
    assert res.promoted == [] and res.skipped >= 1


@pytest.mark.asyncio
async def test_heartbeat_run_one_logs_ok(tmp_path: Path):
    hb = tmp_path / "hb.md"
    hb.write_text("---\nschedule: ad-hoc\n---\n# Test heartbeat\nbody\n")
    record = await run_one(hb, log_dir=tmp_path / "logs")
    assert record["heartbeat"] == "hb"
    # No `agent` declared -> note-only path
    assert record["returncode"] == 0
    assert "logs" in str(list((tmp_path / "logs").iterdir())[0])


@pytest.mark.asyncio
async def test_heartbeat_run_all_no_files_returns_zero(tmp_path: Path):
    rc = await run_all(tmp_path)
    assert rc == 0
