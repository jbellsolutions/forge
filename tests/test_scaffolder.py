"""Tests for forge.scaffolder — describe → design → scaffold flow.

Mocks the LLM provider; asserts:
- design_swarm: returns a SwarmDesign even on garbage LLM output (fallback)
- write_terminal_project: emits examples/<name>/run.py + design.json
- write_claude_subagents: emits .claude/agents/<name>_<agent>.md per agent
- propose_dashboard_action: POSTs /sync/propose-design and returns id
"""
from __future__ import annotations

import asyncio
import json

import pytest

from forge.kernel.types import AssistantTurn
from forge.scaffolder import (
    AgentSpec, SwarmDesign,
    design_swarm, write_terminal_project, write_claude_subagents,
    propose_dashboard_action,
)


# ---------------------------------------------------------------------------
# design.py
# ---------------------------------------------------------------------------

class _StubProvider:
    """Returns a canned AssistantTurn — bypasses the real LLM."""
    def __init__(self, text: str) -> None:
        self._text = text
        from forge.providers import load_profile
        self.profile = load_profile("anthropic-haiku")

    async def generate(self, messages, tools=None, max_tokens=2048, **kw):
        return AssistantTurn(text=self._text, tool_calls=[],
                             usage={"input_tokens": 1, "output_tokens": 1})


def test_design_swarm_parses_clean_json(monkeypatch):
    payload = {
        "name": "notion_briefer",
        "description": "Daily Notion summary to Slack",
        "topology": "single",
        "consensus": "none",
        "schedule": "0 8 * * *",
        "agents": [{
            "name": "briefer",
            "role": "summarizer",
            "instructions": "Pull yesterday's Notion edits, summarize, post to Slack.",
            "profile": "anthropic-haiku",
            "tools": ["notion_search", "slack_send_message"],
        }],
        "notes": "single agent — task is linear",
    }
    monkeypatch.setattr(
        "forge.scaffolder.design.make_provider",
        lambda profile: _StubProvider(json.dumps(payload)),
    )
    design = asyncio.run(design_swarm("Daily Notion → Slack brief"))
    assert design.name == "notion_briefer"
    assert design.schedule == "0 8 * * *"
    assert len(design.agents) == 1
    assert design.agents[0].tools == ["notion_search", "slack_send_message"]


def test_design_swarm_strips_code_fences(monkeypatch):
    raw = "```json\n" + json.dumps({"name": "x", "description": "y", "agents": []}) + "\n```"
    monkeypatch.setattr(
        "forge.scaffolder.design.make_provider",
        lambda profile: _StubProvider(raw),
    )
    design = asyncio.run(design_swarm("test"))
    assert design.name == "x"
    # Empty agents list → fallback single agent injected.
    assert len(design.agents) == 1


def test_design_swarm_falls_back_on_garbage(monkeypatch):
    monkeypatch.setattr(
        "forge.scaffolder.design.make_provider",
        lambda profile: _StubProvider("not json at all, just prose"),
    )
    design = asyncio.run(design_swarm("a thing that does stuff"))
    assert "FALLBACK" in design.notes
    assert len(design.agents) == 1


def test_design_swarm_falls_back_on_missing_provider(monkeypatch):
    def boom(profile):
        raise RuntimeError("no key")
    monkeypatch.setattr("forge.scaffolder.design.make_provider", boom)
    design = asyncio.run(design_swarm("hello"))
    assert "FALLBACK" in design.notes
    assert design.agents[0].name == "agent"


def test_design_swarm_rejects_empty():
    with pytest.raises(ValueError, match="must not be empty"):
        asyncio.run(design_swarm(""))


# ---------------------------------------------------------------------------
# writers.py — terminal
# ---------------------------------------------------------------------------

def _design():
    return SwarmDesign(
        name="my_swarm",
        description="Pull X, do Y, post Z.",
        agents=[
            AgentSpec(name="puller", role="pull", instructions="Pull X.",
                      profile="anthropic-haiku", tools=["web_fetch"]),
            AgentSpec(name="poster", role="post", instructions="Post Z.",
                      profile="anthropic", tools=["slack_send_message"]),
        ],
        schedule="0 9 * * *",
        topology="pipeline",
        consensus="none",
        notes="ok",
    )


def test_write_terminal_project_emits_run_py(tmp_path):
    paths = write_terminal_project(_design(), tmp_path)
    target = tmp_path / "examples" / "my_swarm"
    assert (target / "run.py").exists()
    assert (target / "README.md").exists()
    assert (target / "design.json").exists()
    # Heartbeat present because schedule is set.
    assert (target / "heartbeats" / "run.md").exists()
    body = (target / "run.py").read_text()
    assert "puller" in body and "poster" in body
    # design.json round-trips.
    data = json.loads((target / "design.json").read_text())
    assert data["name"] == "my_swarm"
    assert len(data["agents"]) == 2


def test_write_terminal_no_schedule_no_heartbeat(tmp_path):
    d = _design()
    d.schedule = None
    write_terminal_project(d, tmp_path)
    assert not (tmp_path / "examples" / "my_swarm" / "heartbeats").exists()


# ---------------------------------------------------------------------------
# writers.py — Claude Code subagents
# ---------------------------------------------------------------------------

def test_write_claude_subagents_one_md_per_agent(tmp_path):
    paths = write_claude_subagents(_design(), tmp_path)
    agents_dir = tmp_path / ".claude" / "agents"
    assert (agents_dir / "my_swarm_puller.md").exists()
    assert (agents_dir / "my_swarm_poster.md").exists()
    assert (agents_dir / "my_swarm.README.md").exists()
    body = (agents_dir / "my_swarm_puller.md").read_text()
    # Frontmatter sanity.
    assert body.startswith("---")
    assert "name: my_swarm_puller" in body
    assert "tools: web_fetch" in body
    assert "Pull X." in body


# ---------------------------------------------------------------------------
# writers.py — dashboard PendingAction
# ---------------------------------------------------------------------------

def test_propose_dashboard_action_round_trip(tmp_path, monkeypatch):
    """Boot a real FastAPI app + TestClient; pass its post as transport."""
    pytest.importorskip("fastapi")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/d.db")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-characters-min____")
    monkeypatch.setenv("SYNC_SHARED_SECRET", "tok")
    from forge.dashboard.server import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    with TestClient(app) as c:
        def transport(url, body, headers):
            path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
            r = c.post(path, content=body, headers=headers)
            r.raise_for_status()
            return r.json()
        aid = propose_dashboard_action(_design(), "http://test", "tok", transport=transport)
        assert aid.startswith("pa_")
        # And the row is queryable.
        from forge.dashboard.db import PendingAction
        from sqlmodel import Session
        with Session(app.state.engine) as ses:
            row = ses.get(PendingAction, aid)
            assert row.kind == "start_project"
            assert row.status == "pending"
            assert row.payload_json["name"] == "my_swarm"
