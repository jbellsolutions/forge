"""Obsidian vault backend + tools."""
from __future__ import annotations

from pathlib import Path

import pytest

from forge.kernel.types import AgentDef, ToolCall
from forge.memory import ObsidianVault, ReasoningBank, index_into_reasoning_bank
from forge.tools.builtin.obsidian import (
    ObsidianBacklinksTool, ObsidianReadTool, ObsidianSearchTool, ObsidianWriteTool,
)


def _agent():
    return AgentDef(name="t", instructions="", profile="mock")


def test_vault_bootstraps_layout(tmp_path: Path):
    v = ObsidianVault(tmp_path / "vault")
    for sub in ("inbox", "daily", "decisions", "skills", "topics", "agents"):
        assert (tmp_path / "vault" / sub).is_dir()
    assert (tmp_path / "vault" / ".obsidian").is_dir()
    assert (tmp_path / "vault" / "README.md").exists()


def test_vault_write_and_read_with_frontmatter(tmp_path: Path):
    v = ObsidianVault(tmp_path / "vault")
    v.write_note("Q4 Plan", "Body with [[topics/strategy]] link.",
                 folder="decisions", tags=["quarterly", "ops"])
    note = v.read_note("Q4 Plan")
    assert note is not None
    assert "quarterly" in note.tags
    assert "topics/strategy" in note.forward_links


def test_vault_search_scores_filename_and_body(tmp_path: Path):
    v = ObsidianVault(tmp_path / "vault")
    v.write_note("ship-decision", "should we ship today?", folder="decisions",
                 tags=["shipping"])
    v.write_note("hire-loop", "structure of the hiring loop", folder="topics")
    hits = v.search("ship", k=2)
    assert hits and "ship-decision" in str(hits[0].path)


def test_backlinks_finds_links(tmp_path: Path):
    v = ObsidianVault(tmp_path / "vault")
    v.write_note("strategy", "core topic", folder="topics")
    v.write_note("daily", "see [[strategy]] for context", folder="daily")
    notes = v.backlinks("strategy")
    assert notes and "daily" in str(notes[0].path)


def test_index_into_reasoning_bank(tmp_path: Path):
    v = ObsidianVault(tmp_path / "vault")
    v.write_note("topic-a", "the harness should self-heal", folder="topics", tags=["x"])
    v.write_note("topic-b", "council reaches consensus", folder="topics", tags=["x"])
    bank = ReasoningBank(path=tmp_path / "rb.json")
    n = index_into_reasoning_bank(v, bank)
    assert n >= 2
    hits = bank.retrieve("self-healing harness", k=1, min_confidence=0.0)
    assert hits


@pytest.mark.asyncio
async def test_write_search_read_tools_roundtrip(tmp_path: Path):
    v = ObsidianVault(tmp_path / "vault")
    w = ObsidianWriteTool(v)
    r = ObsidianReadTool(v)
    s = ObsidianSearchTool(v)
    bl = ObsidianBacklinksTool(v)

    res = await w.execute(ToolCall("1", "obsidian_write", {
        "title": "Council ship Q4",
        "body": "verdict: ship.\nLinked to [[topics/q4-launch]].",
        "folder": "decisions",
        "tags": ["decision"],
    }), _agent())
    assert not res.is_error

    res = await s.execute(ToolCall("2", "obsidian_search",
                                    {"query": "ship", "k": 2}), _agent())
    assert "council" in res.content.lower()

    res = await r.execute(ToolCall("3", "obsidian_read",
                                    {"path_or_title": "Council ship Q4"}), _agent())
    assert "verdict" in res.content

    res = await bl.execute(ToolCall("4", "obsidian_backlinks",
                                     {"target": "topics/q4-launch"}), _agent())
    assert "council" in res.content.lower()
