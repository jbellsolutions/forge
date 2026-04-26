"""Tests for forge.tools.builtin.web_search + web_fetch.

All HTTP is mocked. Asserts:
- domain allowlist refusal (web_fetch)
- size cap (web_fetch)
- backend selection priority (web_search)
- concurrency_safe = True for both
- Tool.schema() exposes concurrency_safe
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from forge import WebFetchTool, WebSearchTool
from forge.kernel.types import AgentDef, ToolCall


def _agent() -> AgentDef:
    return AgentDef(name="t", instructions="", profile="mock")


# ---------------------------------------------------------------------------
# concurrency_safe + schema
# ---------------------------------------------------------------------------

def test_web_tools_marked_concurrency_safe() -> None:
    assert WebFetchTool.concurrency_safe is True
    assert WebSearchTool.concurrency_safe is True
    schema_f = WebFetchTool().schema()
    schema_s = WebSearchTool().schema()
    assert schema_f["concurrency_safe"] is True
    assert schema_s["concurrency_safe"] is True


# ---------------------------------------------------------------------------
# WebFetchTool — allowlist + size cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_web_fetch_refuses_offlist_host() -> None:
    """A misconfigured URL must NOT cause an HTTP call."""
    fetched: list[str] = []

    def fetcher(url: str, *, timeout: float, max_bytes: int) -> bytes:
        fetched.append(url); return b""

    tool = WebFetchTool(fetcher=fetcher)
    r = await tool.execute(
        ToolCall(id="1", name="web_fetch",
                 arguments={"url": "https://attacker.example.com/x"}),
        _agent(),
    )
    assert r.is_error
    assert "allowlist" in r.content.lower()
    assert fetched == []


@pytest.mark.asyncio
async def test_web_fetch_returns_title_and_body_for_allowed_host() -> None:
    fixture = (
        b"<!doctype html><html><head><title>Hello forge</title></head>"
        b"<body><h1>Welcome</h1><p>Some <b>body</b> text.</p></body></html>"
    )

    def fetcher(url: str, *, timeout: float, max_bytes: int) -> bytes:
        return fixture[:max_bytes]

    tool = WebFetchTool(fetcher=fetcher, default_max_bytes=4096)
    r = await tool.execute(
        ToolCall(id="1", name="web_fetch",
                 arguments={"url": "https://www.anthropic.com/news"}),
        _agent(),
    )
    assert not r.is_error
    assert "Hello forge" in r.content
    assert "Welcome" in r.content
    assert "<" not in r.content.split("\n", 2)[-1], "tags must be stripped from body"


@pytest.mark.asyncio
async def test_web_fetch_caps_body_size() -> None:
    big = b"x" * 100_000

    def fetcher(url: str, *, timeout: float, max_bytes: int) -> bytes:
        return big[:max_bytes]

    tool = WebFetchTool(fetcher=fetcher)
    r = await tool.execute(
        ToolCall(id="1", name="web_fetch",
                 arguments={"url": "https://www.anthropic.com/x", "max_bytes": 1024}),
        _agent(),
    )
    assert not r.is_error
    body = r.content.split("\n", 2)[-1]
    assert len(body) <= 1024 + 50  # +slack for header line


# ---------------------------------------------------------------------------
# WebSearchTool — backend selection + injectable searcher
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_web_search_uses_injected_searcher() -> None:
    seen = {}

    def searcher(query: str, max_results: int, backend: str) -> list[dict]:
        seen["q"] = query
        seen["n"] = max_results
        seen["backend"] = backend
        return [{"title": "x", "url": "https://github.com/y", "snippet": "z", "source": backend}]

    tool = WebSearchTool(backend="ddg", searcher=searcher)
    r = await tool.execute(
        ToolCall(id="1", name="web_search",
                 arguments={"query": "MCP tool registry", "max_results": 3}),
        _agent(),
    )
    assert not r.is_error
    parsed = json.loads(r.content)
    assert parsed["query"] == "MCP tool registry"
    assert parsed["backend"] == "ddg"
    assert len(parsed["results"]) == 1
    assert seen == {"q": "MCP tool registry", "n": 3, "backend": "ddg"}


@pytest.mark.asyncio
async def test_web_search_backend_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tavily > Brave > DDG when keys are present."""
    monkeypatch.setenv("TAVILY_API_KEY", "x")
    tool = WebSearchTool()
    assert tool._pick_backend() == "tavily"

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("BRAVE_API_KEY", "y")
    assert WebSearchTool()._pick_backend() == "brave"

    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    assert WebSearchTool()._pick_backend() == "ddg"


@pytest.mark.asyncio
async def test_web_search_empty_query_is_error() -> None:
    tool = WebSearchTool(searcher=lambda *a, **kw: [])
    r = await tool.execute(
        ToolCall(id="1", name="web_search", arguments={"query": ""}),
        _agent(),
    )
    assert r.is_error


@pytest.mark.asyncio
async def test_web_search_propagates_backend_error() -> None:
    def boom(query, max_results, backend): raise RuntimeError("backend down")
    tool = WebSearchTool(searcher=boom)
    r = await tool.execute(
        ToolCall(id="1", name="web_search", arguments={"query": "anything"}),
        _agent(),
    )
    assert r.is_error
    assert "backend down" in r.content
