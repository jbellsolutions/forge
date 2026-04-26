"""Phase B — recursion orchestrator end-to-end with mock provider."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.kernel.types import AssistantTurn
from forge.providers import load_profile
from forge.providers.mock import MockProvider
from forge.recursion import recurse_once


def _plant_traces(home: Path) -> None:
    sd = home / "traces" / "s1"
    sd.mkdir(parents=True)
    with (sd / "tool_calls.jsonl").open("w") as f:
        for _ in range(6):
            f.write(json.dumps({"phase": "post", "name": "bad", "is_error": True}) + "\n")


@pytest.mark.asyncio
async def test_recurse_once_keeps_when_candidate_improves(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    _plant_traces(home)

    profile = load_profile("mock")
    canned = AssistantTurn(
        text='[{"rationale":"bad fails 6x","target":".forge/healing/circuits.json",'
             '"op":"retune_circuit","payload":{"tool":"bad","fail_threshold":2,"cooldown_seconds":600}}]',
        tool_calls=[], usage={"input_tokens": 1, "output_tokens": 1},
    )
    provider = MockProvider.scripted(profile, [canned])

    def score_fn(p: Path) -> float:
        circuits = p / ".forge" / "healing" / "circuits.json"
        if not circuits.exists():
            return 0.0
        data = json.loads(circuits.read_text())
        return 1.0 if "bad" in data else 0.0

    result = await recurse_once(home, provider, score_fn)
    assert result.kept is True
    assert result.applied
    # After promotion, home should now have the candidate's circuits.json
    assert (home / ".forge" / "healing" / "circuits.json").exists()
    # Ledger row written
    ledger = home / "results.tsv"
    assert ledger.exists()
    rows = ledger.read_text().splitlines()
    assert len(rows) >= 2  # header + 1 row


@pytest.mark.asyncio
async def test_recurse_once_rollback_when_no_diffs(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    _plant_traces(home)

    profile = load_profile("mock")
    canned = AssistantTurn(text="[]", tool_calls=[], usage={"input_tokens": 1, "output_tokens": 1})
    provider = MockProvider.scripted(profile, [canned])

    def score_fn(p: Path) -> float:
        return 0.0

    result = await recurse_once(home, provider, score_fn)
    assert result.kept is False
    assert "no diffs" in result.notes
