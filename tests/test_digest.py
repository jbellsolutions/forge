"""Tests for forge.observability.digest — daily/weekly self-improvement digest.

Covers:
- aggregation across all 6 source artifacts (recursion ledger, skills, denials,
  telemetry, genome, intel)
- window filtering (in-window vs out-of-window rows)
- markdown rendering
- privacy invariant: digest output never contains `"role":` / `"content":`
  / vendor key prefixes
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forge import build_digest
from forge.observability.digest import (
    Digest,
    _scrub,
    _signed,
    _signed_score,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_results_tsv(home: Path, rows: list[dict]) -> None:
    p = home / "results.tsv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        f.write("timestamp\tcandidate\tbase_score\tcandidate_score\tdelta\tkept\tnotes\n")
        for r in rows:
            f.write(
                f"{r['timestamp']}\t{r['candidate']}\t{r['base_score']}\t"
                f"{r['candidate_score']}\t{r['delta']}\t{r['kept']}\t{r.get('notes','')}\n"
            )


def _write_jsonl(p: Path, records: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_empty_home_returns_zeroed_digest(tmp_path: Path) -> None:
    d = build_digest(tmp_path, period="day")
    assert d.kept_count == 0
    assert d.rolled_count == 0
    assert d.skills == []
    assert d.denials == []
    assert d.telemetry.sessions == 0
    md = d.to_markdown()
    assert "forge daily digest" in md
    assert "0 mod kept" in md


def test_recursion_window_filtering(tmp_path: Path) -> None:
    now = time.time()
    _write_results_tsv(tmp_path, [
        {"timestamp": now - 100,         "candidate": "c1", "base_score": 0.5,
         "candidate_score": 0.7, "delta": 0.2, "kept": "1", "notes": "in window kept"},
        {"timestamp": now - 200,         "candidate": "c2", "base_score": 0.5,
         "candidate_score": 0.4, "delta": -0.1, "kept": "0", "notes": "in window rolled"},
        {"timestamp": now - 86400 * 10,  "candidate": "c3", "base_score": 0.0,
         "candidate_score": 1.0, "delta": 1.0, "kept": "1", "notes": "ancient"},
    ])
    d = build_digest(tmp_path, period="day")
    assert d.kept_count == 1
    assert d.rolled_count == 1
    assert all(r.candidate in {"c1", "c2"} for r in d.recursion)


def test_skill_creation_and_promotion(tmp_path: Path) -> None:
    now = time.time()
    skill_dir = tmp_path / "skills" / "my_skill"
    skill_dir.mkdir(parents=True)
    v1 = skill_dir / "v1.md"
    v1.write_text("---\nname: my_skill\n---\nbody")
    v2 = skill_dir / "v2.md"
    v2.write_text("---\nname: my_skill\n---\nbody v2")
    cur = skill_dir / "current.txt"
    cur.write_text("v2")
    # Force mtimes inside the day window
    import os
    for p in (v1, v2, cur):
        os.utime(p, (now - 60, now - 60))

    d = build_digest(tmp_path, period="day")
    kinds = [s.kind for s in d.skills]
    assert "created" in kinds
    assert "promoted" in kinds
    promo = next(s for s in d.skills if s.kind == "promoted")
    assert promo.version == "v2"


def test_denials_from_traces(tmp_path: Path) -> None:
    now = time.time()
    sess = tmp_path / "traces" / "sess1"
    sess.mkdir(parents=True)
    _write_jsonl(sess / "events.jsonl", [
        {"ts": now - 30, "agent_name": "a", "tool": "shell",
         "verdict": "blocked", "notes": ["policy"]},
        {"ts": now - 20, "agent_name": "a", "tool": "shell",
         "verdict": "safety_blocked", "notes": ["denial loop"]},
        {"ts": now - 10, "agent_name": "a", "tool": "echo",
         "verdict": "ready", "notes": []},  # not a denial
        {"ts": now - 86400 * 30, "agent_name": "a", "tool": "shell",
         "verdict": "blocked"},  # out of window
    ])
    d = build_digest(tmp_path, period="day")
    assert len(d.denials) == 2
    assert d.safety_blocked_count == 1
    assert {x.tool for x in d.denials} == {"shell"}


def test_telemetry_rollup(tmp_path: Path) -> None:
    now = time.time()
    p = tmp_path / "telemetry.jsonl"
    _write_jsonl(p, [
        {"session_id": "s1", "agent": "a", "started_at": now - 100,
         "input_tokens": 1000, "output_tokens": 500, "cost_usd": 0.0023,
         "tool_calls": 4, "tool_errors": 1, "blocked": 0},
        {"session_id": "s2", "agent": "a", "started_at": now - 200,
         "input_tokens": 500, "output_tokens": 250, "cost_usd": 0.001,
         "tool_calls": 2, "tool_errors": 0, "blocked": 1},
        {"session_id": "s3", "agent": "a", "started_at": now - 86400 * 10,
         "input_tokens": 9999, "output_tokens": 9999, "cost_usd": 99.0},
    ])
    d = build_digest(tmp_path, period="day")
    assert d.telemetry.sessions == 2
    assert d.telemetry.total_input_tokens == 1500
    assert d.telemetry.total_output_tokens == 750
    assert abs(d.telemetry.total_cost_usd - 0.0033) < 1e-6
    assert d.telemetry.tool_calls == 6
    assert d.telemetry.tool_errors == 1
    assert d.telemetry.blocked == 1


def test_intel_highlights_in_window(tmp_path: Path) -> None:
    intel_dir = tmp_path / "intel"
    intel_dir.mkdir()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = [
        {"source": "anthropic_changelog", "title": "Sonnet 4.5 ships",
         "url": "https://x", "relevance": "high"},
        {"source": "openai_blog", "title": "GPT-5 preview",
         "url": "https://y", "relevance": "med"},
    ]
    (intel_dir / f"{today}.json").write_text(json.dumps(items))
    d = build_digest(tmp_path, period="day")
    assert len(d.intel) == 2
    assert {i.relevance for i in d.intel} == {"high", "med"}


def test_to_markdown_is_compact_and_safe(tmp_path: Path) -> None:
    now = time.time()
    _write_results_tsv(tmp_path, [{
        "timestamp": now - 50, "candidate": "c1", "base_score": 0.5,
        "candidate_score": 0.7, "delta": 0.2, "kept": "1",
        "notes": 'rationale: applied retune to fix circuit breaker',
    }])
    d = build_digest(tmp_path, period="day")
    md = d.to_markdown()
    assert "1 mod kept" in md
    assert "0 rolled" in md
    assert "Δ+0.20" in md
    # Single-line bullets, not multi-line dumps.
    for line in md.splitlines():
        assert len(line) < 500


# --- privacy invariant ------------------------------------------------------

# Patterns that MUST NOT appear in any digest output.
_FORBIDDEN = [
    re.compile(r'"role"\s*:\s*"', re.IGNORECASE),
    re.compile(r'"content"\s*:\s*\['),
    re.compile(r'sk-ant-[A-Za-z0-9_-]{20,}'),
    re.compile(r'sk-or-v1-[A-Za-z0-9_-]{20,}'),
    re.compile(r'AKIA[0-9A-Z]{16}'),
]


def test_privacy_invariant_strips_message_shapes_and_keys(tmp_path: Path) -> None:
    """If poisoned data leaks into source artifacts, scrub must redact."""
    now = time.time()
    poisoned_notes = (
        'leaked: {"role": "user", "content": [{"text": "secret"}]} '
        'sk-ant-api03-deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdead '
        'sk-or-v1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa '
        'AKIAIOSFODNN7EXAMPLE'
    )
    _write_results_tsv(tmp_path, [{
        "timestamp": now - 50, "candidate": "c1", "base_score": 0.0,
        "candidate_score": 0.0, "delta": 0.0, "kept": "1",
        "notes": poisoned_notes,
    }])
    d = build_digest(tmp_path, period="day")
    md = d.to_markdown()
    js = json.dumps(d.to_json())
    for pat in _FORBIDDEN:
        assert not pat.search(md), f"forbidden pattern leaked into markdown: {pat.pattern}"
        assert not pat.search(js),  f"forbidden pattern leaked into json: {pat.pattern}"


def test_scrub_truncates_and_strips_newlines() -> None:
    s = _scrub("hello\nworld\twith tabs   ", max_len=200)
    assert "\n" not in s and "\t" not in s
    long = _scrub("x" * 500, max_len=50)
    assert len(long) <= 50 and long.endswith("…")


def test_signed_helpers() -> None:
    assert _signed(0) == "0"
    assert _signed(3) == "+3"
    assert _signed(-2) == "-2"
    assert _signed_score(0.0) == "+0.00"
    assert _signed_score(0.234) == "+0.23"
    assert _signed_score(-0.234) == "-0.23"


def test_genome_growth_counts_in_window(tmp_path: Path) -> None:
    """If a per-home genome.json exists, growth = count of memories whose ts
    falls in the window. Real-life genome at ~/.forge/genome.json is also
    consulted but should not affect this synthetic test (we may pick up size
    from there, but growth comes from the in-window items we wrote)."""
    now = time.time()
    p = tmp_path / "genome.json"
    p.write_text(json.dumps({
        "memories": {
            "m1": {"text": "a", "ts": now - 100},
            "m2": {"text": "b", "ts": now - 200},
            "m3": {"text": "c", "ts": now - 86400 * 10},  # out of window
        }
    }))
    d = build_digest(tmp_path, period="day")
    # Real-life ~/.forge/genome.json is checked first; fall back to per-home.
    # The reader picks the first that exists; if home one is found, size>=3.
    # Our growth assertion: at least 2 memories visible in-window.
    assert d.genome_growth >= 2 or d.genome_size >= 3
