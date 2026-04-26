"""Group + rank IntelItems into a compact daily digest the recursion
proposer can consume as `intel_context`.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .normalize import IntelItem


@dataclass
class IntelDigest:
    items: list[IntelItem]
    by_source: dict[str, list[IntelItem]] = field(default_factory=dict)
    by_tag: dict[str, list[IntelItem]] = field(default_factory=dict)

    def to_recursion_context(self, max_items: int = 12) -> str:
        """Render as a compact bullet list for prompt injection."""
        ranked = sorted(
            self.items,
            key=lambda i: (
                {"high": 0, "med": 1, "low": 2}.get(i.relevance, 3),
                -i.ts,
            ),
        )[:max_items]
        if not ranked:
            return "(no high/med-relevance industry signals today)"
        lines = ["Recent industry signals (relevance | source | title)"]
        for i in ranked:
            lines.append(f"- [{i.relevance}] {i.source}: {i.title} ({i.url})")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        if not self.items:
            return "*No new industry signals.*"
        lines = ["### Industry signals"]
        for src, group in sorted(self.by_source.items()):
            high_med = [i for i in group if i.relevance in ("high", "med")]
            if not high_med:
                continue
            lines.append(f"\n**{src}**")
            for i in high_med[:5]:
                lines.append(f"- [{i.relevance}] {i.title} — {i.url}")
        return "\n".join(lines)


def build_intel_digest(items: list[IntelItem]) -> IntelDigest:
    by_source: dict[str, list[IntelItem]] = defaultdict(list)
    by_tag: dict[str, list[IntelItem]] = defaultdict(list)
    for it in items:
        by_source[it.source].append(it)
        for tag in it.tags:
            by_tag[tag].append(it)
    return IntelDigest(items=list(items), by_source=dict(by_source), by_tag=dict(by_tag))
