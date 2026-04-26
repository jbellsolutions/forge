"""Skill primitive — SKILL.md + outcomes log + version graph.

A skill is a markdown prompt template with optional Python sidecar. Each invocation
logs (input_hash, output, outcome_score, cost, latency). Versions live as v1, v2, ...
under skills/<name>/. Active version is symlinked / pointed by `current.txt`.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SkillRun:
    skill: str
    version: str
    input_hash: str
    output: str
    outcome_score: float       # in [-1, 1]; positive = good
    cost: float = 0.0
    latency_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class SkillStore:
    """Filesystem store for skills + run history. Lives under <root>/skills/."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # registration ---------------------------------------------------------
    def write_skill(self, name: str, body: str, version: str = "v1") -> Path:
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{version}.md"
        p.write_text(body)
        cur = d / "current.txt"
        if not cur.exists():
            cur.write_text(version)
        return p

    def read_skill(self, name: str, version: str | None = None) -> str:
        d = self.root / name
        v = version or (d / "current.txt").read_text().strip()
        return (d / f"{v}.md").read_text()

    def current_version(self, name: str) -> str:
        return (self.root / name / "current.txt").read_text().strip()

    def set_current(self, name: str, version: str) -> None:
        (self.root / name / "current.txt").write_text(version)

    def versions(self, name: str) -> list[str]:
        d = self.root / name
        return sorted(p.stem for p in d.glob("v*.md"))

    def list_skills(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    # invocation log -------------------------------------------------------
    def log_run(self, run: SkillRun) -> None:
        d = self.root / run.skill
        d.mkdir(parents=True, exist_ok=True)
        with (d / "runs.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(run.__dict__) + "\n")

    def runs(self, name: str, version: str | None = None) -> list[SkillRun]:
        d = self.root / name
        path = d / "runs.jsonl"
        if not path.exists():
            return []
        out: list[SkillRun] = []
        for line in path.read_text().splitlines():
            data = json.loads(line)
            if version and data.get("version") != version:
                continue
            out.append(SkillRun(**data))
        return out

    @staticmethod
    def hash_input(inp: str) -> str:
        return hashlib.sha256(inp.encode()).hexdigest()[:16]
