"""Tests for forge.sync — local↔cloud bridge.

End-to-end round trip against a FastAPI TestClient acting as the cloud
dashboard. Asserts:

- push_deltas: scans local agents YAML + results.tsv + genome and POSTs
  to /sync/push. Idempotent on retry (zero new rows).
- pull_pending_actions: GETs /sync/pending, applies each locally, POSTs
  diff back. spawn_agent → writes <home>/agents/<name>.yaml.
- SyncState advances by max-mtime; second push picks up only new rows.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlmodel")


def _fresh_app(tmp_path, monkeypatch):
    db_path = tmp_path / "cloud.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-characters-min____")
    monkeypatch.setenv("SYNC_SHARED_SECRET", "shared-secret")
    from forge.dashboard.server import create_app
    return create_app()


@pytest.fixture()
def client(monkeypatch, tmp_path):
    app = _fresh_app(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fake_transport(client):
    """Forge → TestClient transport pair (POST + GET)."""
    def post(url, body, headers):
        # Strip scheme/host if present; TestClient is path-relative.
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        path = "/" + path if not path.startswith("/") else path
        r = client.post(path, content=body, headers=headers)
        r.raise_for_status()
        return r.json()

    def get(url, headers):
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        path = "/" + path if not path.startswith("/") else path
        r = client.get(path, headers=headers)
        r.raise_for_status()
        return r.json()

    return {"post": post, "get": get}


# ---------------------------------------------------------------------------
# state.py
# ---------------------------------------------------------------------------

def test_sync_state_round_trip(tmp_path):
    from forge.sync.state import SyncState
    s = SyncState(last_agents_ts=123.0)
    s.save(tmp_path)
    loaded = SyncState.load(tmp_path)
    assert loaded.last_agents_ts == 123.0
    assert loaded.last_changelog_ts == 0.0


def test_sync_state_load_missing_returns_default(tmp_path):
    from forge.sync.state import SyncState
    s = SyncState.load(tmp_path)
    assert s.last_agents_ts == 0.0


# ---------------------------------------------------------------------------
# push.py
# ---------------------------------------------------------------------------

def test_push_scans_agents_yaml(tmp_path, client, fake_transport):
    """Write a single agents/foo.yaml → push → DB has 1 project + 1 agent."""
    from forge.sync import push_deltas
    home = tmp_path / "home"
    (home / "agents").mkdir(parents=True)
    (home / "agents" / "foo.yaml").write_text(
        "name: foo\nprofile: anthropic\ninstructions: do stuff\n"
    )
    res = push_deltas(home, "http://test", "shared-secret",
                      transport=fake_transport["post"])
    counts = res["counts"]
    assert counts["agents"] == 1
    assert counts["projects"] == 1
    # Idempotent: second push picks up nothing (mtime unchanged below cursor).
    res["state"].save(home)
    res2 = push_deltas(home, "http://test", "shared-secret",
                       transport=fake_transport["post"])
    assert res2["counts"]["agents"] == 0


def test_push_results_tsv_emits_changelog(tmp_path, client, fake_transport):
    from forge.sync import push_deltas
    home = tmp_path / "home"
    home.mkdir()
    (home / "results.tsv").write_text(
        "timestamp\tcandidate\tbase_score\tcandidate_score\tdelta\tkept\tnotes\n"
        f"{time.time():.3f}\tcand_a\t0.5\t0.7\t+0.2\t1\trecursion-mod\n"
        f"{time.time():.3f}\tcand_b\t0.5\t0.4\t-0.1\t0\trolled-back\n"
    )
    res = push_deltas(home, "http://test", "shared-secret",
                      transport=fake_transport["post"])
    assert res["counts"]["changelog"] == 2


def test_push_rejects_bad_token(tmp_path, client, fake_transport):
    """Wrong shared secret → 401 from /sync/push."""
    from forge.sync import push_deltas
    home = tmp_path / "home"
    home.mkdir()
    with pytest.raises(Exception):  # httpx HTTPStatusError
        push_deltas(home, "http://test", "WRONG",
                    transport=fake_transport["post"])


# ---------------------------------------------------------------------------
# pull.py
# ---------------------------------------------------------------------------

def _seed_pending_action(client_, kind, payload):
    """Hit the DB directly via the TestClient app's engine."""
    from forge.dashboard.db import PendingAction
    from sqlmodel import Session
    engine = client_.app.state.engine
    aid = f"pa_test_{kind}"
    with Session(engine) as ses:
        a = PendingAction(
            id=aid, kind=kind, payload_json=payload,
            status="approved", proposed_by="test",
        )
        ses.add(a)
        ses.commit()
    return aid


def test_pull_applies_spawn_agent(tmp_path, client, fake_transport):
    """Approved spawn_agent → /sync/pending → apply_pending writes YAML."""
    from forge.sync import pull_pending_actions

    aid = _seed_pending_action(client, "spawn_agent", {
        "project": "forge", "name": "notion_summarizer",
        "instructions": "Daily Notion digest.",
        "profile": "anthropic-haiku",
    })
    home = tmp_path / "home"
    results = pull_pending_actions(
        home, "http://test", "shared-secret",
        get_transport=fake_transport["get"],
        post_transport=fake_transport["post"],
    )
    assert len(results) == 1
    assert results[0]["ok"] is True
    yaml_path = home / "agents" / "notion_summarizer.yaml"
    assert yaml_path.exists()
    body = yaml_path.read_text()
    assert "notion_summarizer" in body
    assert "anthropic-haiku" in body

    # Server-side: action flipped to applied.
    from forge.dashboard.db import PendingAction
    from sqlmodel import Session
    with Session(client.app.state.engine) as ses:
        a = ses.get(PendingAction, aid)
        assert a.status == "applied"


def test_pull_handles_unknown_kind_gracefully(tmp_path, client, fake_transport):
    from forge.sync import pull_pending_actions
    _seed_pending_action(client, "frobnicate", {"x": 1})
    home = tmp_path / "home"
    results = pull_pending_actions(
        home, "http://test", "shared-secret",
        get_transport=fake_transport["get"],
        post_transport=fake_transport["post"],
    )
    assert len(results) == 1
    assert results[0]["ok"] is False
    assert "unknown" in results[0]["diff"]["error"].lower()


def test_pull_update_agent_patches_yaml(tmp_path, client, fake_transport):
    from forge.sync import pull_pending_actions
    home = tmp_path / "home"
    (home / "agents").mkdir(parents=True)
    (home / "agents" / "foo.yaml").write_text(
        "name: foo\nprofile: anthropic\ninstructions: original\n"
    )
    _seed_pending_action(client, "update_agent", {
        "name": "foo", "patch": {"instructions": "patched"},
    })
    results = pull_pending_actions(
        home, "http://test", "shared-secret",
        get_transport=fake_transport["get"],
        post_transport=fake_transport["post"],
    )
    assert results[0]["ok"] is True
    body = (home / "agents" / "foo.yaml").read_text()
    assert "patched" in body
