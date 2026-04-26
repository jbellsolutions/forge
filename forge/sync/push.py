"""push_deltas — scan local artifacts and POST a JSON batch to /sync/push.

Sources scanned (each independently optional — missing files are OK):

- `<home>/agents/*.yaml`         → Project + AgentRow
- `<home>/results.tsv`           → ChangelogEntry(kind=recursion, mod_kept|mod_rolled)
- `~/.forge/genome.json`         → GenomeMemory

Stable IDs:
- project_id = sha256("forge").hex[:12]              (single default project for v1)
- agent_id   = sha256(name).hex[:12]
- changelog id = sha256(kind|ts|title).hex[:12]
- genome id  = the memory's own md5 hash

The transport is pluggable: pass `transport=fn(url, body, headers) -> dict`
in tests to forward into a FastAPI TestClient. Default uses stdlib urllib.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .state import SyncState


Transport = Callable[[str, bytes, dict[str, str]], dict[str, Any]]


def _default_transport(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec — own server
        return json.loads(resp.read().decode("utf-8"))


def _stable(s: str, n: int = 12) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:n]


def _scan_agents(home: Path, since_ts: float) -> tuple[list[dict], list[dict], float]:
    """Return (projects, agents, max_mtime). One default project for v1."""
    proj_id = _stable("forge")
    projects = [{"id": proj_id, "name": "forge", "slug": "forge"}]
    agents: list[dict] = []
    max_mtime = since_ts
    agents_dir = home / "agents"
    if not agents_dir.exists():
        return projects, agents, max_mtime
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None  # type: ignore
    for yml in sorted(agents_dir.glob("*.yaml")):
        mtime = yml.stat().st_mtime
        if mtime <= since_ts:
            continue
        max_mtime = max(max_mtime, mtime)
        try:
            text = yml.read_text(encoding="utf-8")
            data = yaml.safe_load(text) if yaml else {"name": yml.stem}
        except Exception:  # noqa: BLE001
            continue
        name = data.get("name") or yml.stem
        agents.append({
            "id": _stable(name),
            "project_id": proj_id,
            "name": name,
            "profile": data.get("profile", "anthropic"),
            "instructions": data.get("instructions", ""),
            "tools_allowed": data.get("tools_allowed"),
            "tools_denied": data.get("tools_denied") or [],
            "status": data.get("status", "active"),
            "last_seen_at": mtime,
        })
    return projects, agents, max_mtime


def _scan_results_tsv(home: Path, since_ts: float) -> tuple[list[dict], float]:
    """Each TSV row → one ChangelogEntry."""
    path = home / "results.tsv"
    if not path.exists():
        return [], since_ts
    out: list[dict] = []
    max_ts = since_ts
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        return [], since_ts
    header = lines[0].split("\t")
    for raw in lines[1:]:
        if not raw.strip():
            continue
        row = dict(zip(header, raw.split("\t")))
        try:
            ts = float(row.get("timestamp", "0"))
        except ValueError:
            continue
        if ts <= since_ts:
            continue
        max_ts = max(max_ts, ts)
        kept = row.get("kept", "0") == "1"
        kind = "mod_kept" if kept else "mod_rolled"
        title = f"recurse: {row.get('candidate', '')[:60]}"
        body = (
            f"- base: {row.get('base_score')}\n"
            f"- candidate: {row.get('candidate_score')}\n"
            f"- delta: {row.get('delta')}\n"
            f"- kept: {kept}\n"
            f"- notes: {row.get('notes', '')}"
        )
        out.append({
            "id": _stable(f"{kind}|{ts}|{title}"),
            "ts": ts,
            "kind": kind,
            "title": title,
            "body_md": body,
            "ref_path": str(path),
        })
    return out, max_ts


def _scan_genome(since_ts: float) -> tuple[list[dict], float]:
    """Read the singleton genome JSON; emit any memory not seen before
    by created_at high-water mark."""
    try:
        from ..memory.genome import genome_path
    except ImportError:
        return [], since_ts
    path = genome_path()
    if not path.exists():
        return [], since_ts
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], since_ts
    out: list[dict] = []
    max_ts = since_ts
    for mid, m in data.items():
        ts = float(m.get("created_at", 0))
        if ts <= since_ts:
            continue
        max_ts = max(max_ts, ts)
        out.append({
            "id": str(mid),
            "text": m.get("text", ""),
            "tags": m.get("tags") or [],
            "confidence": float(m.get("confidence", 0.5)),
            "ts": ts,
        })
    return out, max_ts


def push_deltas(
    home: Path, url: str, token: str,
    *,
    transport: Transport | None = None,
    state: SyncState | None = None,
) -> dict[str, Any]:
    """Scan local artifacts → POST to <url>/sync/push.

    Returns the server's count summary plus the new SyncState. Caller is
    expected to persist the state via `state.save(home)` (the convenience
    `forge sync push` CLI does this automatically).
    """
    home = Path(home)
    transport = transport or _default_transport
    state = state or SyncState.load(home)

    projects, agents, agents_ts = _scan_agents(home, state.last_agents_ts)
    changelog, changelog_ts = _scan_results_tsv(home, state.last_changelog_ts)
    genome, genome_ts = _scan_genome(state.last_genome_ts)

    body = {
        "projects": projects,
        "agents": agents,
        "runs": [],   # v1: no run-level push (RunRow lands via direct local→DB later)
        "changelog": changelog,
        "genome": genome,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Forge-Sync-Token": token,
    }
    target = url.rstrip("/") + "/sync/push"
    counts = transport(target, json.dumps(body).encode("utf-8"), headers)

    # advance state on success
    state.last_agents_ts = agents_ts
    state.last_changelog_ts = changelog_ts
    state.last_genome_ts = genome_ts
    state.last_runs_ts = time.time()  # placeholder for v2

    return {"counts": counts, "state": state}
