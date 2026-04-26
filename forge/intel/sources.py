"""Intel sources — what forge tracks daily for industry signal.

A `Source` is a (name, kind, url, tags) tuple plus a small parse policy.
The default list ships inline (curated for forge's domain). Users can
override via `~/.forge/intel/sources.yaml`. Every fetched URL is checked
against `DOMAIN_ALLOWLIST` first — a typo'd source can't pivot to
arbitrary endpoints.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse


SourceKind = Literal["rss", "atom", "github_releases", "json_changelog", "html"]


@dataclass(frozen=True)
class Source:
    name: str
    kind: SourceKind
    url: str
    tags: tuple[str, ...] = field(default_factory=tuple)


# Hosts forge will fetch from. Anything else is rejected at fetch time.
# Add hosts here BEFORE adding sources that target them.
DOMAIN_ALLOWLIST: frozenset[str] = frozenset({
    "anthropic.com",
    "www.anthropic.com",
    "docs.anthropic.com",
    "openai.com",
    "platform.openai.com",
    "github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    "modelcontextprotocol.io",
    "ai.googleblog.com",
    "googleblog.com",
    "blog.google",
    "deepmind.google",
    "blog.cloudflare.com",
    "huggingface.co",
})


# Default sources — sane starter set covering the SDKs forge competes with
# or builds on. Users can override with ~/.forge/intel/sources.yaml.
DEFAULT_SOURCES: tuple[Source, ...] = (
    Source(
        name="anthropic_news",
        kind="html",
        url="https://www.anthropic.com/news",
        tags=("anthropic", "claude", "model"),
    ),
    Source(
        name="openai_blog",
        kind="rss",
        url="https://openai.com/blog/rss.xml",
        tags=("openai", "model"),
    ),
    Source(
        name="anthropic_quickstarts_releases",
        kind="github_releases",
        url="https://api.github.com/repos/anthropics/anthropic-quickstarts/releases",
        tags=("anthropic", "sdk", "examples"),
    ),
    Source(
        name="claude_code_releases",
        kind="github_releases",
        url="https://api.github.com/repos/anthropics/claude-code/releases",
        tags=("anthropic", "claude-code", "cli"),
    ),
    Source(
        name="composio_releases",
        kind="github_releases",
        url="https://api.github.com/repos/ComposioHQ/composio/releases",
        tags=("composio", "tools", "mcp"),
    ),
    Source(
        name="mcp_python_sdk_releases",
        kind="github_releases",
        url="https://api.github.com/repos/modelcontextprotocol/python-sdk/releases",
        tags=("mcp", "sdk", "python"),
    ),
    Source(
        name="mcp_servers_releases",
        kind="github_releases",
        url="https://api.github.com/repos/modelcontextprotocol/servers/releases",
        tags=("mcp", "servers"),
    ),
    Source(
        name="openai_python_releases",
        kind="github_releases",
        url="https://api.github.com/repos/openai/openai-python/releases",
        tags=("openai", "sdk", "python"),
    ),
    Source(
        name="anthropic_sdk_python_releases",
        kind="github_releases",
        url="https://api.github.com/repos/anthropics/anthropic-sdk-python/releases",
        tags=("anthropic", "sdk", "python"),
    ),
    Source(
        name="autoagent_releases",
        kind="github_releases",
        url="https://api.github.com/repos/kevinrgu/autoagent/releases",
        tags=("autoagent", "harness", "research"),
    ),
)


def is_allowed(url: str) -> bool:
    """True if the URL's host is in DOMAIN_ALLOWLIST."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001
        return False
    return host.lower() in DOMAIN_ALLOWLIST


def load_sources(home: str | Path | None = None) -> list[Source]:
    """Return user override sources from `<home>/intel/sources.yaml` if it
    exists, else the default list. Malformed YAML falls back to defaults.

    YAML shape:
        sources:
          - name: foo
            kind: rss
            url: https://example.com/feed.xml
            tags: [tag1, tag2]
    """
    if home is None:
        return list(DEFAULT_SOURCES)
    p = Path(home) / "intel" / "sources.yaml"
    if not p.exists():
        return list(DEFAULT_SOURCES)
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return list(DEFAULT_SOURCES)
    raw = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return list(DEFAULT_SOURCES)
    out: list[Source] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            out.append(Source(
                name=str(item["name"]),
                kind=item["kind"],
                url=str(item["url"]),
                tags=tuple(item.get("tags") or []),
            ))
        except (KeyError, TypeError):
            continue
    return out or list(DEFAULT_SOURCES)
