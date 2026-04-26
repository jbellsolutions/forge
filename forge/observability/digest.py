"""Daily / weekly self-improvement digest.

Aggregates what forge LEARNED in a given window:
- skill creations + promotions (from <home>/skills/<name>/{v*.md, runs.jsonl, current.txt})
- recursion outcomes (from <home>/results.tsv — kept vs rolled candidates)
- denial loops triggered (from <home>/traces/<sid>/events.jsonl, verdict ∈ {blocked, safety_blocked})
- circuit trips (from <home>/.forge/healing/circuits.json — state==OPEN snapshots)
- genome growth (size delta)
- intel + auto-research outputs (from <home>/intel/auto-research.tsv, <home>/intel/<date>.json)
- cost + token rollup (from <home>/telemetry.jsonl)

PRIVACY INVARIANT
=================
This module reads aggregate metadata only. It MUST NEVER include full
`messages.jsonl` content, full prompts, or raw LLM outputs in the digest.
What's allowed: counts, names, score deltas, error classifications, vault
note titles, intel-item titles. What's forbidden: the body of messages,
chat content, stack traces with paths, anything that could leak PII or
secrets to a Slack channel.

Tests under `tests/test_digest.py` regex-assert this invariant.
"""
from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal


Period = Literal["day", "week"]


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class RecursionRow:
    ts: float
    candidate: str
    base_score: float
    candidate_score: float
    delta: float
    kept: bool
    notes: str


@dataclass
class SkillEvent:
    kind: Literal["created", "promoted", "rolled_back"]
    name: str
    version: str
    ts: float
    note: str = ""


@dataclass
class DenialEvent:
    ts: float
    agent: str
    tool: str
    verdict: str  # "blocked" | "safety_blocked"
    note: str


@dataclass
class TelemetryRollup:
    sessions: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    tool_calls: int = 0
    tool_errors: int = 0
    blocked: int = 0


@dataclass
class IntelHighlight:
    """One intel item from today's pull or the auto-research summary."""
    source: str
    title: str
    url: str
    relevance: str  # "high" | "med" | "low"


