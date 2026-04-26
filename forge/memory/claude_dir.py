"""`.claude/` filesystem contract — lifted from Justin's Orgo + coo repos.

Canonical layout:
  .claude/
    GENOME.md
    MEMORY.md
    agents/<name>.md
    skills/<name>/SKILL.md
    personas/<name>.yaml
    healing/{history,patterns,circuits}.json
    learning/{observations,insights,evolution,dream-log}.json
    security/{pii-patterns,allowlists}.json
    traces/<run_id>/
    heartbeats/*.md
    settings.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SUBDIRS = [
    "agents", "skills", "personas",
    "healing", "learning", "security",
    "traces", "heartbeats",
]

_DEFAULT_FILES = {
    "GENOME.md": "# Genome\n\nThe agent's identity, constraints, and provenance.\n",
    "MEMORY.md": "# Memory Index\n\nLong-term memory entries.\n",
    "settings.json": "{}\n",
}

_HEALING_FILES = {
    "history.json": "[]\n",
    "patterns.json": "{}\n",
    "circuits.json": "{}\n",
}

_LEARNING_FILES = {
    "observations.json": "[]\n",
    "insights.json": "[]\n",
    "evolution.json": "[]\n",
    "dream-log.json": "[]\n",
}

_SECURITY_FILES = {
    "pii-patterns.json": "[]\n",
    "allowlists.json": "{}\n",
}


class ClaudeDir:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.bootstrap()

    def bootstrap(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for d in _SUBDIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        for name, body in _DEFAULT_FILES.items():
            p = self.root / name
            if not p.exists():
                p.write_text(body)
        for name, body in _HEALING_FILES.items():
            p = self.root / "healing" / name
            if not p.exists():
                p.write_text(body)
        for name, body in _LEARNING_FILES.items():
            p = self.root / "learning" / name
            if not p.exists():
                p.write_text(body)
        for name, body in _SECURITY_FILES.items():
            p = self.root / "security" / name
            if not p.exists():
                p.write_text(body)

    def append_observation(self, obs: dict[str, Any]) -> None:
        path = self.root / "learning" / "observations.json"
        data = json.loads(path.read_text() or "[]")
        data.append(obs)
        path.write_text(json.dumps(data, indent=2))

    def write_circuits(self, snapshot: dict[str, Any]) -> None:
        (self.root / "healing" / "circuits.json").write_text(json.dumps(snapshot, indent=2))
