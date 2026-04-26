"""Tests for forge.intel.fetch — passive RSS/Atom/GitHub-releases pull.

All HTTP is mocked via an injected fetcher callable. Asserts:
- domain allowlist refusal for off-list URLs
- RSS / Atom / GitHub-releases / JSON-changelog parsers
- dedup against `<home>/intel/seen.json` across runs
- store_items idempotent merge into <home>/intel/<date>.json
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import pytest

from forge.intel import (
    IntelItem,
    Source,
    build_intel_digest,
    is_allowed,
    pull_intel,
    store_items,
)
from forge.intel.fetch import _hash, _parse_date, _strip_html
from forge.intel.normalize import keyword_relevance, normalize_item


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------

def test_allowlist_accepts_known_hosts() -> None:
    assert is_allowed("https://www.anthropic.com/news")
    assert is_allowed("https://api.github.com/repos/openai/openai-python/releases")
    assert is_allowed("https://openai.com/blog/rss.xml")


def test_allowlist_rejects_unknown_hosts() -> None:
    assert not is_allowed("https://evil.example.com/hijack")
    assert not is_allowed("file:///etc/passwd")
    assert not is_allowed("http://localhost:9999")


def test_pull_intel_refuses_offlist_source(tmp_path: Path) -> None:
    """A misconfigured source must NOT cause an HTTP call."""
    bad = Source(
        name="bad", kind="rss", url="https://attacker.example.com/rss",
        tags=("test",),
    )

    calls: list[str] = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        return b""

    items = pull_intel(tmp_path, [bad], fetcher=fetcher)
    assert items == []
    assert calls == [], "off-list URL must not be fetched"


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

RSS_FIXTURE = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<title>OpenAI</title>
<item>
  <title>Function calling lands in GPT-5</title>
  <link>https://openai.com/blog/function-calling-gpt5</link>
  <description>Tool use, agentic patterns, and a new SDK.</description>
  <pubDate>Mon, 21 Apr 2026 12:00:00 GMT</pubDate>
</item>
<item>
  <title>Generic AI weekly roundup</title>
  <link>https://openai.com/blog/roundup</link>
  <description>News digest.</description>
  <pubDate>Mon, 21 Apr 2026 13:00:00 GMT</pubDate>
</item>
</channel></rss>"""


ATOM_FIXTURE = (
    '<?xml version="1.0"?>'
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    "<title>MCP Changelog</title>"
    "<entry>"
    "<title>servers v0.42 — adds tool catalog API</title>"
    '<link href="https://github.com/modelcontextprotocol/servers/releases/tag/v0.42"/>'
    "<summary>New MCP tool registry endpoint, breaking change in catalog.</summary>"
    "<updated>2026-04-22T10:00:00Z</updated>"
    "</entry>"
    "</feed>"
).encode("utf-8")


GITHUB_FIXTURE = json.dumps([
    {
        "name": "v1.5.0", "tag_name": "v1.5.0",
        "html_url": "https://github.com/openai/openai-python/releases/tag/v1.5.0",
        "body": "Adds streaming tool-call support; ships function calling.",
        "published_at": "2026-04-22T10:00:00Z",
    },
    {
        "name": "v1.4.0", "tag_name": "v1.4.0",
        "html_url": "https://github.com/openai/openai-python/releases/tag/v1.4.0",
        "body": "Bug fixes.",
        "published_at": "2026-04-15T10:00:00Z",
    },
]).encode("utf-8")


JSON_CHANGELOG_FIXTURE = json.dumps([
    {
        "title": "Composio launches MCP transport",
        "url": "https://github.com/ComposioHQ/composio/releases/tag/v0.7",
        "summary": "1000+ apps now over MCP. Tool registry rewritten.",
        "ts": 1745000000.0,
    },
]).encode("utf-8")


def _scripted(map_: dict[str, bytes]) -> Callable[[str], bytes]:
    def fetch(url: str) -> bytes:
        if url not in map_:
            raise FileNotFoundError(url)
        return map_[url]
    return fetch


def test_pull_rss_parses_items(tmp_path: Path) -> None:
    src = Source(name="openai_blog", kind="rss",
                 url="https://openai.com/blog/rss.xml", tags=("openai",))
    fetcher = _scripted({src.url: RSS_FIXTURE})
    items = pull_intel(tmp_path, [src], fetcher=fetcher)
    assert len(items) == 2
    titles = {i.title for i in items}
    assert "Function calling lands in GPT-5" in titles
    # Function-calling item should hit at least 'med' relevance via keywords.
    fc = next(i for i in items if "Function calling" in i.title)
    assert fc.relevance in ("med", "high")
    assert "openai" in fc.tags


def test_pull_atom_parses_entries(tmp_path: Path) -> None:
    src = Source(name="mcp_changelog", kind="atom",
                 url="https://github.com/modelcontextprotocol/servers/releases.atom",
                 tags=("mcp",))
    # Use a valid allowlisted host for the URL (github.com).
    fetcher = _scripted({src.url: ATOM_FIXTURE})
    items = pull_intel(tmp_path, [src], fetcher=fetcher)
    assert len(items) == 1
    assert "MCP" in items[0].title or "v0.42" in items[0].title
    # MCP keyword → high relevance.
    assert items[0].relevance == "high"


