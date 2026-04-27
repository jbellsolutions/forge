"""Tests for the orchestrator agent + propose_* actions.

Uses a ScriptedProvider that emits tool_use blocks. Asserts:
- propose_spawn → PendingAction row inserted with status=pending
- AgentRow is NOT mutated until Approve flow + sync apply
- propose_start_project carries template name + description
- bad schema rejected with friendly error
- chat history persists across turns to OrchestratorMessage
"""
from __future__ import annotations

import asyncio

import pytest

# Skip if [dashboard] extra not installed.
pytest.importorskip("fastapi")
pytest.importorskip("sqlmodel")

from forge.kernel.types import AssistantTurn, Message, ToolCall


@pytest.fixture()
def ses_factory(tmp_path, monkeypatch):
    """Per-test in-memory SQLite session factory."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    monkeypatch.setenv("SESSION_SECRET", "test" * 16)
    monkeypatch.setenv("SYNC_SHARED_SECRET", "x")

    from forge.dashboard.db import init_db, make_engine
    from sqlmodel import Session

    engine = make_engine(f"sqlite:///{tmp_path}/test.db")
    init_db(engine)

    def factory():
        return Session(engine)

    return factory


class ScriptedProvider:
    """Replays a list of AssistantTurns. Each turn either has tool_use
    blocks or a final text. Loop terminates when text-only turn arrives."""
    def __init__(self, turns: list[AssistantTurn]) -> None:
        from forge.providers import load_profile
        self.profile = load_profile("anthropic-haiku")
        self._turns = list(turns)
        self.calls: list[list[Message]] = []

    async def generate(self, messages, tools=None, max_tokens=2048, **kw):
        self.calls.append(list(messages))
        if not self._turns:
            return AssistantTurn(text="(out of script)", tool_calls=[],
                                 usage={"input_tokens": 1, "output_tokens": 1})
        return self._turns.pop(0)


# ---------------------------------------------------------------------------
# propose_* schema validation
# ---------------------------------------------------------------------------

def test_propose_spawn_inserts_pending_action(ses_factory) -> None:
    from forge.orchestrator.actions import propose_spawn
    from forge.dashboard.db import PendingAction
    from sqlmodel import select

    with ses_factory() as ses:
        aid = propose_spawn(
            ses,
            project="forge", name="notion-summarizer",
            instructions="Summarize Notion daily.",
            profile="anthropic-haiku",
            tools_allowed=["fs_read", "fs_write"],
        )
        assert aid.startswith("pa_")
        actions = ses.exec(select(PendingAction)).all()
        assert len(actions) == 1
        a = actions[0]
        assert a.status == "pending"
        assert a.kind == "spawn_agent"
        assert a.payload_json["name"] == "notion-summarizer"
        assert a.payload_json["tools_allowed"] == ["fs_read", "fs_write"]


def test_propose_spawn_rejects_missing_required(ses_factory) -> None:
    from forge.orchestrator.actions import propose_spawn
    with ses_factory() as ses:
        with pytest.raises(ValueError, match="missing required"):
            propose_spawn(ses, project="forge", name="x", instructions="", profile="")  # all empty strings ARE present
        # missing key path:
        # call without required `profile` to actually trigger
        with pytest.raises(TypeError):
            propose_spawn(ses, project="forge", name="x", instructions="y")


def test_propose_start_project_validates_template(ses_factory) -> None:
    from forge.orchestrator.actions import propose_start_project
    with ses_factory() as ses:
        with pytest.raises(ValueError, match="unknown template"):
            propose_start_project(ses, name="x", template="blockchain")
        aid = propose_start_project(ses, name="outbound_v2", template="sdr",
                                    description="Outbound to Series-A SaaS.")
        assert aid.startswith("pa_")


def test_propose_run_recurse_optional_fields(ses_factory) -> None:
    from forge.orchestrator.actions import propose_run_recurse
    from forge.dashboard.db import PendingAction
    with ses_factory() as ses:
        aid = propose_run_recurse(ses)
        assert aid.startswith("pa_")
        a = ses.get(PendingAction, aid)
        assert a.payload_json == {"with_intel": False}
        aid2 = propose_run_recurse(ses, home="~/.forge/x", with_intel=True, profile="anthropic")
        a2 = ses.get(PendingAction, aid2)
        assert a2.payload_json["with_intel"] is True
        assert a2.payload_json["home"] == "~/.forge/x"


# ---------------------------------------------------------------------------
# Templates render
# ---------------------------------------------------------------------------

def test_render_operator_template_substitutes_name() -> None:
    from forge.orchestrator.templates import render
    files = render("operator", "outbound_v2", description="Outbound to SaaS")
    expected_path = "examples/outbound_v2/run.py"
    assert expected_path in files
    assert "outbound_v2" in files[expected_path]
    assert "Outbound to SaaS" in files[expected_path]
    # Heartbeat included.
    assert any("heartbeats/morning.md" in p for p in files)


def test_render_unknown_template_raises() -> None:
    from forge.orchestrator.templates import render
    with pytest.raises(ValueError, match="unknown template"):
        render("blockchain", "x")


# ---------------------------------------------------------------------------
# OrchestratorAgent chat turn
# ---------------------------------------------------------------------------

def test_chat_turn_proposes_spawn_via_tool_use(ses_factory) -> None:
    """Scripted: turn 1 calls propose_spawn; turn 2 emits final reply."""
    from forge.orchestrator.agent import OrchestratorAgent
    from forge.dashboard.db import PendingAction, OrchestratorMessage
    from sqlmodel import select

    spawn_call = ToolCall(
        id="t1", name="propose_spawn",
        arguments={
            "project": "forge", "name": "notion-summarizer",
            "instructions": "Summarize daily.",
            "profile": "anthropic-haiku",
        },
    )
    turns = [
        AssistantTurn(text="", tool_calls=[spawn_call],
                      usage={"input_tokens": 100, "output_tokens": 30}),
        AssistantTurn(
            text="Proposed pa_x. Click Approve in the workspace.",
            tool_calls=[], usage={"input_tokens": 200, "output_tokens": 80},
        ),
    ]
    provider = ScriptedProvider(turns)

    agent = OrchestratorAgent(ses_factory=ses_factory, provider=provider)
    result = asyncio.run(agent.chat_turn("chat-1", "spawn me a notion summarizer"))

    assert "Click Approve" in result["reply"]
    assert len(result["actions"]) == 1
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "propose_spawn"

    # PendingAction row inserted with status=pending — NOT applied.
    with ses_factory() as ses:
        actions = ses.exec(select(PendingAction)).all()
        assert len(actions) == 1
        assert actions[0].status == "pending"
        # No AgentRow created yet — that's the local apply step's job (C-3).
        from forge.dashboard.db import AgentRow
        agents = ses.exec(select(AgentRow)).all()
        assert agents == []

    # Chat history persisted: 1 user + 1 assistant message.
    with ses_factory() as ses:
        msgs = ses.exec(
            select(OrchestratorMessage).where(OrchestratorMessage.session_id == "chat-1")
            .order_by(OrchestratorMessage.ts)
        ).all()
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"


def test_chat_turn_list_agents_returns_workspace(ses_factory) -> None:
    """Read-only tool: list_agents. No PendingAction emitted."""
    from forge.orchestrator.agent import OrchestratorAgent
    from forge.dashboard.db import AgentRow, Project

    # Seed.
    with ses_factory() as ses:
        ses.add(Project(id="p1", name="forge", slug="forge"))
        ses.add(AgentRow(id="a1", project_id="p1", name="operator",
                         profile="anthropic"))
        ses.commit()

    list_call = ToolCall(id="t1", name="list_agents", arguments={})
    turns = [
        AssistantTurn(text="", tool_calls=[list_call],
                      usage={"input_tokens": 1, "output_tokens": 1}),
        AssistantTurn(text="You have 1 agent: operator.", tool_calls=[],
                      usage={"input_tokens": 1, "output_tokens": 1}),
    ]
    provider = ScriptedProvider(turns)
    agent = OrchestratorAgent(ses_factory=ses_factory, provider=provider)
    result = asyncio.run(agent.chat_turn("chat-2", "what agents do I have?"))
    assert "1 agent" in result["reply"]
    assert result["actions"] == []
    # Tool result was the agent list.
    assert result["tool_calls"][0]["name"] == "list_agents"
    assert any("operator" in str(r) for r in [result["tool_calls"][0]["result"]])


def test_chat_turn_iteration_cap(ses_factory) -> None:
    """Provider that always returns tool_use eventually hits the cap and
    falls back to a synthetic message — never spins forever."""
    from forge.orchestrator.agent import OrchestratorAgent
    looper = ToolCall(id="t", name="list_agents", arguments={})
    turns = [
        AssistantTurn(text="", tool_calls=[looper],
                      usage={"input_tokens": 1, "output_tokens": 1})
        for _ in range(20)
    ]
    provider = ScriptedProvider(turns)
    agent = OrchestratorAgent(ses_factory=ses_factory, provider=provider,
                              max_tool_iterations=3)
    result = asyncio.run(agent.chat_turn("chat-cap", "loop forever"))
    assert "iteration cap" in result["reply"].lower()


def test_chat_turn_assistant_tool_call_message_uses_provider_keys(ses_factory) -> None:
    """Regression for the live-Railway 400: 'messages: text content blocks must
    be non-empty'. When the orchestrator emits an assistant turn with tool_calls
    and empty text, the provider expects metadata['raw_tool_calls'] with field
    'arguments' (not metadata['tool_calls'] with field 'input'). Asserts the
    second LLM call sees a properly-formed prior assistant message."""
    from forge.orchestrator.agent import OrchestratorAgent

    spawn_call = ToolCall(
        id="t1", name="propose_spawn",
        arguments={"project": "forge", "name": "x", "instructions": "y",
                   "profile": "anthropic-haiku"},
    )
    turns = [
        AssistantTurn(text="", tool_calls=[spawn_call],
                      usage={"input_tokens": 1, "output_tokens": 1}),
        AssistantTurn(text="ok", tool_calls=[],
                      usage={"input_tokens": 1, "output_tokens": 1}),
    ]
    provider = ScriptedProvider(turns)
    agent = OrchestratorAgent(ses_factory=ses_factory, provider=provider)
    asyncio.run(agent.chat_turn("chat-meta", "spawn"))

    # The second .generate() call sees a 3-message history: user, assistant
    # (with raw_tool_calls), tool_result. Find the assistant message.
    assert len(provider.calls) == 2
    second_call_messages = provider.calls[1]
    assistant_msgs = [m for m in second_call_messages if m.role == "assistant"]
    assert len(assistant_msgs) == 1
    am = assistant_msgs[0]
    # The provider keys MUST be raw_tool_calls + arguments — anything else
    # silently produces an empty content block and Anthropic 400s in prod.
    rtc = am.metadata.get("raw_tool_calls")
    assert rtc, f"missing raw_tool_calls; metadata was {am.metadata!r}"
    assert "arguments" in rtc[0], f"expected 'arguments' key, got {list(rtc[0])}"
    assert "input" not in rtc[0], "stale 'input' key would skip provider serialization"
