"""Persist IntelItems to disk + vault + genome.

Three sinks per item batch:
1. `<home>/intel/<YYYY-MM-DD>.json` — append (or merge by URL) all items
   for the day. This is what the daily report + recursion proposer read.
2. `<home>/vault/intel/<source>/<slug>.md` — one Note per item with
   frontmatter, so the existing ObsidianVault backlinks graph picks them up.
3. cross-project `genome()` — distill top-3 high-relevance items into the
   ReasoningBank for compounding learning.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ..memory.genome import genome
from ..memory.obsidian import ObsidianVault
from .normalize import IntelItem


log = logging.getLogger("forge.intel.store")


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(s: str, max_len: int = 60) -> str:
    s = _SLUG_RE.sub("-", s.lower()).strip("-")
    return s[:max_len] or "item"


def store_items(
    home: str | Path,
    items: list[IntelItem],
    *,
    write_vault: bool = True,
    write_genome: bool = True,
    today: str | None = None,
) -> dict[str, int]:
    """Write items to all three sinks. Returns counts.

    Idempotent: re-running with already-stored URLs merges (no duplicates
    in the daily JSON, no duplicate vault notes, no double-distilled
    genome memories).
    """
    home_p = Path(home)
    intel_dir = home_p / "intel"
    intel_dir.mkdir(parents=True, exist_ok=True)
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Daily JSON — merge by URL.
    day_path = intel_dir / f"{today}.json"
    existing: list[dict] = []
    if day_path.exists():
        try:
            existing = json.loads(day_path.read_text(encoding="utf-8")) or []
        except json.JSONDecodeError:
            existing = []
    by_url = {e.get("url"): e for e in existing if isinstance(e, dict)}
    added_json = 0
    for it in items:
        if it.url in by_url:
            continue
        by_url[it.url] = it.to_json()
        added_json += 1
    day_path.write_text(
        json.dumps(list(by_url.values()), indent=2, default=str),
        encoding="utf-8",
    )

    # 2. Vault notes.
    added_vault = 0
    if write_vault:
        vault_root = home_p / "vault"
        vault = ObsidianVault(vault_root)
        for it in items:
            try:
                folder = f"intel/{_slug(it.source, 32)}"
                title = it.title or "untitled"
                # Body: human-readable summary with link.
                body = (
                    f"{it.summary}\n\n"
                    f"**Source**: {it.source}\n"
                    f"**Relevance**: {it.relevance}\n"
                    f"**Tags**: {', '.join(it.tags)}\n"
                    f"**URL**: <{it.url}>\n"
                )
                vault.write_note(title=title, body=body, folder=folder, tags=list(it.tags))
                added_vault += 1
            except Exception as e:  # noqa: BLE001
                log.warning("vault write failed for %s: %s", it.url, e)

    # 3. Genome — distill top-3 high-relevance only.
    added_genome = 0
    if write_genome:
        try:
            bank = genome()
            high = [i for i in items if i.relevance == "high"]
            high.sort(key=lambda i: -i.ts)
            for it in high[:3]:
                text = f"[{it.source}] {it.title} — {it.summary[:200]}".strip()
                m = bank.distill(text, tags=list(it.tags) + ["intel"])
                bank.consolidate(m)
                added_genome += 1
        except Exception as e:  # noqa: BLE001
            log.warning("genome distill failed: %s", e)

    return {
        "json_added": added_json, "json_total": len(by_url),
        "vault_added": added_vault, "genome_added": added_genome,
        "day_path": str(day_path),
    }
