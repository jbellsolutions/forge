"""Obsidian vault as a third memory backend.

A vault is a directory of markdown notes with optional YAML frontmatter and
[[wiki-links]]. Forge writes notes the agent produces, parses backlinks to
build a knowledge graph, and exposes search via filename + tag + body match.

Why all three (ReasoningBank + GitJournal + Obsidian)?
  - ReasoningBank: vector recall, decay, confidence — for "remind me of similar past work"
  - GitJournal: durable log of code/state changes — for "resume a killed run"
  - Obsidian: human-readable knowledge graph — for "open the vault and see what
    the agent has been learning". Wiki-links surface conceptual connections that
    vector search misses.

Layout (relative to vault root):
  inbox/         — raw observations the agent writes immediately
  daily/         — daily notes (YYYY-MM-DD.md)
  decisions/     — one note per Council/decision (auto-linked to actors + topics)
  skills/        — symlinks/copies of SKILL.md so the vault is the human view
  topics/        — concept notes the agent creates as wiki-link targets
  agents/        — one note per persona/agent that has run
"""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z][\w/-]*)")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

_SUBDIRS = ("inbox", "daily", "decisions", "skills", "topics", "agents")


@dataclass
class Note:
    path: Path                          # relative to vault root
    title: str
    body: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    backlinks: list[str] = field(default_factory=list)   # other notes linking here
    forward_links: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def _slugify(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s.strip())
    s = re.sub(r"\s+", "-", s).strip("-")
    return s.lower() or "note"


def _split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, raw[m.end():]


def _serialize(fm: dict[str, Any], body: str) -> str:
    if not fm:
        return body if body.endswith("\n") else body + "\n"
    return "---\n" + yaml.safe_dump(fm, sort_keys=True).strip() + "\n---\n\n" + body.lstrip()


class ObsidianVault:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.bootstrap()

    def bootstrap(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for d in _SUBDIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        # .obsidian/ marker so Obsidian recognizes the folder as a vault on first open
        (self.root / ".obsidian").mkdir(exist_ok=True)
        readme = self.root / "README.md"
        if not readme.exists():
            readme.write_text(
                "# Forge Vault\n\nAgent-curated knowledge graph. Open in Obsidian.\n"
                "Subfolders: inbox, daily, decisions, skills, topics, agents.\n"
            )

    # ---- writing ---------------------------------------------------------

    def write_note(
        self,
        title: str,
        body: str,
        *,
        folder: str = "inbox",
        tags: Iterable[str] | None = None,
        links: Iterable[str] | None = None,
        frontmatter: dict[str, Any] | None = None,
        timestamp: bool = True,
    ) -> Path:
        """Create or overwrite a note. Returns the absolute path."""
        if folder not in _SUBDIRS:
            raise ValueError(f"unknown folder {folder!r}; allowed: {_SUBDIRS}")
        fm = dict(frontmatter or {})
        if timestamp and "created" not in fm:
            fm["created"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if tags:
            fm["tags"] = sorted(set(list(fm.get("tags", [])) + list(tags)))
        body = body.rstrip()
        if links:
            link_block = " ".join(f"[[{lk}]]" for lk in links)
            body += f"\n\n## Links\n{link_block}\n"
        path = self.root / folder / f"{_slugify(title)}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_serialize(fm, f"# {title}\n\n{body}\n"))
        return path

    def append_inbox(self, observation: str, tags: Iterable[str] | None = None) -> Path:
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        return self.write_note(f"obs-{ts}", observation, folder="inbox", tags=tags)

    def daily_note(self, date: dt.date | None = None) -> Path:
        date = date or dt.date.today()
        return self.write_note(
            date.isoformat(), "", folder="daily",
            frontmatter={"date": date.isoformat()},
        )

    # ---- reading ---------------------------------------------------------

    def read_note(self, rel_or_title: str) -> Note | None:
        """Accepts a relative path (`decisions/ship-q4.md`) or a bare title."""
        candidates: list[Path] = []
        target = (self.root / rel_or_title)
        if target.exists() and target.is_file():
            candidates.append(target)
        else:
            slug = _slugify(rel_or_title)
            candidates.extend(self.root.rglob(f"{slug}.md"))
            candidates.extend(self.root.rglob(f"{rel_or_title}.md"))
        for p in candidates:
            if p.is_file():
                return self._load(p)
        return None

    def _load(self, path: Path) -> Note:
        raw = path.read_text(encoding="utf-8")
        fm, body = _split_frontmatter(raw)
        title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else path.stem
        forward = WIKI_LINK_RE.findall(body)
        tags = list(set(TAG_RE.findall(body)) | set(fm.get("tags", []) or []))
        return Note(
            path=path.relative_to(self.root),
            title=title, body=body,
            frontmatter=fm,
            forward_links=forward, tags=tags,
        )

    def all_notes(self) -> list[Note]:
        return [self._load(p) for p in self.root.rglob("*.md") if p.is_file()]

    # ---- graph -----------------------------------------------------------

    def backlinks(self, target_title: str) -> list[Note]:
        slug = _slugify(target_title)
        out: list[Note] = []
        for note in self.all_notes():
            for lk in note.forward_links:
                if _slugify(lk) == slug or lk.lower() == target_title.lower():
                    out.append(note)
                    break
        return out

    # ---- search ----------------------------------------------------------

    def search(self, query: str, *, k: int = 10, tags: Iterable[str] | None = None) -> list[Note]:
        """Filename + tag + body substring scoring. Cheap and works offline.

        For semantic search, run notes through ReasoningBank (see ObsidianBridge).
        """
        q = query.lower().strip()
        tag_set = set(tags or [])
        scored: list[tuple[float, Note]] = []
        for note in self.all_notes():
            score = 0.0
            if q in note.path.stem.lower():
                score += 3.0
            if q in note.title.lower():
                score += 2.0
            score += note.body.lower().count(q) * 0.5
            if tag_set and tag_set.intersection(note.tags):
                score += 1.0
            if score > 0 or (tag_set and tag_set.intersection(note.tags)):
                scored.append((score, note))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [n for _, n in scored[:k]]


# --- Bridge: feed notes into ReasoningBank for semantic recall ---------------

def index_into_reasoning_bank(vault: ObsidianVault, bank, *, folder: str | None = None) -> int:
    """Distill every note into a Memory and consolidate. Returns count indexed."""
    n = 0
    for note in vault.all_notes():
        if folder and not str(note.path).startswith(folder + "/"):
            continue
        text = f"{note.title}\n{note.body}".strip()
        if not text:
            continue
        m = bank.distill(text, tags=note.tags + ["obsidian"])
        m.extra["obsidian_path"] = str(note.path)
        bank.consolidate(m)
        n += 1
    return n
