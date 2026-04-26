"""Skill search — vector index over skill body + outcome history.

Lets the agent call a `find_skill_for(task)` tool. Phase 6 reuses the
ReasoningBank-style hash embedder; production swaps for real embeddings.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..memory.embeddings import Embedder, hash_embedder
from ..memory.reasoning_bank import _cosine
from .skill import SkillStore


@dataclass
class SkillHit:
    name: str
    version: str
    score: float
    body_excerpt: str


class SkillSearchIndex:
    def __init__(self, store: SkillStore, embedder: Embedder | None = None) -> None:
        self.store = store
        self._embed = embedder or hash_embedder()
        self._index: dict[str, list[float]] = {}
        self.rebuild()

    def rebuild(self) -> None:
        self._index = {}
        for skill in self.store.list_skills():
            try:
                body = self.store.read_skill(skill)
            except FileNotFoundError:
                continue
            runs = self.store.runs(skill)
            outcomes = " ".join(r.output[:120] for r in runs[-20:])
            corpus = f"{skill}\n{body}\n{outcomes}"
            self._index[skill] = self._embed(corpus)

    def search(self, query: str, k: int = 5) -> list[SkillHit]:
        q = self._embed(query)
        scored = [(name, _cosine(q, vec)) for name, vec in self._index.items()]
        scored.sort(reverse=True, key=lambda x: x[1])
        out: list[SkillHit] = []
        for name, score in scored[:k]:
            try:
                body = self.store.read_skill(name)
            except FileNotFoundError:
                continue
            out.append(SkillHit(
                name=name, version=self.store.current_version(name),
                score=score, body_excerpt=body[:240],
            ))
        return out
