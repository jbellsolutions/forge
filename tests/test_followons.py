"""MCP / Composio / OTel / LLM proposer — surface tests, no live network."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from forge.kernel import HookBus
from forge.kernel.types import AssistantTurn, Message
from forge.observability.otel import OTelExporter
from forge.providers.base import Provider
from forge.providers.mock import MockProvider
from forge.providers import load_profile
from forge.recursion import HarnessDiff, ResultsLedger, parse_diffs, propose_with_llm
from forge.tools.mcp_client import MCPServerConfig, load_mcp_servers


# ---- MCP --------------------------------------------------------------------

def test_mcp_server_config_from_dict():
    cfg = MCPServerConfig.from_dict("fs", {
        "command": "npx", "args": ["-y", "@mcp/server-fs", "/tmp"],
        "env": {"FOO": "1"},
    })
    assert cfg.name == "fs"
    assert cfg.command == "npx"
    assert cfg.args[0] == "-y"
    assert cfg.env["FOO"] == "1"


def test_load_mcp_servers_from_json(tmp_path: Path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text("""{"mcpServers": {
        "fs":  {"command": "npx", "args": ["-y", "@mcp/server-fs"]},
        "git": {"command": "npx", "args": ["-y", "@mcp/server-git"]}
    }}""")
    servers = load_mcp_servers(cfg)
    assert sorted(s.name for s in servers) == ["fs", "git"]


# ---- OTel exporter (no-op when otel not installed) -------------------------

def test_otel_exporter_attaches_safely():
    exp = OTelExporter(service_name="forge-test")
    hooks = HookBus()
    # Should not crash regardless of whether opentelemetry is installed
    exp.attach(hooks)


# ---- LLM proposer parser ---------------------------------------------------

def test_parse_diffs_extracts_json_array_from_fenced_block():
    text = (
        "Here are the proposed diffs:\n"
        "```json\n"
        '[{"rationale":"x","target":"a.yaml","op":"deny_tool","payload":{"tool":"bad"}}]\n'
        "```\n"
        "End."
    )
    diffs = parse_diffs(text)
    assert len(diffs) == 1
    assert diffs[0].op == "deny_tool"


def test_parse_diffs_handles_empty_array():
    diffs = parse_diffs("[]")
    assert diffs == []


def test_parse_diffs_skips_malformed_items():
    text = '[{"rationale":"x","target":"a","op":"deny_tool"}, {"missing":"keys"}]'
    diffs = parse_diffs(text)
    assert len(diffs) == 1


@pytest.mark.asyncio
async def test_propose_with_llm_uses_mock_provider(tmp_path: Path):
    # Pre-populate a fake symptoms-bearing trace
    sd = tmp_path / "traces" / "s1"
    sd.mkdir(parents=True)
    import json
    with (sd / "tool_calls.jsonl").open("w") as f:
        for _ in range(6):
            f.write(json.dumps({"phase": "post", "name": "bad", "is_error": True}) + "\n")

    profile = load_profile("mock")
    canned = AssistantTurn(
        text='[{"rationale":"bad fails 6x","target":".forge/healing/circuits.json",'
             '"op":"retune_circuit","payload":{"tool":"bad","fail_threshold":2,"cooldown_seconds":600}}]',
        tool_calls=[], usage={"input_tokens": 1, "output_tokens": 1},
    )
    provider = MockProvider.scripted(profile, [canned])
    diffs = await propose_with_llm(provider, tmp_path / "traces")
    assert len(diffs) == 1 and diffs[0].op == "retune_circuit"


# ---- ResultsLedger ----------------------------------------------------------

def test_results_ledger_appends_and_reads(tmp_path: Path):
    led = ResultsLedger(tmp_path / "results.tsv")
    led.append(candidate="cand-1", base_score=0.5, candidate_score=0.6, kept=True, notes="ok")
    led.append(candidate="cand-2", base_score=0.6, candidate_score=0.55, kept=False)
    rows = led.rows()
    assert len(rows) == 2
    assert rows[0]["kept"] == "1"
    assert rows[1]["kept"] == "0"
    assert float(rows[0]["delta"]) > 0
