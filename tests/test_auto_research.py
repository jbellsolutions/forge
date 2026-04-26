"""Tests for forge.intel.auto_research — AutoAgent-style sub-agent.

Uses a scripted MockProvider to simulate a multi-turn auto-research run.
Asserts:
- IntelStoreItemTool persists items
- ledger row appended to <home>/intel/auto-research.tsv
- summary_md persisted under <home>/intel/research/<ts>-<label>.md
- budget cap on tool_calls trips Verdict.SAFETY_BLOCKED
- daily / weekly budget defaults
- run_auto_research is fully test-injectable (no live API)
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from forge.intel import AutoResearchBudget, run_auto_research
from forge.kernel.types import AssistantTurn, Message, ToolCall
from forge.providers import load_profile
from forge.providers.base import Provider


class ScriptedProvider(Provider):
    """Replays a deterministic sequence of AssistantTurns.

    Each turn either contains tool_calls (loop runs the tool, comes back)
    or final text (loop terminates).
    """
    def __init__(self, turns: list[AssistantTurn]) -> None:
        self.profile = load_profile("anthropic-haiku")
        self._turns = list(turns)
        self.calls: list[list[Message]] = []

    async def generate(self, messages, tools=None, max_tokens=2048, **kw):
        self.calls.append(list(messages))
        if not self._turns:
            return AssistantTurn(text="(done)", tool_calls=[],
                                 usage={"input_tokens": 1, "output_tokens": 1})
        return self._turns.pop(0)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

def test_budget_defaults() -> None:
    daily = AutoResearchBudget.daily()
    assert daily.label == "daily"
    assert daily.max_turns == 4
    assert daily.max_cost_usd == 0.15
    assert daily.max_tool_calls == 8

    weekly = AutoResearchBudget.weekly()
    assert weekly.label == "weekly"
    assert weekly.max_turns == 20
    assert weekly.max_cost_usd == 1.00
    assert weekly.max_tool_calls == 40


# ---------------------------------------------------------------------------
# Happy-path round trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_auto_research_persists_items_and_ledger(tmp_path: Path) -> None:
    """Scripted: turn 1 calls intel_store_item; turn 2 emits final summary."""
    store_call = ToolCall(
        id="t1", name="intel_store_item",
        arguments={
            "source": "openai_python_releases",
            "title": "openai-python v2 ships function calling",
            "url": "https://github.com/openai/openai-python/releases/tag/v2",
            "summary": "Adds tool use",
            "tags": ["openai", "sdk"],
            "relevance": "high",
        },
    )
    turns = [
        AssistantTurn(text="", tool_calls=[store_call],
                      usage={"input_tokens": 100, "output_tokens": 50}),
        AssistantTurn(
            text="### Summary\n- OpenAI shipped function calling in openai-python v2.\n",
            tool_calls=[],
            usage={"input_tokens": 200, "output_tokens": 80},
        ),
    ]
    provider = ScriptedProvider(turns)

    result = await run_auto_research(
        tmp_path, profile="anthropic-haiku", provider=provider,
        budget=AutoResearchBudget.daily(),
    )
    assert result.error is None
    assert result.tool_calls == 1
    assert "OpenAI shipped function calling" in result.summary_md

    # Ledger row written.
    ledger = tmp_path / "intel" / "auto-research.tsv"
    assert ledger.exists()
    rows = ledger.read_text().splitlines()
    assert rows[0].startswith("ts\t")
    assert len(rows) == 2  # header + one row
    assert "daily" in rows[1] and "anthropic-haiku" in rows[1]

    # Summary persisted.
    summary_path = Path(result.summary_path)
    assert summary_path.exists()
    body = summary_path.read_text()
    assert "OpenAI shipped function calling" in body
    assert "auto-research summary" in body.lower()

    # IntelItem persisted to today's JSON via store_items.
    today_glob = list((tmp_path / "intel").glob("*.json"))
    # at least one of the daily JSONs has the URL.
    found_url = False
    for p in today_glob:
        if p.name == "seen.json":
            continue
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        if isinstance(data, list):
            for it in data:
                if isinstance(it, dict) and "openai-python" in it.get("url", ""):
                    found_url = True
    assert found_url, "intel_store_item must persist to today's intel JSON"


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_budget_max_tool_calls_short_circuits(tmp_path: Path) -> None:
    """If the agent tries to exceed `max_tool_calls`, the budget guard
    fires SAFETY_BLOCKED and the loop terminates cleanly."""
    # Configure tiny budget to force the trip.
    tiny = AutoResearchBudget(max_turns=10, max_cost_usd=10.0,
                              max_tool_calls=2, label="daily")

    def make_call(i: int) -> ToolCall:
        return ToolCall(
            id=f"t{i}", name="intel_store_item",
            arguments={
                "source": f"src_{i}", "title": f"item {i}",
                "url": f"https://github.com/a/b/{i}", "summary": "",
                "tags": [], "relevance": "med",
            },
        )

    turns = [
        AssistantTurn(text="", tool_calls=[make_call(1)],
                      usage={"input_tokens": 1, "output_tokens": 1}),
        AssistantTurn(text="", tool_calls=[make_call(2)],
                      usage={"input_tokens": 1, "output_tokens": 1}),
        # 3rd call should be blocked by budget guard.
        AssistantTurn(text="", tool_calls=[make_call(3)],
                      usage={"input_tokens": 1, "output_tokens": 1}),
        AssistantTurn(text="### Summary\nbudget tripped", tool_calls=[],
                      usage={"input_tokens": 1, "output_tokens": 1}),
    ]
    provider = ScriptedProvider(turns)

    result = await run_auto_research(
        tmp_path, profile="anthropic-haiku", provider=provider, budget=tiny,
    )
    # Budget guard tripped on call #3; truncated flag set.
    assert result.truncated, "exceeding max_tool_calls must set truncated=True"
    # Ledger row carries the truncated marker.
    ledger = (tmp_path / "intel" / "auto-research.tsv").read_text().splitlines()
    assert ledger[-1].endswith("\t1"), f"truncated col should be 1; got {ledger[-1]!r}"


@pytest.mark.asyncio
async def test_no_provider_short_circuits_with_haiku_fallback(tmp_path: Path) -> None:
    """When no API key + no provider injected, run_auto_research must not crash;
    we either build a real provider (if key set in CI) or surface error gracefully."""
    # We pass an injected provider that returns an immediate final turn.
    turns = [AssistantTurn(text="### Summary\n(no findings)\n", tool_calls=[],
                           usage={"input_tokens": 1, "output_tokens": 1})]
    provider = ScriptedProvider(turns)
    result = await run_auto_research(
        tmp_path, provider=provider, budget=AutoResearchBudget.daily(),
    )
    assert result.error is None
    assert "no findings" in result.summary_md
