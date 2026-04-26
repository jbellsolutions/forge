"""Sync push handlers — applied by /sync/push.

Idempotent upsert by stable ID. The local forge runtime computes IDs
from content hashes, so re-running `forge sync push` after a crash
produces no duplicates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from .db import (
    AgentRow, ChangelogEntry, GenomeMemory, Project, RunRow,
)


def _parse_dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(float(v), tz=timezone.utc)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def apply_sync_push(ses: Session, body: dict[str, Any]) -> dict[str, int]:
    """Body shape:
        {
          "projects": [{"id":..,"name":..,"slug":..}],
          "agents":   [{"id":..,"project_id":..,"name":..,"profile":..,...}],
          "runs":     [{"id":..,"agent_id":..,"started_at":..,...}],
          "changelog":[{"id":..,"ts":..,"kind":..,"title":..,"body_md":..}],
          "genome":   [{"id":..,"text":..,"tags":..,"confidence":..,"ts":..}],
        }
    Each list is independently optional. Returns counts of upserted rows.
    """
    counts = {"projects": 0, "agents": 0, "runs": 0, "changelog": 0, "genome": 0}

    for p in body.get("projects") or []:
        existing = ses.get(Project, p["id"])
        if existing is None:
            ses.add(Project(
                id=p["id"], name=p.get("name", p["id"]),
                slug=p.get("slug", p["id"]),
                created_at=_parse_dt(p.get("created_at")) or datetime.now(timezone.utc),
            ))
            counts["projects"] += 1
        else:
            existing.name = p.get("name", existing.name)
            existing.slug = p.get("slug", existing.slug)
            ses.add(existing)
            counts["projects"] += 1

    for a in body.get("agents") or []:
        existing = ses.get(AgentRow, a["id"])
        if existing is None:
            ses.add(AgentRow(
                id=a["id"], project_id=a["project_id"], name=a["name"],
                profile=a.get("profile", "anthropic"),
                instructions=a.get("instructions", ""),
                tools_allowed=a.get("tools_allowed"),
                tools_denied=a.get("tools_denied") or [],
                status=a.get("status", "active"),
                created_at=_parse_dt(a.get("created_at")) or datetime.now(timezone.utc),
                last_seen_at=_parse_dt(a.get("last_seen_at")),
                total_runs=int(a.get("total_runs", 0)),
                total_cost_usd=float(a.get("total_cost_usd", 0.0)),
            ))
        else:
            for fld in ("name", "profile", "instructions", "tools_allowed",
                        "tools_denied", "status", "total_runs", "total_cost_usd"):
                if fld in a:
                    setattr(existing, fld, a[fld])
            if "last_seen_at" in a:
                existing.last_seen_at = _parse_dt(a.get("last_seen_at"))
            ses.add(existing)
        counts["agents"] += 1

    for r in body.get("runs") or []:
        existing = ses.get(RunRow, r["id"])
        if existing is None:
            ses.add(RunRow(
                id=r["id"], agent_id=r["agent_id"],
                session_id=r.get("session_id", ""),
                started_at=_parse_dt(r.get("started_at")) or datetime.now(timezone.utc),
                ended_at=_parse_dt(r.get("ended_at")),
                tool_calls=int(r.get("tool_calls", 0)),
                tool_errors=int(r.get("tool_errors", 0)),
                blocked=int(r.get("blocked", 0)),
                input_tokens=int(r.get("input_tokens", 0)),
                output_tokens=int(r.get("output_tokens", 0)),
                cost_usd=float(r.get("cost_usd", 0.0)),
            ))
            counts["runs"] += 1

    for c in body.get("changelog") or []:
        existing = ses.get(ChangelogEntry, c["id"])
        if existing is None:
            ses.add(ChangelogEntry(
                id=c["id"],
                ts=_parse_dt(c.get("ts")) or datetime.now(timezone.utc),
                kind=c.get("kind", "unknown"),
                title=c.get("title", ""),
                body_md=c.get("body_md", ""),
                ref_path=c.get("ref_path"),
            ))
            counts["changelog"] += 1

    for g in body.get("genome") or []:
        existing = ses.get(GenomeMemory, g["id"])
        if existing is None:
            ses.add(GenomeMemory(
                id=g["id"],
                text=g.get("text", ""),
                tags=g.get("tags") or [],
                confidence=float(g.get("confidence", 0.5)),
                ts=_parse_dt(g.get("ts")) or datetime.now(timezone.utc),
            ))
            counts["genome"] += 1
        else:
            existing.text = g.get("text", existing.text)
            existing.tags = g.get("tags") or existing.tags
            existing.confidence = float(g.get("confidence", existing.confidence))
            ses.add(existing)
            counts["genome"] += 1

    return counts
