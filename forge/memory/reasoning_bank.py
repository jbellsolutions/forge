"""ReasoningBank — Ruflo-shaped pattern memory.

5-stage loop: RETRIEVE -> JUDGE -> DISTILL -> CONSOLIDATE -> ROUTE.
Backed by a pluggable embedder (default = hash; swap for OpenAI / Voyage / ONNX).
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .embeddings import Embedder, hash_embedder


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True))


# Back-compat shim: tests / older callers still import _hash_embed
_hash_embed = hash_embedder()


@dataclass
class Memory:
    id: str
    text: str
    embedding: list[float]
    score: float = 0.0          # outcome score from JUDGE
    confidence: float = 0.5     # rises with reuse, decays with failures
    used: int = 0
    created_at: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class ReasoningBank:
    """RETRIEVE -> JUDGE -> DISTILL -> CONSOLIDATE -> ROUTE."""

    def __init__(
        self,
        path: str | Path | None = None,
        embedder: Embedder | None = None,
        confidence_floor: float = 0.2,
    ) -> None:
        self._mems: dict[str, Memory] = {}
        self._embed = embedder or hash_embedder()
        self._path = Path(path) if path else None
        self._floor = confidence_floor
        if self._path and self._path.exists():
            self._load()

    # 1. RETRIEVE ----------------------------------------------------------
    def retrieve(self, query: str, k: int = 5, min_confidence: float | None = None) -> list[Memory]:
        threshold = self._floor if min_confidence is None else min_confidence
        q = self._embed(query)
        scored = [
            (_cosine(q, m.embedding) * m.confidence, m)
            for m in self._mems.values() if m.confidence >= threshold
        ]
        scored.sort(reverse=True, key=lambda x: x[0])
        return [m for _, m in scored[:k]]

    # 2. JUDGE -------------------------------------------------------------
    def judge(self, mem_id: str, outcome_score: float) -> None:
        """Outcome score in [-1, 1]. Updates confidence with EWMA."""
        if mem_id not in self._mems:
            return
        m = self._mems[mem_id]
        m.score = outcome_score
        # EWMA confidence update
        delta = (outcome_score + 1) / 2  # map to [0, 1]
        m.confidence = 0.7 * m.confidence + 0.3 * delta
        m.used += 1

    # 3. DISTILL -----------------------------------------------------------
    def distill(self, raw: str, tags: list[str] | None = None) -> Memory:
        """Reduce a raw observation to a storable memory entry."""
        # Phase 5: keep raw; richer distillation hooks into a small LLM later.
        mid = hashlib.md5(raw.encode()).hexdigest()[:16]
        m = Memory(id=mid, text=raw, embedding=self._embed(raw), tags=tags or [])
        return m

    # 4. CONSOLIDATE -------------------------------------------------------
    def consolidate(self, memory: Memory) -> None:
        """Insert or merge into the bank."""
        existing = self._mems.get(memory.id)
        if existing:
            existing.confidence = min(1.0, existing.confidence + 0.05)
            existing.used += 1
        else:
            self._mems[memory.id] = memory
        self._save()

    # 5. ROUTE -------------------------------------------------------------
    def route(self, query: str, k: int = 3) -> str:
        """Return a short retrieved-context block for prompt injection."""
        hits = self.retrieve(query, k=k)
        if not hits:
            return ""
        lines = ["## Retrieved memories"]
        for m in hits:
            lines.append(f"- ({m.confidence:.2f}) {m.text}")
        return "\n".join(lines)

    # persistence ----------------------------------------------------------
    def _save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            mid: {
                "id": m.id, "text": m.text, "embedding": m.embedding,
                "score": m.score, "confidence": m.confidence, "used": m.used,
                "created_at": m.created_at, "tags": m.tags, "extra": m.extra,
            } for mid, m in self._mems.items()
        }
        self._path.write_text(json.dumps(data))

    def _load(self) -> None:
        if not self._path:
            return
        data = json.loads(self._path.read_text())
        for mid, d in data.items():
            self._mems[mid] = Memory(**d)

    def __len__(self) -> int:
        return len(self._mems)