def test_pull_github_releases(tmp_path: Path) -> None:
    src = Source(name="openai_python_releases", kind="github_releases",
                 url="https://api.github.com/repos/openai/openai-python/releases",
                 tags=("openai", "sdk"))
    fetcher = _scripted({src.url: GITHUB_FIXTURE})
    items = pull_intel(tmp_path, [src], fetcher=fetcher)
    assert len(items) == 2
    assert all(i.url.startswith("https://github.com/openai/openai-python/releases/tag/")
               for i in items)


def test_pull_json_changelog(tmp_path: Path) -> None:
    src = Source(name="composio", kind="json_changelog",
                 url="https://github.com/ComposioHQ/composio/changelog.json",
                 tags=("composio",))
    fetcher = _scripted({src.url: JSON_CHANGELOG_FIXTURE})
    items = pull_intel(tmp_path, [src], fetcher=fetcher)
    assert len(items) == 1
    assert "MCP" in items[0].title


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def test_dedup_across_runs(tmp_path: Path) -> None:
    src = Source(name="openai_blog", kind="rss",
                 url="https://openai.com/blog/rss.xml", tags=("openai",))
    fetcher = _scripted({src.url: RSS_FIXTURE})
    first = pull_intel(tmp_path, [src], fetcher=fetcher)
    assert len(first) == 2

    # Second run with same fixture → no new items.
    second = pull_intel(tmp_path, [src], fetcher=fetcher)
    assert second == [], "items already seen must be deduped"

    # seen.json persisted.
    seen = tmp_path / "intel" / "seen.json"
    assert seen.exists()
    seen_set = set(json.loads(seen.read_text()))
    # 2 items hashed.
    assert len(seen_set) == 2


def test_hash_stable_per_source_url() -> None:
    h1 = _hash("openai_blog", "https://openai.com/x")
    h2 = _hash("openai_blog", "https://openai.com/x")
    assert h1 == h2
    h3 = _hash("openai_blog", "https://openai.com/y")
    assert h1 != h3


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def test_parse_date_handles_iso_and_rfc822() -> None:
    iso_ts = _parse_date("2026-04-22T10:00:00Z")
    assert iso_ts is not None and iso_ts > 0
    rss_ts = _parse_date("Mon, 21 Apr 2026 12:00:00 GMT")
    assert rss_ts is not None and rss_ts > 0


def test_strip_html_basics() -> None:
    s = _strip_html("<p>Hello <b>world</b>&amp; friends</p>")
    assert "<" not in s and ">" not in s
    assert "Hello" in s and "world" in s


def test_keyword_relevance_levels() -> None:
    assert keyword_relevance("MCP server adds tool catalog", "", []) == "high"
    assert keyword_relevance("Claude Sonnet 4.5 ships", "", []) == "med"
    assert keyword_relevance("Generic blog post", "Lorem ipsum", []) == "low"


# ---------------------------------------------------------------------------
# store_items
# ---------------------------------------------------------------------------

def test_store_items_idempotent_daily_json(tmp_path: Path) -> None:
    items = [
        normalize_item(source="openai_blog", title="Function calling",
                       url="https://openai.com/blog/function-calling",
                       summary="tool use", ts=time.time(), tags=["openai"]),
        normalize_item(source="openai_blog", title="Roundup",
                       url="https://openai.com/blog/roundup",
                       summary="generic", ts=time.time(), tags=["openai"]),
    ]
    today = "2026-04-26"
    meta1 = store_items(tmp_path, items, write_vault=False, write_genome=False, today=today)
    assert meta1["json_added"] == 2
    p = Path(meta1["day_path"])
    assert p.exists()
    parsed = json.loads(p.read_text())
    assert len(parsed) == 2

    # Re-run with same items → no duplicates.
    meta2 = store_items(tmp_path, items, write_vault=False, write_genome=False, today=today)
    assert meta2["json_added"] == 0
    assert meta2["json_total"] == 2


def test_build_intel_digest_groups_by_source_and_relevance() -> None:
    items = [
        normalize_item(source="A", title="MCP server v2", url="https://github.com/x/y/1",
                       summary="MCP", ts=1.0, tags=["mcp"]),
        normalize_item(source="A", title="Generic post", url="https://github.com/x/y/2",
                       summary="news", ts=2.0, tags=[]),
        normalize_item(source="B", title="Sonnet 4.5", url="https://www.anthropic.com/news/x",
                       summary="model", ts=3.0, tags=["claude"]),
    ]
    d = build_intel_digest(items)
    assert "A" in d.by_source and "B" in d.by_source
    md = d.to_markdown()
    assert "MCP server v2" in md
    assert "Sonnet 4.5" in md
    ctx = d.to_recursion_context()
    # Should include high-relevance first.
    assert ctx.index("MCP") < ctx.index("Sonnet")