@dataclass
class Digest:
    period: Period
    started_at: datetime
    ended_at: datetime
    home: Path
    recursion: list[RecursionRow] = field(default_factory=list)
    skills: list[SkillEvent] = field(default_factory=list)
    denials: list[DenialEvent] = field(default_factory=list)
    telemetry: TelemetryRollup = field(default_factory=TelemetryRollup)
    genome_size: int = 0
    genome_growth: int = 0
    intel: list[IntelHighlight] = field(default_factory=list)
    auto_research_summary: str = ""

    # ---- counts (cheap derived views) ------------------------------------
    @property
    def kept_count(self) -> int:
        return sum(1 for r in self.recursion if r.kept)

    @property
    def rolled_count(self) -> int:
        return sum(1 for r in self.recursion if not r.kept)

    @property
    def safety_blocked_count(self) -> int:
        return sum(1 for d in self.denials if d.verdict == "safety_blocked")

    # ---- views -----------------------------------------------------------
    def to_json(self) -> dict[str, Any]:
        def _row(r: RecursionRow) -> dict[str, Any]:
            return {
                "ts": r.ts, "candidate": r.candidate,
                "base_score": r.base_score, "candidate_score": r.candidate_score,
                "delta": r.delta, "kept": r.kept,
                # `notes` may contain rationale text — strip newlines, cap length
                "notes": _scrub(r.notes, 200),
            }
        def _skill(s: SkillEvent) -> dict[str, Any]:
            return {"kind": s.kind, "name": s.name, "version": s.version,
                    "ts": s.ts, "note": _scrub(s.note, 200)}
        def _den(d: DenialEvent) -> dict[str, Any]:
            return {"ts": d.ts, "agent": d.agent, "tool": d.tool,
                    "verdict": d.verdict, "note": _scrub(d.note, 200)}
        def _intel(i: IntelHighlight) -> dict[str, Any]:
            return {"source": i.source, "title": _scrub(i.title, 160),
                    "url": i.url, "relevance": i.relevance}
        return {
            "period": self.period,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "home": str(self.home),
            "recursion": [_row(r) for r in self.recursion],
            "kept_count": self.kept_count,
            "rolled_count": self.rolled_count,
            "skills": [_skill(s) for s in self.skills],
            "denials": [_den(d) for d in self.denials],
            "safety_blocked_count": self.safety_blocked_count,
            "telemetry": self.telemetry.__dict__,
            "genome_size": self.genome_size,
            "genome_growth": self.genome_growth,
            "intel": [_intel(i) for i in self.intel],
            "auto_research_summary": _scrub(self.auto_research_summary, 4000),
        }

    def to_markdown(self) -> str:
        title = "🌅 forge daily digest" if self.period == "day" else "📊 forge weekly digest"
        when = self.ended_at.strftime("%Y-%m-%d")
        lines = [
            f"*{title} — {when}*",
            f"_window: {self.started_at.isoformat()} → {self.ended_at.isoformat()}_",
            "",
            f"*Self-improvement*",
            f"• {self.kept_count} mod kept · {self.rolled_count} rolled back",
            f"• {len([s for s in self.skills if s.kind == 'created'])} skill(s) created · "
            f"{len([s for s in self.skills if s.kind == 'promoted'])} promoted · "
            f"{len([s for s in self.skills if s.kind == 'rolled_back'])} rolled back",
            f"• genome: {self.genome_size} memories ({_signed(self.genome_growth)} since window start)",
            "",
            f"*Healing*",
            f"• {len(self.denials)} denial event(s) · {self.safety_blocked_count} bypass-immune",
            "",
            f"*Cost*",
            f"• {self.telemetry.sessions} session(s) · "
            f"in: {self.telemetry.total_input_tokens:,} tok · "
            f"out: {self.telemetry.total_output_tokens:,} tok · "
            f"${self.telemetry.total_cost_usd:.4f}",
        ]
        if self.recursion:
            lines += ["", "*Recursion ledger (kept first)*"]
            kept_first = sorted(self.recursion, key=lambda r: (not r.kept, -r.delta))
            for r in kept_first[:8]:
                marker = "✓ kept" if r.kept else "✗ rolled"
                lines.append(
                    f"• {marker} · Δ{_signed_score(r.delta)} · {_scrub(r.notes, 120)}"
                )
        if self.skills:
            lines += ["", "*Skills*"]
            for s in self.skills[:8]:
                lines.append(f"• {s.kind}: `{s.name}@{s.version}` · {_scrub(s.note, 100)}")
        if self.denials:
            lines += ["", "*Top denial loops*"]
            by_tool: dict[str, int] = {}
            for d in self.denials:
                by_tool[d.tool] = by_tool.get(d.tool, 0) + 1
            for tool, n in sorted(by_tool.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"• `{tool}` × {n}")
        if self.intel:
            lines += ["", "*Industry signal (today)*"]
            for it in [i for i in self.intel if i.relevance in ("high", "med")][:8]:
                lines.append(f"• [{it.source}] {it.title}")
        if self.auto_research_summary:
            lines += ["", "*Auto-research summary*", _scrub(self.auto_research_summary, 1200)]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_digest(
    home: str | Path,
    period: Period = "day",
    at: datetime | None = None,
) -> Digest:
    """Aggregate forge artifacts into a `Digest` for the given window.

    `at` defaults to "now"; the window ends at `at` and starts 1 day or
    1 week earlier depending on `period`. All times are timezone-aware UTC.
    """
    home_p = Path(home)
    end = at or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    delta = timedelta(days=1) if period == "day" else timedelta(days=7)
    start = end - delta

    digest = Digest(
        period=period, started_at=start, ended_at=end, home=home_p,
    )
    digest.recursion = _read_recursion(home_p, start, end)
    digest.skills = _read_skills(home_p, start, end)
    digest.denials = _read_denials(home_p, start, end)
    digest.telemetry = _read_telemetry(home_p, start, end)
    digest.genome_size, digest.genome_growth = _read_genome(home_p, start, end)
    digest.intel, digest.auto_research_summary = _read_intel(home_p, start, end)
    return digest


# ---------------------------------------------------------------------------
# Readers — each tolerates missing files (fresh installs) and bad rows.
# ---------------------------------------------------------------------------

