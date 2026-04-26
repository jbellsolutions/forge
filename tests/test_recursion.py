"""Phase 9 — recursive self-modification."""
from __future__ import annotations

import json
from pathlib import Path

from forge.recursion import HarnessDiff, TraceAnalyzer, apply, fork, keep_or_rollback, propose


def _write_session(traces: Path, sid: str, errors: int, blocks: int):
    sd = traces / sid
    sd.mkdir(parents=True, exist_ok=True)
    with (sd / "tool_calls.jsonl").open("w") as f:
        for i in range(errors):
            f.write(json.dumps({"phase": "post", "name": "bad", "is_error": True}) + "\n")
        for i in range(blocks):
            f.write(json.dumps({"phase": "pre", "name": "blocked_tool", "verdict": "blocked"}) + "\n")


def test_analyzer_extracts_symptoms(tmp_path: Path):
    _write_session(tmp_path / "traces", "s1", errors=6, blocks=3)
    sx = TraceAnalyzer(tmp_path / "traces").symptoms()
    assert sx["tool_errors"]["bad"] == 6
    assert sx["blocks"]["blocked_tool"] == 3


def test_propose_generates_diffs_above_threshold(tmp_path: Path):
    diffs = propose({"tool_errors": {"bad": 6}, "blocks": {"x": 4}})
    assert any(d.op == "retune_circuit" for d in diffs)
    assert any(d.op == "deny_tool" for d in diffs)


def test_apply_retune_circuit_writes_json(tmp_path: Path):
    diff = HarnessDiff(
        rationale="x", target=".forge/healing/circuits.json", op="retune_circuit",
        payload={"tool": "bad", "fail_threshold": 2, "cooldown_seconds": 10},
    )
    assert apply(diff, tmp_path)
    data = json.loads((tmp_path / ".forge/healing/circuits.json").read_text())
    assert data["bad"]["fail_threshold"] == 2


def test_keep_or_rollback_threshold():
    assert keep_or_rollback(0.5, 0.6, margin=0.05) is True
    assert keep_or_rollback(0.5, 0.52, margin=0.05) is False


def test_fork_copies_directory(tmp_path: Path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "a.txt").write_text("hello")
    cand = fork(base, suffix="cand")
    assert (cand / "a.txt").read_text() == "hello"
    # second fork overwrites
    (base / "a.txt").write_text("hello-2")
    cand2 = fork(base, suffix="cand")
    assert (cand2 / "a.txt").read_text() == "hello-2"
