"""SyncState — `<home>/sync-state.json` tracks last-pushed timestamps per kind.

Idempotency belongs in two places: stable IDs on the server (so re-pushing
a row is a no-op) and a high-water mark on the client (so we don't scan
the world every cycle). This file is the latter.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class SyncState:
    last_agents_ts: float = 0.0
    last_runs_ts: float = 0.0
    last_changelog_ts: float = 0.0
    last_genome_ts: float = 0.0
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, home: Path) -> "SyncState":
        path = home / "sync-state.json"
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return cls()
        # tolerate extra/missing fields
        return cls(
            last_agents_ts=float(data.get("last_agents_ts", 0.0)),
            last_runs_ts=float(data.get("last_runs_ts", 0.0)),
            last_changelog_ts=float(data.get("last_changelog_ts", 0.0)),
            last_genome_ts=float(data.get("last_genome_ts", 0.0)),
            extra=data.get("extra") or {},
        )

    def save(self, home: Path) -> None:
        home.mkdir(parents=True, exist_ok=True)
        (home / "sync-state.json").write_text(json.dumps(asdict(self), indent=2))