def _read_recursion(home: Path, start: datetime, end: datetime) -> list[RecursionRow]:
    p = home / "results.tsv"
    if not p.exists():
        return []
    out: list[RecursionRow] = []
    s_ts, e_ts = start.timestamp(), end.timestamp()
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            try:
                ts = float(row.get("timestamp", "0"))
                if not (s_ts <= ts < e_ts):
                    continue
                out.append(RecursionRow(
                    ts=ts,
                    candidate=row.get("candidate", ""),
                    base_score=float(row.get("base_score", "0") or 0),
                    candidate_score=float(row.get("candidate_score", "0") or 0),
                    delta=float(row.get("delta", "0") or 0),
                    kept=row.get("kept", "0") in ("1", "true", "True"),
                    notes=row.get("notes", "") or "",
                ))
            except (ValueError, TypeError):
                continue
    return out


def _read_skills(home: Path, start: datetime, end: datetime) -> list[SkillEvent]:
    skills_dir = home / "skills"
    if not skills_dir.exists():
        return []
    out: list[SkillEvent] = []
    s_ts, e_ts = start.timestamp(), end.timestamp()
    for skill_dir in skills_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        name = skill_dir.name
        # Versions = v*.md files; mtime serves as creation ts.
        for v_path in sorted(skill_dir.glob("v*.md")):
            try:
                mtime = v_path.stat().st_mtime
            except OSError:
                continue
            if s_ts <= mtime < e_ts:
                out.append(SkillEvent(
                    kind="created", name=name, version=v_path.stem, ts=mtime,
                ))
        # current.txt → if mtime in window AND points to a version other than v1, count as promotion.
        cur = skill_dir / "current.txt"
        if cur.exists():
            try:
                mtime = cur.stat().st_mtime
                if s_ts <= mtime < e_ts:
                    cv = cur.read_text(encoding="utf-8").strip()
                    if cv and cv != "v1":
                        out.append(SkillEvent(
                            kind="promoted", name=name, version=cv, ts=mtime,
                            note=f"current → {cv}",
                        ))
            except OSError:
                pass
        # Rolled-back signal: runs.jsonl entries with outcome_score < 0 in window.
        runs = skill_dir / "runs.jsonl"
        if runs.exists():
            for line in runs.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                    rts = float(rec.get("ts", 0))
                    if s_ts <= rts < e_ts and float(rec.get("outcome_score", 0)) < -0.5:
                        out.append(SkillEvent(
                            kind="rolled_back", name=name,
                            version=rec.get("version", "?"), ts=rts,
                            note="negative outcome",
                        ))
                except (ValueError, json.JSONDecodeError):
                    continue
    out.sort(key=lambda e: e.ts)
    return out


_DENIAL_VERDICTS = {"blocked", "safety_blocked"}


def _read_denials(home: Path, start: datetime, end: datetime) -> list[DenialEvent]:
    traces = home / "traces"
    if not traces.exists():
        return []
    out: list[DenialEvent] = []
    s_ts, e_ts = start.timestamp(), end.timestamp()
    for sess_dir in traces.iterdir():
        if not sess_dir.is_dir():
            continue
        ev_path = sess_dir / "events.jsonl"
        if not ev_path.exists():
            continue
        for line in ev_path.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            verdict = (ev.get("verdict") or "").lower()
            if verdict not in _DENIAL_VERDICTS:
                continue
            ts = float(ev.get("ts", 0))
            if not (s_ts <= ts < e_ts):
                continue
            tool = ev.get("tool") or (ev.get("tool_call") or {}).get("name", "?")
            out.append(DenialEvent(
                ts=ts, agent=ev.get("agent_name") or ev.get("agent", "?"),
                tool=tool, verdict=verdict,
                note="; ".join(ev.get("notes", [])) if isinstance(ev.get("notes"), list) else "",
            ))
    out.sort(key=lambda d: d.ts)
    return out


def _read_telemetry(home: Path, start: datetime, end: datetime) -> TelemetryRollup:
    p = home / "telemetry.jsonl"
    rollup = TelemetryRollup()
    if not p.exists():
        return rollup
    s_ts, e_ts = start.timestamp(), end.timestamp()
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Telemetry rows have started_at as the timestamp.
        ts = float(r.get("started_at") or r.get("ended_at") or 0)
        if not (s_ts <= ts < e_ts):
            continue
        rollup.sessions += 1
        rollup.total_input_tokens += int(r.get("input_tokens", 0))
        rollup.total_output_tokens += int(r.get("output_tokens", 0))
        rollup.total_cost_usd += float(r.get("cost_usd", 0))
        rollup.tool_calls += int(r.get("tool_calls", 0))
        rollup.tool_errors += int(r.get("tool_errors", 0))
        rollup.blocked += int(r.get("blocked", 0))
    rollup.total_cost_usd = round(rollup.total_cost_usd, 6)
    return rollup


