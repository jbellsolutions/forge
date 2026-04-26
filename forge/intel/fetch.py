"""Fetch intel items from configured sources.

stdlib-only fetching: `urllib.request` for HTTP, `xml.etree.ElementTree`
for RSS/Atom, `json` for GitHub releases. No `requests`, no `feedparser`,
no `httpx` in the base install. Domain allowlist enforced before every
HTTP call. Per-source timeout + small retry. Dedupe across runs via
`<home>/intel/seen.json` keyed by `sha256(source|url)`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from .normalize import IntelItem, normalize_item
from .sources import Source, is_allowed, load_sources


log = logging.getLogger("forge.intel.fetch")

DEFAULT_TIMEOUT = 12  # seconds; wall-clock per request
USER_AGENT = "forge-intel/0.1 (+https://github.com/jbellsolutions/forge)"
MAX_BYTES = 4 * 1024 * 1024  # 4 MB hard cap per fetch


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------

def pull_intel(
    home: str | Path,
    sources: list[Source] | None = None,
    *,
    fetcher: Any = None,
    now: float | None = None,
) -> list[IntelItem]:
    """Fetch all sources, dedupe vs `seen.json`, return new items.

    `fetcher` is an injectable callable `(url) -> bytes` for tests. The
    real implementation calls `_http_get`. Items already in `seen.json`
    are skipped; new items are appended to `seen.json` and persisted on
    success.
    """
    home_p = Path(home)
    intel_dir = home_p / "intel"
    intel_dir.mkdir(parents=True, exist_ok=True)
    seen_path = intel_dir / "seen.json"
    seen: set[str] = _load_seen(seen_path)
    src_list = sources if sources is not None else load_sources(home_p)
    fetch = fetcher or _http_get
    out: list[IntelItem] = []
    now_ts = now if now is not None else time.time()

    for src in src_list:
        if not is_allowed(src.url):
            log.warning("intel: source %s url %s not in allowlist; skipping",
                        src.name, src.url)
            continue
        try:
            raw = fetch(src.url)
        except Exception as e:  # noqa: BLE001
            log.warning("intel: fetch failed for %s (%s)", src.name, e)
            continue
        if not raw:
            continue
        try:
            parsed = _parse_for_kind(src, raw, now_ts=now_ts)
        except Exception as e:  # noqa: BLE001
            log.warning("intel: parse failed for %s (%s)", src.name, e)
            continue
        for item in parsed:
            key = _hash(src.name, item.url)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)

    _save_seen(seen_path, seen)
    return out


# ---------------------------------------------------------------------------
# Parsers per source kind
# ---------------------------------------------------------------------------

def _parse_for_kind(src: Source, raw: bytes, *, now_ts: float) -> list[IntelItem]:
    if src.kind == "rss":
        return _parse_rss(src, raw, now_ts=now_ts)
    if src.kind == "atom":
        return _parse_atom(src, raw, now_ts=now_ts)
    if src.kind == "github_releases":
        return _parse_github_releases(src, raw)
    if src.kind == "json_changelog":
        return _parse_json_changelog(src, raw, now_ts=now_ts)
    if src.kind == "html":
        return _parse_html_titles(src, raw, now_ts=now_ts)
    return []


def _parse_rss(src: Source, raw: bytes, *, now_ts: float) -> list[IntelItem]:
    out: list[IntelItem] = []
    root = ET.fromstring(raw)
    # Both <rss><channel><item> and bare <item>.
    items = root.findall(".//item")
    for el in items[:30]:
        title = (el.findtext("title") or "").strip()
        link = (el.findtext("link") or "").strip()
        desc = (el.findtext("description") or el.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or "").strip()
        pub = el.findtext("pubDate") or ""
        ts = _parse_date(pub) or now_ts
        if not (title and link):
            continue
        out.append(normalize_item(
            source=src.name, title=title, url=link,
            summary=_strip_html(desc), ts=ts, tags=list(src.tags),
        ))
    return out


def _parse_atom(src: Source, raw: bytes, *, now_ts: float) -> list[IntelItem]:
    """Parse an Atom feed. Note: Python 3.14 makes `Element.__bool__` False
    for elements with no children, so we use `is not None` for safety —
    `el.find(...) or el.find(...)` would short-circuit even when the first
    find succeeded but matched a self-closing tag like `<link href="..."/>`.
    """
    out: list[IntelItem] = []
    root = ET.fromstring(raw)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = root.findall(".//a:entry", ns)
    if not entries:
        entries = root.findall(".//entry")
    for el in entries[:30]:
        title = (el.findtext("a:title", default="", namespaces=ns)
                 or el.findtext("title", default="")).strip()
        link_el = el.find("a:link", ns)
        if link_el is None:
            link_el = el.find("link")
        link = link_el.get("href", "") if link_el is not None else ""
        summary = (el.findtext("a:summary", default="", namespaces=ns)
                   or el.findtext("summary", default="")).strip()
        upd = (el.findtext("a:updated", default="", namespaces=ns)
               or el.findtext("updated", default=""))
        ts = _parse_date(upd) or now_ts
        if not (title and link):
            continue
        out.append(normalize_item(
            source=src.name, title=title, url=link,
            summary=_strip_html(summary), ts=ts, tags=list(src.tags),
        ))
    return out


def _parse_github_releases(src: Source, raw: bytes) -> list[IntelItem]:
    out: list[IntelItem] = []
    data = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(data, list):
        return out
    for rel in data[:20]:
        if not isinstance(rel, dict):
            continue
        title = rel.get("name") or rel.get("tag_name") or "release"
        url = rel.get("html_url", "")
        body = (rel.get("body") or "")
        published = rel.get("published_at") or rel.get("created_at") or ""
        ts = _parse_date(published) or time.time()
        if not url:
            continue
        out.append(normalize_item(
            source=src.name, title=str(title), url=url,
            summary=body, ts=ts, tags=list(src.tags),
        ))
    return out


def _parse_json_changelog(src: Source, raw: bytes, *, now_ts: float) -> list[IntelItem]:
    """Generic JSON changelog: expects a top-level list of
    `{title, url, summary, ts}` items. Tolerant to missing fields."""
    out: list[IntelItem] = []
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return out
    if not isinstance(data, list):
        return out
    for item in data[:30]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", ""))
        url = str(item.get("url", ""))
        if not (title and url):
            continue
        out.append(normalize_item(
            source=src.name, title=title, url=url,
            summary=str(item.get("summary", "")),
            ts=float(item.get("ts") or now_ts),
            tags=list(src.tags),
        ))
    return out


_TITLE_RE = re.compile(r'<title[^>]*>([^<]+)</title>', re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r'<h1[^>]*>(.+?)</h1>', re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r'<a\s+[^>]*href="(/news/[^"]+|https://www\.anthropic\.com/news/[^"]+)"',
                      re.IGNORECASE)


def _parse_html_titles(src: Source, raw: bytes, *, now_ts: float) -> list[IntelItem]:
    """Best-effort extract of title + first H1 + a few news links from a
    plain HTML page. Used as a last-resort source kind for sites without
    a feed."""
    text = raw.decode("utf-8", errors="replace")
    out: list[IntelItem] = []
    page_title_m = _TITLE_RE.search(text)
    page_title = (page_title_m.group(1) if page_title_m else "page").strip()
    h1_m = _H1_RE.search(text)
    h1 = _strip_html(h1_m.group(1)) if h1_m else ""
    out.append(normalize_item(
        source=src.name, title=h1 or page_title, url=src.url,
        summary=_strip_html(text[:600]),
        ts=now_ts, tags=list(src.tags),
    ))
    # Anthropic-style news link discovery: cap at 5 links to avoid spam.
    seen_urls: set[str] = {src.url}
    for m in _LINK_RE.finditer(text):
        href = m.group(1)
        if href.startswith("/"):
            href = "https://www.anthropic.com" + href
        if href in seen_urls:
            continue
        seen_urls.add(href)
        if not is_allowed(href):
            continue
        out.append(normalize_item(
            source=src.name, title=href.rsplit("/", 1)[-1].replace("-", " ").title()[:160],
            url=href, summary="", ts=now_ts, tags=list(src.tags),
        ))
        if len(out) >= 6:
            break
    return out


# ---------------------------------------------------------------------------
# HTTP, dedup, helpers
# ---------------------------------------------------------------------------

def _http_get(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    """Minimal stdlib GET. Raises on non-2xx, caps body at MAX_BYTES."""
    if not is_allowed(url):
        raise PermissionError(f"url not in allowlist: {url}")
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,application/xml,text/html;q=0.9"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - allowlist enforced
        if resp.status >= 400:
            raise urllib.error.HTTPError(url, resp.status, "fetch failed", resp.headers, None)
        return resp.read(MAX_BYTES)


def _load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(str(x) for x in data)
        if isinstance(data, dict):
            return set(data.keys())
    except (json.JSONDecodeError, OSError):
        pass
    return set()


def _save_seen(path: Path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(seen)), encoding="utf-8")


def _hash(source: str, url: str) -> str:
    return hashlib.sha256(f"{source}|{url}".encode("utf-8")).hexdigest()[:16]


def _parse_date(s: str) -> float | None:
    if not s:
        return None
    s = s.strip()
    # ISO 8601
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        pass
    # RFC 822 (RSS)
    try:
        return parsedate_to_datetime(s).timestamp()
    except (TypeError, ValueError):
        pass
    return None


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(s: str) -> str:
    """Crude HTML tag stripper. Good enough for summaries — we already cap
    summary length downstream."""
    if not s:
        return ""
    out = _HTML_TAG_RE.sub(" ", s)
    return _WS_RE.sub(" ", out).strip()
