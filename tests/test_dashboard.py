"""End-to-end tests for the FastAPI dashboard.

Boots the app against in-memory SQLite, exercises every nav route,
verifies auth gate, sync API idempotency, and pending-action lifecycle.
Uses fastapi.TestClient — no live network.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

# Skip the whole module if the [dashboard] extra isn't installed.
fastapi = pytest.importorskip("fastapi")
sqlmodel = pytest.importorskip("sqlmodel")


def _fresh_app(tmp_path, monkeypatch, password=""):
    """Build a brand-new FastAPI app with isolated SQLite, env, and auth.

    SQLModel metadata is module-global, so we don't reload db.py — we just
    let `init_db` re-create_all() against a fresh engine. The metadata
    lives once; the engine is per-test.
    """
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("DASHBOARD_PASSWORD", password)
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-characters-min____")
    monkeypatch.setenv("SYNC_SHARED_SECRET", "test-sync-token")
    from forge.dashboard.server import create_app
    return create_app()


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """Fresh in-memory SQLite + auth-disabled app per test."""
    app = _fresh_app(tmp_path, monkeypatch, password="")
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.text == "ok"


def test_root_redirects_to_workspace(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/workspace"


def test_workspace_renders_three_tabs_in_light_mode(client):
    r = client.get("/workspace")
    assert r.status_code == 200
    body = r.text
    # Three nav tabs (text inside anchor, not necessarily adjacent to '>').
    assert "Workspace" in body
    assert "Changelog" in body
    assert "Genome" in body
    assert 'href="/workspace"' in body
    assert 'href="/changelog"' in body
    assert 'href="/genome"' in body
    # Light mode classes.
    assert "bg-slate-50" in body
    # Empty-state copy.
    assert "No agents yet" in body or "agents" in body.lower()


def test_changelog_renders_empty_state(client):
    r = client.get("/changelog")
    assert r.status_code == 200
    assert "Changelog" in r.text
    # Filter chips visible.
    assert "kind=mod_kept" in r.text
    assert "kind=denial_loop" in r.text


def test_genome_renders_empty_state(client):
    r = client.get("/genome")
    assert r.status_code == 200
    assert "Genome" in r.text
    assert "search" in r.text.lower()


# ---------------------------------------------------------------------------
# Sync API
# ---------------------------------------------------------------------------

def test_sync_push_requires_token(client):
    r = client.post("/sync/push", json={})
    assert r.status_code == 401


def test_sync_push_idempotent_upsert(client):
    body = {
        "projects": [{"id": "p1", "name": "forge", "slug": "forge"}],
        "agents": [{
            "id": "a1", "project_id": "p1", "name": "operator",
            "profile": "anthropic", "instructions": "do things",
            "tools_denied": ["shell"], "total_runs": 3, "total_cost_usd": 0.42,
        }],
        "changelog": [{
            "id": "c1", "ts": "2026-04-26T08:00:00+00:00",
            "kind": "mod_kept", "title": "kept retune",
            "body_md": "score +0.20",
        }],
        "genome": [{
            "id": "m1", "text": "MCP tool catalog endpoint shipped",
            "tags": ["mcp"], "confidence": 0.85,
            "ts": "2026-04-26T08:00:00+00:00",
        }],
    }
    h = {"X-Forge-Sync-Token": "test-sync-token"}
    r1 = client.post("/sync/push", json=body, headers=h)
    assert r1.status_code == 200
    counts1 = r1.json()
    assert counts1["projects"] == 1 and counts1["agents"] == 1
    assert counts1["changelog"] == 1 and counts1["genome"] == 1

    # Re-push same body — no duplicate inserts.
    r2 = client.post("/sync/push", json=body, headers=h)
    assert r2.status_code == 200
    counts2 = r2.json()
    # changelog counted only on insert; genome upserts but doesn't dup.
    assert counts2["changelog"] == 0

    # Workspace now shows the agent.
    r3 = client.get("/workspace")
    assert r3.status_code == 200
    assert "operator" in r3.text
    assert "forge" in r3.text  # project name

    # Changelog renders the entry.
    r4 = client.get("/changelog")
    assert "kept retune" in r4.text
    assert "mod_kept" in r4.text

    # Genome renders the memory.
    r5 = client.get("/genome")
    assert "MCP tool catalog" in r5.text


def test_sync_pending_filters_by_approved_status(client):
    h = {"X-Forge-Sync-Token": "test-sync-token"}
    # Insert a pending action via direct DB write (no orchestrator yet).
    from forge.dashboard.db import PendingAction
    from sqlmodel import Session
    with Session(client.app.state.engine) as ses:
        ses.add(PendingAction(
            id="pa1", kind="spawn_agent",
            payload_json={"name": "notion_summarizer"},
            status="pending",
        ))
        ses.add(PendingAction(
            id="pa2", kind="spawn_agent",
            payload_json={"name": "x"},
            status="approved",
        ))
        ses.commit()

    r = client.get("/sync/pending", headers=h)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["id"] == "pa2"


def test_action_approve_then_reject_locked(client):
    """Approve flips to approved; subsequent reject 409s."""
    from forge.dashboard.db import PendingAction
    from sqlmodel import Session
    with Session(client.app.state.engine) as ses:
        ses.add(PendingAction(
            id="pa1", kind="spawn_agent",
            payload_json={"name": "x"},
            status="pending",
        ))
        ses.commit()

    r1 = client.post("/actions/pa1/approve")
    assert r1.status_code == 200, r1.text
    r2 = client.post("/actions/pa1/reject")
    assert r2.status_code == 409


def test_action_unknown_id_404(client):
    r = client.post("/actions/nope/approve")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Mutating endpoints reject GET
# ---------------------------------------------------------------------------

def test_mutating_endpoints_reject_get(client):
    for path in ["/sync/push", "/actions/x/approve", "/actions/x/reject",
                 "/sync/applied/x"]:
        r = client.get(path)
        assert r.status_code in (404, 405), f"{path}: {r.status_code}"


# ---------------------------------------------------------------------------
# Auth gate (separate fixture: with password configured)
# ---------------------------------------------------------------------------

@pytest.fixture()
def auth_client(monkeypatch, tmp_path):
    app = _fresh_app(tmp_path, monkeypatch, password="letmein")
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


def test_protected_redirects_to_login_when_unauthed(auth_client):
    auth_client.cookies.clear()
    r = auth_client.get("/workspace", follow_redirects=False,
                        headers={"accept": "text/html"})
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_with_correct_password(auth_client):
    auth_client.cookies.clear()
    r = auth_client.post("/login", data={"password": "letmein"},
                         follow_redirects=False)
    assert r.status_code == 303
    assert "forge_session" in r.cookies or "set-cookie" in {k.lower(): v for k, v in r.headers.items()}
    # Now the protected route renders.
    r2 = auth_client.get("/workspace")
    assert r2.status_code == 200


def test_login_with_wrong_password(auth_client):
    auth_client.cookies.clear()
    r = auth_client.post("/login", data={"password": "wrong"})
    assert r.status_code == 401
    assert "Invalid password" in r.text