def _read_genome(home: Path, start: datetime, end: datetime) -> tuple[int, int]:
    """Return (size_now, growth_in_window). Best-effort: reads ~/.forge/genome.json
    and the per-home one if it exists. Growth is approximated by counting
    memories whose `ts` (if present) falls in the window."""
    candidates = [Path.home() / ".forge" / "genome.json", home / "genome.json"]
    s_ts, e_ts = start.timestamp(), end.timestamp()
    size = 0
    growth = 0
    for p in candidates:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        # ReasoningBank persists as {"memories": {id: mem}, ...} — be lenient.
        mems = data.get("memories") if isinstance(data, dict) else None
        if mems is None and isinstance(data, dict):
            mems = data
        if not isinstance(mems, dict):
            continue
        size = max(size, len(mems))
        for m in mems.values():
            if not isinstance(m, dict):
                continue
            ts = float(m.get("ts") or m.get("created_at") or 0)
            if s_ts <= ts < e_ts:
                growth += 1
        break
    return size, growth


def _read_intel(home: Path, start: datetime, end: datetime) -> tuple[list[IntelHighlight], str]:
    """Read today's intel JSON + most-recent auto-research summary in window."""
    out: list[IntelHighlight] = []
    intel_dir = home / "intel"
    if intel_dir.exists():
        # All YYYY-MM-DD.json files whose date falls in window.
        for p in sorted(intel_dir.glob("*.json")):
            try:
                d = datetime.strptime(p.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if not (start <= d <= end):
                continue
            try:
                items = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                out.append(IntelHighlight(
                    source=it.get("source", "?"),
                    title=it.get("title", "?"),
                    url=it.get("url", ""),
                    relevance=it.get("relevance", "low"),
                ))
    summary = ""
    ar_dir = home / "intel"
    ar_path = ar_dir / "auto-research.tsv" if ar_dir.exists() else None
    if ar_path and ar_path.exists():
        s_ts, e_ts = start.timestamp(), end.timestamp()
        rows: list[tuple[float, str]] = []
        with ar_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                try:
                    ts = float(row.get("ts", 0))
                except (ValueError, TypeError):
                    continue
                if not (s_ts <= ts < e_ts):
                    continue
                summary_ref = row.get("summary_ref") or ""
                rows.append((ts, summary_ref))
        if rows:
            # Take latest in window.
            _, ref = max(rows, key=lambda x: x[0])
            if ref:
                ref_path = home / ref
                if ref_path.exists():
                    summary = ref_path.read_text(encoding="utf-8")
    return out, summary


# ---------------------------------------------------------------------------
# Privacy / safety helpers
# ---------------------------------------------------------------------------

# Patterns we never want to leak into a Slack channel even by accident.
_FORBIDDEN_PATTERNS = [
    re.compile(r'"role"\s*:\s*"', re.IGNORECASE),
    re.compile(r'"content"\s*:\s*\[', re.IGNORECASE),  # Anthropic content arrays
    re.compile(r'sk-[A-Za-z0-9_-]{20,}'),               # Anthropic-style key
    re.compile(r'sk-ant-[A-Za-z0-9_-]{20,}'),
    re.compile(r'sk-or-v1-[A-Za-z0-9_-]{20,}'),         # OpenRouter
    re.compile(r'AKIA[0-9A-Z]{16}'),                    # AWS
]


def _scrub(text: str, max_len: int) -> str:
    """Truncate and strip newlines for compact one-line rendering. Hard-strip
    anything that looks like a credential or message-content shape — privacy
    invariant defined at top of file."""
    if not text:
        return ""
    s = str(text).replace("\n", " ").replace("\t", " ").strip()
    for pat in _FORBIDDEN_PATTERNS:
        s = pat.sub("[redacted]", s)
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _signed(n: int) -> str:
    return f"+{n}" if n > 0 else str(n)


def _signed_score(n: float) -> str:
    return f"+{n:.2f}" if n >= 0 else f"{n:.2f}"
