"""Cross-project genome — ReasoningBank at ~/.forge/genome.json.

Compounding learnings live here; each project's working memory stays under
its own .claude/forge/. Use `genome()` from any project to read/write the
shared bank.
"""
from __future__ import annotations

from pathlib import Path

from .embeddings import Embedder, hash_embedder
from .reasoning_bank import ReasoningBank


def genome_path() -> Path:
    return Path.home() / ".forge" / "genome.json"


_singleton: ReasoningBank | None = None


def genome(embedder: Embedder | None = None) -> ReasoningBank:
    """Process-wide singleton ReasoningBank rooted at ~/.forge/genome.json."""
    global _singleton
    if _singleton is None:
        path = genome_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _singleton = ReasoningBank(path=path, embedder=embedder or hash_embedder())
    return _singleton


def reset_singleton() -> None:
    """Test helper: drop the cached genome."""
    global _singleton
    _singleton = None
