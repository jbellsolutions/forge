"""Heartbeat runner — `.claude/heartbeats/*.md` as files-as-cron-jobs.

Each heartbeat is a markdown file with optional YAML frontmatter:
  ---
  schedule: "07:00 daily"          # informational; OS scheduler enforces cadence
  agent: operator                  # which vertical to run
  ---
  # Morning Brief
  ... task body ...

`run_all(dir)` reads every .md, runs each through the configured vertical, and
records the outcome. Designed to be called from `cron` / `launchd` / GitHub Actions:

  forge heartbeat run --dir ~/.forge/operator-real/.claude/heartbeats
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("forge.heartbeat")

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _parse(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    fm = yaml.safe_load(m.group(1)) or {}
    return fm, raw[m.end():]


async def run_one(path: Path, *, log_dir: Path | None = None) -> dict[str, Any]:
    """Run a single heartbeat. Returns a result dict."""
    fm, body = _parse(path)
    title = path.stem
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    # The "execution" of a heartbeat in this scaffold is to invoke the configured
    # vertical's run.py via subprocess if `agent` is set, otherwise to log.
    import subprocess
    import sys
    repo_root = Path(__file__).resolve().parents[2]
    target = None
    if "agent" in fm:
        candidate = repo_root / "examples" / fm["agent"] / "run.py"
        if candidate.exists():
            target = candidate

    record: dict[str, Any] = {
        "started": started,
        "heartbeat": title,
        "schedule": fm.get("schedule", "ad-hoc"),
        "agent": fm.get("agent"),
    }
    if target:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(target),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
            record["returncode"] = proc.returncode
            record["stdout_tail"] = stdout.decode(errors="replace")[-2000:]
            record["stderr_tail"] = stderr.decode(errors="replace")[-1000:]
        except asyncio.TimeoutError:
            record["returncode"] = -1
            record["error"] = "timeout"
    else:
        record["returncode"] = 0
        record["note"] = "no agent target; logged only"

    record["ended"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (log_dir / f"{title}-{ts}.json").write_text(json.dumps(record, indent=2))
    return record


async def run_all(directory: Path) -> int:
    """Run every .md in `directory`. Returns 0 if all succeeded."""
    directory = Path(directory).expanduser()
    if not directory.exists():
        log.warning("heartbeat dir does not exist: %s", directory)
        return 0
    log_dir = directory.parent / "heartbeat-logs"
    files = sorted(directory.glob("*.md"))
    if not files:
        print(f"[heartbeat] no .md files in {directory}")
        return 0
    print(f"[heartbeat] running {len(files)} heartbeats from {directory}")
    rc = 0
    for path in files:
        record = await run_one(path, log_dir=log_dir)
        status = "ok" if record.get("returncode") == 0 else "FAIL"
        print(f"[heartbeat] {status:4s} {path.name}  rc={record.get('returncode')}")
        if record.get("returncode") not in (0, None):
            rc = 1
    return rc
