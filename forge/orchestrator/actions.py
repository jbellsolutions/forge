"""PendingAction proposers — the orchestrator's only side-effects.

Each `propose_*` function inserts one `PendingAction` row and returns
its ID. The action sits as `status='pending'` until a human clicks
Approve in the dashboard; then local forge picks it up via sync pull
and applies. Schema for each `kind` is validated at apply time
(`apply_pending`) — see C-3 sync/pull.py.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import Session

from ..dashboard.db import PendingAction


# ---------------------------------------------------------------------------
# Schemas — every PendingAction.payload_json must match the kind's schema
# at apply time. Keep these light; full validation lives where the action
# is actually applied (forge.sync.pull.apply_pending in C-3).
# ---------------------------------------------------------------------------

PROPOSE_SCHEMAS: dict[str, dict[str, Any]] = {
    "spawn_agent": {
        "required": ["project", "name", "instructions", "profile"],
        "optional": ["tools_allowed", "tools_denied"],
    },
    "update_agent": {
        "required": ["name", "patch"],
        "optional": [],
    },
    "start_project": {
        "required": ["name", "template"],  # template ∈ {operator, research, sdr, custom}
        "optional": ["description"],
    },
    "run_recurse": {
        "required": [],
        "optional": ["home", "with_intel", "profile"],
    },
}


def _new_id(prefix: str = "pa") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _validate(kind: str, payload: dict[str, Any]) -> None:
    schema = PROPOSE_SCHEMAS.get(kind)
    if schema is None:
        raise ValueError(f"unknown action kind: {kind!r}")
    missing = [k for k in schema["required"]
               if k not in payload or payload[k] in (None, "")]
    if missing:
        raise ValueError(f"{kind}: missing required keys: {missing}")


def propose_spawn(
    ses: Session, *,
    project: str, name: str, instructions: str, profile: str,
    tools_allowed: list[str] | None = None,
    tools_denied: list[str] | None = None,
) -> str:
    payload = {
        "project": project, "name": name,
        "instructions": instructions, "profile": profile,
    }
    if tools_allowed is not None:
        payload["tools_allowed"] = tools_allowed
    if tools_denied is not None:
        payload["tools_denied"] = tools_denied
    _validate("spawn_agent", payload)
    action_id = _new_id()
    ses.add(PendingAction(
        id=action_id, kind="spawn_agent",
        payload_json=payload, status="pending",
        proposed_by="orchestrator",
    ))
    ses.commit()
    return action_id


def propose_update(ses: Session, *, name: str, patch: dict[str, Any]) -> str:
    payload = {"name": name, "patch": patch}
    _validate("update_agent", payload)
    action_id = _new_id()
    ses.add(PendingAction(
        id=action_id, kind="update_agent",
        payload_json=payload, status="pending",
        proposed_by="orchestrator",
    ))
    ses.commit()
    return action_id


def propose_start_project(
    ses: Session, *,
    name: str, template: str, description: str = "",
) -> str:
    if template not in {"operator", "research", "sdr", "custom"}:
        raise ValueError(f"unknown template: {template}")
    payload = {"name": name, "template": template, "description": description}
    _validate("start_project", payload)
    action_id = _new_id()
    ses.add(PendingAction(
        id=action_id, kind="start_project",
        payload_json=payload, status="pending",
        proposed_by="orchestrator",
    ))
    ses.commit()
    return action_id


def propose_run_recurse(
    ses: Session, *,
    home: str | None = None,
    with_intel: bool = False,
    profile: str | None = None,
) -> str:
    payload: dict[str, Any] = {"with_intel": with_intel}
    if home: payload["home"] = home
    if profile: payload["profile"] = profile
    _validate("run_recurse", payload)
    action_id = _new_id()
    ses.add(PendingAction(
        id=action_id, kind="run_recurse",
        payload_json=payload, status="pending",
        proposed_by="orchestrator",
    ))
    ses.commit()
    return action_id
