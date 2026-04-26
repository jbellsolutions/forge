"""Tests for forge.observability.delivery — file + Slack-MCP delivery channels."""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge import build_digest
from forge.observability.delivery import (
    Delivery,
    MarkdownFileDelivery,
    SlackMCPDelivery,
    deliver,
    make_delivery,
)


@pytest.mark.asyncio
async def test_markdown_file_delivery_writes_md_and_json(tmp_path: Path) -> None:
    digest = build_digest(tmp_path, period="day")
    meta = await MarkdownFileDelivery(home=tmp_path).send(digest)

    md = Path(meta["path"])
    assert md.exists()
    assert md.read_text(encoding="utf-8").startswith("*🌅 forge daily digest")
    js = Path(meta["json_path"])
    assert js.exists()
    parsed = json.loads(js.read_text(encoding="utf-8"))
    assert parsed["period"] == "day"


@pytest.mark.asyncio
async def test_make_delivery_default_is_file(tmp_path: Path) -> None:
    """No delivery.yaml → MarkdownFileDelivery."""
    d = make_delivery(tmp_path)
    assert isinstance(d, MarkdownFileDelivery)


@pytest.mark.asyncio
async def test_make_delivery_override_file(tmp_path: Path) -> None:
    """Even with a slack-mcp config, override='file' wins."""
    (tmp_path / "delivery.yaml").write_text(
        "channel: slack-mcp\n"
        "slack:\n"
        "  channel: '#x'\n"
        "  server: {command: npx, args: []}\n"
    )
    d = make_delivery(tmp_path, override="file")
    assert isinstance(d, MarkdownFileDelivery)


@pytest.mark.asyncio
async def test_make_delivery_slack_mcp_when_configured(tmp_path: Path) -> None:
    (tmp_path / "delivery.yaml").write_text(
        "channel: slack-mcp\n"
        "slack:\n"
        "  channel: '#updates'\n"
        "  tool_name: slack_send_message\n"
        "  server:\n"
        "    command: npx\n"
        "    args: ['-y', 'somepkg']\n"
    )
    d = make_delivery(tmp_path)
    assert isinstance(d, SlackMCPDelivery)
    assert d.channel == "#updates"


@pytest.mark.asyncio
async def test_make_delivery_falls_back_when_slack_block_incomplete(tmp_path: Path) -> None:
    """Missing slack.server → fall back to file delivery (don't crash)."""
    (tmp_path / "delivery.yaml").write_text(
        "channel: slack-mcp\n"
        "slack:\n"
        "  channel: '#x'\n"
    )
    d = make_delivery(tmp_path)
    assert isinstance(d, MarkdownFileDelivery)


@pytest.mark.asyncio
async def test_make_delivery_unknown_channel_falls_back(tmp_path: Path) -> None:
    (tmp_path / "delivery.yaml").write_text("channel: telegram\n")
    d = make_delivery(tmp_path)
    assert isinstance(d, MarkdownFileDelivery)


@pytest.mark.asyncio
async def test_slack_mcp_delivery_writes_audit_file_even_on_import_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If MCP can't be imported, we still must persist the digest to the
    audit file. The fallback is the whole point of this design."""
    # Force the lazy import to fail by stubbing the module.
    fake_mcp_client = types.ModuleType("forge.tools.mcp_client")
    fake_mcp_client.MCPClientPool = None  # type: ignore[attr-defined]
    # Make the import yield an AttributeError when MCPClientPool is read.

    class _BoomPool:
        def __init__(self, *a, **kw): raise RuntimeError("simulated import-time failure")

    fake_mcp_client.MCPClientPool = _BoomPool  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "forge.tools.mcp_client", fake_mcp_client)

    digest = build_digest(tmp_path, period="day")
    delivery = SlackMCPDelivery(
        home=tmp_path,
        server_config={"command": "npx", "args": []},
        channel="#x",
    )
    meta = await delivery.send(digest)
    assert meta["channel"] == "file"  # mirrors file delivery shape
    assert "path" in meta and Path(meta["path"]).exists()
    # Slack failed gracefully — surfaced in metadata, didn't raise.
    assert meta.get("slack") in ("skipped", "failed")
    assert "reason" in meta


@pytest.mark.asyncio
async def test_slack_mcp_delivery_calls_pool_call_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: MCPClientPool exposes call_tool(server, tool, args)."""
    captured: dict = {}

    class FakePool:
        def __init__(self, cfg): self.cfg = cfg
        async def connect_all(self): pass
        async def close_all(self): pass
        def get(self, name): return object()
        async def call_tool(self, server, tool, args):
            captured["server"] = server
            captured["tool"] = tool
            captured["args"] = args
            return {"ok": True, "ts": "1234.567"}

    fake_mcp_client = types.ModuleType("forge.tools.mcp_client")
    fake_mcp_client.MCPClientPool = FakePool  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "forge.tools.mcp_client", fake_mcp_client)

    digest = build_digest(tmp_path, period="day")
    d = SlackMCPDelivery(
        home=tmp_path,
        server_config={"command": "npx", "args": []},
        channel="#updates",
        tool_name="slack_send_message",
    )
    meta = await d.send(digest)
    assert meta["slack"] == "sent"
    assert captured == {
        "server": "slack",
        "tool": "slack_send_message",
        "args": {"channel": "#updates", "text": digest.to_markdown()},
    }


@pytest.mark.asyncio
async def test_deliver_factory_helper(tmp_path: Path) -> None:
    digest = build_digest(tmp_path, period="day")
    meta = await deliver(tmp_path, digest, override="file")
    assert meta["channel"] == "file"
    assert Path(meta["path"]).exists()
