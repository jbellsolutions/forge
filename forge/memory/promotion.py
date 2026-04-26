"""Promote high-confidence ReasoningBank memories into the Obsidian vault.

Rule: when a memory's confidence crosses `threshold` and it has been used at
least `min_used` times, write it as a `topics/<slug>.md` note (or update the
existing one). The vault becomes the human-browsable layer; the bank stays the
fast vector recall layer.

Idempotent: re-promoting an already-written topic updates the body but bumps a
`promoted_count` in frontmatter so you can see how often the agent re-affirms it.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .obsidian import ObsidianVault, _slugify, _split_frontmatter
from .reasoning_bank import ReasoningBank


@dataclass
class PromotionResult:
    promoted: list[str]   # memory ids written
    updated: list[str]    # memory ids whose existing note was updated
    skipped: int


def promote(
    bank: ReasoningBank,
    vault: ObsidianVault,
    *,
    threshold: float = 0.75,
    min_used: int = 2,
    folder: str = "topics",
) -> PromotionResult:
    promoted: list[str] = []
    updated: list[str] = []
    skipped = 0
    for mid, mem in bank._mems.items():
        if mem.confidence < threshold or mem.used < min_used:
            skipped += 1
            continue
        # Title from first line of memory text, slugified.
        first_line = mem.text.strip().splitlines()[0][:80] if mem.text.strip() else mid
        title = first_line
        slug = _slugify(title)
        note_path = vault.root / folder / f"{slug}.md"
        body = (
            f"{mem.text}\n\n"
            f"---\n"
            f"_promoted from ReasoningBank · confidence={mem.confidence:.2f} · used={mem.used} · "
            f"score={mem.score:+.2f}_"
        )
        tags = sorted(set(list(mem.tags) + ["promoted"]))
        if note_path.exists():
            existing = note_path.read_text(encoding="utf-8")
            fm, _existing_body = _split_frontmatter(existing)
            fm["promoted_count"] = int(fm.get("promoted_count", 1)) + 1
            fm["last_promoted"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            vault.write_note(title, body, folder=folder, tags=tags,
                             frontmatter=fm, timestamp=False)
            updated.append(mid)
        else:
            vault.write_note(title, body, folder=folder, tags=tags,
                             frontmatter={"promoted_count": 1,
                                          "memory_id": mid,
                                          "confidence": round(mem.confidence, 4)})
            promoted.append(mid)
    return PromotionResult(promoted=promoted, updated=updated, skipped=skipped)
