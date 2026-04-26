"""Recursive self-modification — the meta-harness loop.

Reads full-fidelity traces (Meta-Harness invariant), extracts failure signatures,
proposes config diffs against the harness itself (provider profile, persona,
tool allow/deny, retry policy). Diffs are applied to a candidate dir, scored,
and rolled back on regression.

Phase 9 ships a working v0:
  Proposer  — analyzes traces -> emits a list of HarnessDiff
  Apply     — apply a HarnessDiff to a working copy
  Score     — run a benchmark task, return outcome score
  Loop      — propose -> apply -> score -> keep-or-rollback

The default analyzer is rule-based (token cost spikes, repeated tool errors,
high blocked-rate). Production swaps in an LLM proposer that reads the raw
trace filesystem.
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class HarnessDiff:
    rationale: str
    target: str           # path within working copy, relative
    op: str               # "patch_yaml" | "deny_tool" | "retune_circuit"
    payload: dict[str, Any]


class TraceAnalyzer:
    """Read a session's tool_calls.jsonl and extract symptoms."""

    def __init__(self, traces_root: str | Path) -> None:
        self.root = Path(traces_root)

    def sessions(self) -> list[Path]:
        return sorted(p for p in self.root.iterdir() if p.is_dir()) if self.root.exists() else []

    def symptoms(self) -> dict[str, Any]:
        tool_errors = Counter()
        blocks = Counter()
        for sess in self.sessions():
            tc_path = sess / "tool_calls.jsonl"
            if not tc_path.exists():
                continue
            for line in tc_path.read_text().splitlines():
                rec = json.loads(line)
                if rec.get("phase") == "post" and rec.get("is_error"):
                    tool_errors[rec.get("name", "?")] += 1
                if rec.get("phase") == "pre" and rec.get("verdict") == "blocked":
                    blocks[rec.get("name", "?")] += 1
        return {"tool_errors": dict(tool_errors), "blocks": dict(blocks)}


def propose(symptoms: dict[str, Any]) -> list[HarnessDiff]:
    """Rule-based v0 proposer."""
    out: list[HarnessDiff] = []
    for tool, n in symptoms.get("tool_errors", {}).items():
        if n >= 5:
            out.append(HarnessDiff(
                rationale=f"{tool} errored {n}x — tighten circuit threshold",
                target=".forge/healing/circuits.json",
                op="retune_circuit",
                payload={"tool": tool, "fail_threshold": 2, "cooldown_seconds": 1800},
            ))
    for tool, n in symptoms.get("blocks", {}).items():
        if n >= 3:
            out.append(HarnessDiff(
                rationale=f"{tool} blocked {n}x — add to persona deny list",
                target=".claude/personas/_default.yaml",
                op="deny_tool",
                payload={"tool": tool},
            ))
    return out


def apply(diff: HarnessDiff, root: str | Path) -> bool:
    """Apply a HarnessDiff. Returns True on success."""
    root = Path(root)
    if diff.op == "retune_circuit":
        tool = diff.payload.get("tool")
        if not tool:
            return False
        path = root / diff.target
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(path.read_text() or "{}") if path.exists() else {}
        data[tool] = {
            "fail_threshold": int(diff.payload.get("fail_threshold", 3)),
            "cooldown_seconds": int(diff.payload.get("cooldown_seconds", 3600)),
        }
        path.write_text(json.dumps(data, indent=2))
        return True
    if diff.op == "deny_tool":
        tool = diff.payload.get("tool") or diff.payload.get("name")
        if not tool:
            return False
        path = root / diff.target
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text() if path.exists() else "denied_tools: []\n"
        if "denied_tools:" not in existing:
            existing += "\ndenied_tools: []\n"
        if tool not in existing:
            existing = existing.replace(
                "denied_tools: []",
                f"denied_tools: [{tool}]",
            )
        path.write_text(existing)
        return True
    if diff.op == "patch_yaml":
        # Best-effort: append a YAML stanza to the target file.
        path = root / diff.target
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text() if path.exists() else ""
        snippet = diff.payload.get("yaml") or json.dumps(diff.payload)
        path.write_text(existing.rstrip() + "\n" + snippet + "\n")
        return True
    return False


def fork(root: str | Path, suffix: str = "candidate") -> Path:
    """Copy harness state to a candidate dir for safe modification."""
    root = Path(root)
    cand = root.with_name(f"{root.name}.{suffix}")
    if cand.exists():
        shutil.rmtree(cand)
    shutil.copytree(root, cand)
    return cand


def keep_or_rollback(
    base_score: float, candidate_score: float,
    margin: float = 0.0,
) -> bool:
    """Return True if candidate should be kept."""
    return candidate_score > base_score + margin
