"""Normalize raw intel items into the canonical IntelItem shape.

`IntelItem` is the unit forge stores, indexes, ranks, and feeds into the
recursion proposer. Normalization steps:

1. truncate summary to 400 chars (cheap; bounds memory)
2. assign relevance ∈ {high, med, low} via simple keyword match against
   forge's domain — avoids paying for an LLM call when keywords already
   give a clean signal
3. (optional) Haiku one-shot for items the keyword pass marks "low" but
   that have ambiguous wording — only invoked when an Anthropic key is
   present AND `use_llm=True` is passed by the caller. No hard dep.

Tests run against canned inputs only; the LLM path is gated and skipped
when no key is configured.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any


log = logging.getLogger("forge.intel.normalize")


@dataclass
class IntelItem:
    source: str
    title: str
    url: str
    summary: str
    ts: float                                  # epoch seconds
    tags: list[str] = field(default_factory=list)
    relevance: str = "low"                     # "high" | "med" | "low"

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# Forge-domain keywords. Tuned for what would actually shift a harness's
# behavior — not generic AI hype.
HIGH_KEYWORDS = re.compile(
    r"\b(mcp|model context protocol|tool use|tool[- ]calling|agent harness|"
    r"reasoning bank|skill autosynth|circuit breaker|computer use|"
    r"context window|prompt cach(?:e|ing)|extended thinking|agentic)\b",
    re.IGNORECASE,
)

MED_KEYWORDS = re.compile(
    r"\b(claude|sonnet|haiku|opus|gpt-?[345]|o[1-9]|deepseek|llama|gemini|"
    r"composio|sdk|cli|swarm|router|consensus|multi[- ]agent|eval|benchmark|"
    r"function call|tool registry|sandbox|provider profile|api stable)\b",
    re.IGNORECASE,
)


def keyword_relevance(title: str, summary: str, tags: list[str]) -> str:
    """Cheap keyword-based relevance scorer. Returns 'high', 'med', or 'low'."""
    blob = " ".join([title or "", summary or "", " ".join(tags or [])])
    if HIGH_KEYWORDS.search(blob):
        return "high"
    if MED_KEYWORDS.search(blob):
        return "med"
    return "low"


def normalize_item(
    *,
    source: str,
    title: str,
    url: str,
    summary: str,
    ts: float,
    tags: list[str] | None = None,
) -> IntelItem:
    tags = list(tags or [])
    summary = (summary or "").strip()
    if len(summary) > 400:
        summary = summary[:397] + "…"
    title = (title or "").strip()[:240]
    rel = keyword_relevance(title, summary, tags)
    return IntelItem(
        source=source, title=title, url=url, summary=summary, ts=ts,
        tags=tags, relevance=rel,
    )


def maybe_haiku_rerank(items: list[IntelItem], *, use_llm: bool = False) -> list[IntelItem]:
    """Optionally re-rank ambiguous items via Haiku.

    Only runs when:
    - `use_llm=True` AND
    - `ANTHROPIC_API_KEY` is set AND
    - the `anthropic` package is importable

    Conservative by design: re-rank only items currently scored "low".
    Bumps obvious harness-relevant items to "med". Never demotes high/med
    (that's the keyword pass's job). Silent no-op on any failure.
    """
    if not use_llm or not items:
        return items
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return items
    candidates = [i for i in items if i.relevance == "low"]
    if not candidates:
        return items
    try:
        import anthropic  # type: ignore
    except ImportError:
        return items
    # Single batched call — keep cost trivial (~fractions of a cent).
    try:
        client = anthropic.Anthropic()
        prompt = (
            "For each item, respond with one line per item: 'KEEP' if the item "
            "is generic AI/tech news with no direct bearing on building agent "
            "harnesses, MCP servers, tool-use, or model providers; 'BUMP' if it "
            "describes something an agent-harness builder should react to.\n\n"
            + "\n".join(f"{i+1}. [{c.source}] {c.title}: {c.summary[:160]}"
                        for i, c in enumerate(candidates))
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
        verdicts = re.findall(r"\b(KEEP|BUMP)\b", text.upper())
        for c, v in zip(candidates, verdicts):
            if v == "BUMP":
                c.relevance = "med"
    except Exception as e:  # noqa: BLE001
        log.warning("haiku rerank failed (%s); proceeding with keyword-only relevance", e)
    return items
