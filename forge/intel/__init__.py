"""forge.intel — daily/weekly industry-signal pipeline.

Public surface:

- `IntelItem`           — canonical normalized item shape
- `Source`              — source declaration (name, kind, url, tags)
- `pull_intel`          — fetch + dedup all sources, return new IntelItems
- `IntelDigest`         — group + rank by relevance for proposer injection
- `build_intel_digest`  — items → digest
- `store_items`         — persist to <home>/intel/<date>.json + vault + genome
- `load_sources`        — read default + user-override source list
"""
from __future__ import annotations

from .auto_research import AutoResearchBudget, AutoResearchResult, run_auto_research
from .digest import IntelDigest, build_intel_digest
from .fetch import pull_intel
from .normalize import IntelItem, keyword_relevance, normalize_item
from .sources import DEFAULT_SOURCES, DOMAIN_ALLOWLIST, Source, is_allowed, load_sources
from .store import store_items

__all__ = [
    "IntelItem", "Source", "DEFAULT_SOURCES", "DOMAIN_ALLOWLIST",
    "IntelDigest", "build_intel_digest", "pull_intel",
    "load_sources", "is_allowed", "store_items",
    "keyword_relevance", "normalize_item",
    "AutoResearchBudget", "AutoResearchResult", "run_auto_research",
]
