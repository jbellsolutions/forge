"""WebFetchTool — fetch a URL and return cleaned text.

stdlib-only. Domain allowlist configurable via constructor (defaults to
the same allowlist forge.intel uses) + env-extensible. Size-capped at
8KB by default to keep agent context costs bounded. Hard timeout.
"""
from __future__ import annotations

import logging
import os
import re
import urllib.error
import urllib.request
from typing import ClassVar

from ...kernel.types import AgentDef, ToolCall, ToolResult
from ..base import Tool


log = logging.getLogger("forge.tools.web_fetch")


# Default allowlist mirrors forge.intel.sources.DOMAIN_ALLOWLIST so the
# auto-research sub-agent can fetch the same hosts intel pulls from.
# Extensible via FORGE_WEB_FETCH_HOSTS=host1,host2,... in the env.
_DEFAULT_HOSTS: frozenset[str] = frozenset({
    "anthropic.com", "www.anthropic.com", "docs.anthropic.com",
    "openai.com", "platform.openai.com",
    "github.com", "api.github.com", "raw.githubusercontent.com",
    "modelcontextprotocol.io",
    "ai.googleblog.com", "googleblog.com", "blog.google", "deepmind.google",
    "blog.cloudflare.com", "huggingface.co",
})

_USER_AGENT = "forge-web-fetch/0.1 (+https://github.com/jbellsolutions/forge)"
_MAX_BYTES = 8 * 1024  # 8KB default cap

_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _allowed_hosts() -> frozenset[str]:
    extra = os.environ.get("FORGE_WEB_FETCH_HOSTS", "").strip()
    if not extra:
        return _DEFAULT_HOSTS
    return frozenset(_DEFAULT_HOSTS | {h.strip().lower() for h in extra.split(",") if h.strip()})


class WebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "Fetch a single URL (HTTP GET). Returns the page <title> + first ~8KB of "
        "cleaned text. Domain-allowlisted; fails if the host isn't on the list. "
        "Read-only; no cookies, no JavaScript."
    )
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute URL to fetch."},
            "max_bytes": {
                "type": "integer",
                "description": "Optional cap on body size (default 8192).",
                "minimum": 256, "maximum": 65536,
            },
        },
        "required": ["url"],
    }
    tier = "mcp"
    concurrency_safe = True  # read-only

    def __init__(self, allowed_hosts: frozenset[str] | None = None,
                 default_max_bytes: int = _MAX_BYTES,
                 timeout: float = 12.0,
                 fetcher=None):
        self.allowed_hosts = allowed_hosts or _allowed_hosts()
        self.default_max_bytes = default_max_bytes
        self.timeout = timeout
        # Injectable for tests; signature: (url, *, timeout, max_bytes) -> bytes
        self._fetcher = fetcher

    def _is_allowed(self, url: str) -> bool:
        try:
            from urllib.parse import urlparse
            host = (urlparse(url).hostname or "").lower()
        except Exception:  # noqa: BLE001
            return False
        return host in self.allowed_hosts

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        url = call.arguments.get("url", "")
        max_bytes = int(call.arguments.get("max_bytes", self.default_max_bytes))
        if not url:
            return ToolResult(call.id, self.name, "error: url required", is_error=True)
        if not self._is_allowed(url):
            return ToolResult(
                call.id, self.name,
                f"error: host not in allowlist; ask the operator to add it via "
                f"FORGE_WEB_FETCH_HOSTS env var. url={url!r}",
                is_error=True,
            )
        try:
            raw = (self._fetcher or _default_fetcher)(
                url, timeout=self.timeout, max_bytes=max_bytes,
            )
        except urllib.error.HTTPError as e:
            return ToolResult(call.id, self.name, f"error: HTTP {e.code} {e.reason}", is_error=True)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return ToolResult(call.id, self.name, f"error: fetch failed: {e}", is_error=True)
        text = raw.decode("utf-8", errors="replace")
        title_m = _TITLE_RE.search(text)
        title = title_m.group(1).strip() if title_m else url
        # Strip tags + collapse whitespace.
        body = _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()[:max_bytes]
        return ToolResult(
            call.id, self.name,
            f"# {title}\nURL: {url}\n\n{body}",
            metadata={"url": url, "title": title, "bytes": len(raw)},
        )


def _default_fetcher(url: str, *, timeout: float, max_bytes: int) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT,
                 "Accept": "text/html,application/json,text/plain;q=0.9"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - allowlist enforced
        if resp.status >= 400:
            raise urllib.error.HTTPError(url, resp.status, "fetch failed", resp.headers, None)
        return resp.read(max_bytes)
