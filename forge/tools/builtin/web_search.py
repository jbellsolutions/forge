"""WebSearchTool — search the open web.

Backend selection (in priority order, first that's available wins):
1. **Tavily** (preferred — agent-friendly JSON, free tier, good summaries)
   — requires `TAVILY_API_KEY` env var.
2. **Brave Search** — requires `BRAVE_API_KEY`.
3. **DuckDuckGo HTML** — no key required; stdlib urllib + regex extraction.
   Lower quality, but always available so the auto-research sub-agent
   isn't dead in the water on a fresh install.

All backends are lazy-imported. No hard dependency on any vendor SDK.
The tool returns a fixed JSON shape so the agent's reasoning is stable
across backends:

    {"query": "...", "results": [{"title": "...", "url": "...",
                                  "snippet": "...", "source": "tavily|brave|ddg"}]}
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, ClassVar

from ...kernel.types import AgentDef, ToolCall, ToolResult
from ..base import Tool


log = logging.getLogger("forge.tools.web_search")

_USER_AGENT = "forge-web-search/0.1 (+https://github.com/jbellsolutions/forge)"


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the open web. Returns up to N results (default 5). "
        "Backend chosen automatically: Tavily > Brave > DuckDuckGo (no-key fallback). "
        "Read-only; no scraping, no JavaScript."
    )
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {
                "type": "integer", "default": 5, "minimum": 1, "maximum": 10,
            },
        },
        "required": ["query"],
    }
    tier = "mcp"
    concurrency_safe = True  # read-only

    def __init__(self, *, backend: str | None = None, searcher=None) -> None:
        # `backend` forces a specific backend ("tavily"|"brave"|"ddg"); None autodetects.
        self.backend = backend
        # Injectable for tests; signature: (query, max_results, backend) -> list[dict]
        self._searcher = searcher

    def _pick_backend(self) -> str:
        if self.backend:
            return self.backend
        if os.environ.get("TAVILY_API_KEY", "").strip():
            return "tavily"
        if os.environ.get("BRAVE_API_KEY", "").strip():
            return "brave"
        return "ddg"

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        query = (call.arguments.get("query") or "").strip()
        if not query:
            return ToolResult(call.id, self.name, "error: query required", is_error=True)
        max_results = int(call.arguments.get("max_results", 5))
        backend = self._pick_backend()
        try:
            if self._searcher is not None:
                results = self._searcher(query, max_results, backend)
            elif backend == "tavily":
                results = _search_tavily(query, max_results)
            elif backend == "brave":
                results = _search_brave(query, max_results)
            else:
                results = _search_ddg(query, max_results)
        except Exception as e:  # noqa: BLE001
            return ToolResult(
                call.id, self.name,
                f"error: search failed via {backend}: {e}",
                is_error=True,
            )
        return ToolResult(
            call.id, self.name,
            json.dumps({"query": query, "backend": backend, "results": results}, default=str),
            metadata={"backend": backend, "result_count": len(results)},
        )


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def _search_tavily(query: str, max_results: int) -> list[dict[str, Any]]:
    """Tavily JSON API. Lazy-imports `tavily-python`; falls back to direct HTTP."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    try:
        from tavily import TavilyClient  # type: ignore
        client = TavilyClient(api_key=api_key)
        resp = client.search(query=query, max_results=max_results)
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": r.get("content", "")[:400], "source": "tavily"}
            for r in resp.get("results", [])
        ]
    except ImportError:
        # Direct HTTP — tavily endpoint is documented + stable.
        body = json.dumps({
            "api_key": api_key, "query": query, "max_results": max_results,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
            data = json.loads(r.read().decode("utf-8"))
        return [
            {"title": x.get("title", ""), "url": x.get("url", ""),
             "snippet": x.get("content", "")[:400], "source": "tavily"}
            for x in data.get("results", [])
        ]


def _search_brave(query: str, max_results: int) -> list[dict[str, Any]]:
    api_key = os.environ.get("BRAVE_API_KEY", "")
    qs = urllib.parse.urlencode({"q": query, "count": max_results})
    req = urllib.request.Request(
        f"https://api.search.brave.com/res/v1/web/search?{qs}",
        headers={
            "X-Subscription-Token": api_key,
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
        data = json.loads(r.read().decode("utf-8"))
    return [
        {"title": x.get("title", ""), "url": x.get("url", ""),
         "snippet": (x.get("description") or "")[:400], "source": "brave"}
        for x in (data.get("web", {}).get("results", []) or [])[:max_results]
    ]


# DuckDuckGo HTML scraping — last-resort backend. Quality is mediocre but
# it's free + keyless, so the auto-research sub-agent works on a fresh install.

_DDG_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_DDG_SNIPPET_RE = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", s)).strip()


def _search_ddg(query: str, max_results: int) -> list[dict[str, Any]]:
    qs = urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(
        f"https://html.duckduckgo.com/html/?{qs}",
        headers={"User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - public search engine
        html = r.read(500_000).decode("utf-8", errors="replace")
    titles = _DDG_RESULT_RE.findall(html)
    snippets = [_strip(s) for s in _DDG_SNIPPET_RE.findall(html)]
    results: list[dict[str, Any]] = []
    for i, (url, title) in enumerate(titles[:max_results]):
        # DDG wraps URLs as `//duckduckgo.com/l/?uddg=<encoded>` — extract the real one.
        real_url = url
        m = re.search(r"uddg=([^&]+)", url)
        if m:
            real_url = urllib.parse.unquote(m.group(1))
        elif url.startswith("//"):
            real_url = "https:" + url
        results.append({
            "title": _strip(title), "url": real_url,
            "snippet": snippets[i] if i < len(snippets) else "",
            "source": "ddg",
        })
    return results
