"""FastAPI dashboard — Workspace · Changelog · Genome.

Three nav tabs only (per user requirement). Workspace has the agents
list + orchestrator chat side-by-side. v1 is read-only against synthetic
or sync-pushed data; orchestrator chat (C-2) and local-cloud sync (C-3)
ride on top of this scaffold.
"""
from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from fastapi import (
        Depends, FastAPI, Form, Header, HTTPException, Query, Request, Response,
        status,
    )
    from fastapi.responses import (
        HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse,
    )
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from sqlmodel import Session, select
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "forge.dashboard requires the [dashboard] extra. "
        "Install with: pip install 'forge-harness[dashboard]'"
    ) from e

from .auth import auth, require_auth, setup_auth, verify_password, hash_password
from .db import (
    AgentRow, ChangelogEntry, GenomeMemory, OrchestratorMessage,
    PendingAction, Project, RunRow, init_db, make_engine,
)
from .settings import Settings, settings_dict


log = logging.getLogger("forge.dashboard.server")
_BASE = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(_BASE / "templates"))


@asynccontextmanager
async def _lifespan(app: FastAPI):
    s = Settings()
    setup_auth(s)
    engine = make_engine(s.database_url)
    init_db(engine)
    app.state.engine = engine
    app.state.settings = s
    log.info(
        "forge dashboard started: db=%s auth=%s",
        s.database_url.split("://", 1)[0],
        "enabled" if not auth.open_mode else "OPEN MODE",
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="forge dashboard", version="0.1", lifespan=_lifespan)
    app.mount("/static", StaticFiles(directory=str(_BASE / "static")), name="static")
    _register_routes(app)
    return app


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _register_routes(app: FastAPI) -> None:

    def _session(request: Request) -> Session:
        return Session(request.app.state.engine)

    # ---- public ----------------------------------------------------------

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok"

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, error: str | None = None):
        return TEMPLATES.TemplateResponse(
            request, "login.html", {"error": error},
        )

    @app.post("/login")
    def login_submit(
        request: Request,
        password: str = Form(...),
    ):
        ip = (request.client.host if request.client else "unknown") or "unknown"
        if not auth.can_login(ip):
            return TEMPLATES.TemplateResponse(
                request, "login.html",
                {"error": "Too many attempts. Wait a minute."},
                status_code=429,
            )
        s: Settings = request.app.state.settings
        if auth.open_mode or verify_password(password, hash_password(s.dashboard_password)) \
                or (s.dashboard_password and verify_password(password, auth.password_hash or b"")):
            resp = RedirectResponse("/workspace", status_code=303)
            auth.issue_session(resp)
            return resp
        return TEMPLATES.TemplateResponse(
            request, "login.html",
            {"error": "Invalid password."},
            status_code=401,
        )

    @app.get("/logout")
    def logout(request: Request):
        resp = RedirectResponse("/login", status_code=303)
        auth.revoke_session(resp)
        return resp

    # ---- protected -------------------------------------------------------

    @app.get("/")
    def root(_user: str = Depends(require_auth)):
        return RedirectResponse("/workspace", status_code=303)

    @app.get("/workspace", response_class=HTMLResponse)
    def workspace(
        request: Request,
        _user: str = Depends(require_auth),
    ):
        with _session(request) as ses:
            projects = ses.exec(select(Project).order_by(Project.name)).all()
            agents = ses.exec(select(AgentRow).order_by(AgentRow.last_seen_at.desc())).all()
            pending = ses.exec(
                select(PendingAction).where(PendingAction.status == "pending")
            ).all()
        # Group agents by project.
        by_proj: dict[str, list[AgentRow]] = {}
        proj_lookup = {p.id: p for p in projects}
        for a in agents:
            by_proj.setdefault(a.project_id, []).append(a)
        return TEMPLATES.TemplateResponse(
            request, "workspace.html",
            {
                "projects": projects,
                "by_proj": by_proj,
                "proj_lookup": proj_lookup,
                "pending": pending,
                "agents_total": len(agents),
            },
        )

    @app.get("/workspace/agents/{agent_id}", response_class=HTMLResponse)
    def agent_panel(
        request: Request, agent_id: str,
        _user: str = Depends(require_auth),
    ):
        with _session(request) as ses:
            agent = ses.get(AgentRow, agent_id)
            if agent is None:
                raise HTTPException(404, "agent not found")
            runs = ses.exec(
                select(RunRow).where(RunRow.agent_id == agent_id)
                .order_by(RunRow.started_at.desc()).limit(20)
            ).all()
        return TEMPLATES.TemplateResponse(
            request, "agent_panel.html",
            {"agent": agent, "runs": runs},
        )

    @app.post("/workspace/agents/{agent_id}/edit")
    def agent_edit(
        request: Request, agent_id: str,
        instructions: str = Form(""),
        tools_denied: str = Form(""),
        _user: str = Depends(require_auth),
    ):
        # v1 allow-list: only `instructions` and `tools_denied` editable directly.
        with _session(request) as ses:
            agent = ses.get(AgentRow, agent_id)
            if agent is None:
                raise HTTPException(404, "agent not found")
            agent.instructions = instructions
            agent.tools_denied = [t.strip() for t in tools_denied.split(",") if t.strip()]
            ses.add(agent)
            ses.add(ChangelogEntry(
                id=f"cl_{uuid.uuid4().hex[:12]}",
                kind="agent_edit",
                title=f"edited {agent.name}",
                body_md=f"Updated instructions + tools_denied for `{agent.name}` "
                        f"in project `{agent.project_id}`.",
                ref_path=f"/workspace/agents/{agent_id}",
            ))
            ses.commit()
        return RedirectResponse(f"/workspace/agents/{agent_id}", status_code=303)

    @app.get("/changelog", response_class=HTMLResponse)
    def changelog(
        request: Request,
        kind: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
        _user: str = Depends(require_auth),
    ):
        with _session(request) as ses:
            stmt = select(ChangelogEntry).order_by(ChangelogEntry.ts.desc())
            if kind:
                stmt = stmt.where(ChangelogEntry.kind == kind)
            entries = ses.exec(stmt.limit(limit)).all()
        return TEMPLATES.TemplateResponse(
            request, "changelog.html",
            {"entries": entries, "kind_filter": kind},
        )

    @app.get("/genome", response_class=HTMLResponse)
    def genome(
        request: Request,
        q: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
        _user: str = Depends(require_auth),
    ):
        with _session(request) as ses:
            stmt = select(GenomeMemory).order_by(GenomeMemory.ts.desc())
            if q:
                # naive contains-match; vector search wired later.
                stmt = stmt.where(GenomeMemory.text.contains(q))
            mems = ses.exec(stmt.limit(limit)).all()
            total = ses.exec(select(GenomeMemory)).all()
        return TEMPLATES.TemplateResponse(
            request, "genome.html",
            {"memories": mems, "q": q or "", "total": len(total)},
        )

    # ---- orchestrator chat (C-2) ----------------------------------------

    @app.post("/orchestrator/turn", response_class=HTMLResponse)
    async def orchestrator_turn(
        request: Request,
        message: str = Form(...),
        session_id: str | None = Form(None),
        _user: str = Depends(require_auth),
    ):
        """Run one orchestrator chat turn. Returns user+assistant messages
        rendered for HTMX `beforeend` swap into #chat-log."""
        from ..orchestrator.agent import OrchestratorAgent
        s: Settings = request.app.state.settings
        if not s.anthropic_api_key and not getattr(request.app.state, "_test_provider", None):
            return HTMLResponse(
                '<div class="text-amber-700 text-xs p-2">'
                'orchestrator chat needs ANTHROPIC_API_KEY set in env</div>',
                status_code=503,
            )
        sid = session_id or f"chat_{uuid.uuid4().hex[:12]}"
        provider_override = getattr(request.app.state, "_test_provider", None)

        def _ses_factory() -> Session:
            return Session(request.app.state.engine)

        agent = OrchestratorAgent(
            ses_factory=_ses_factory,
            profile=s.orchestrator_profile,
            provider=provider_override,
        )
        try:
            result = await agent.chat_turn(sid, message)
        except Exception as e:
            log.exception("orchestrator turn failed")
            return HTMLResponse(
                f'<div class="text-rose-700 text-xs p-2">orchestrator error: {e}</div>',
                status_code=500,
            )
        return TEMPLATES.TemplateResponse(
            request, "chat_message.html",
            {
                "session_id": sid,
                "user_msg": message,
                "reply": result["reply"],
                "actions": result.get("actions") or [],
                "tool_calls": result.get("tool_calls") or [],
            },
        )

    # ---- sync (HTTP API for local↔cloud bridge — wired in C-3) -----------

    def _check_sync_token(token: str | None, settings: Settings) -> None:
        if not settings.sync_shared_secret:
            raise HTTPException(503, "sync disabled (SYNC_SHARED_SECRET not set)")
        if not token or not _consteq(token, settings.sync_shared_secret):
            raise HTTPException(401, "invalid sync token")

    @app.post("/sync/push")
    async def sync_push(
        request: Request,
        x_forge_sync_token: str | None = Header(None),
    ):
        s: Settings = request.app.state.settings
        _check_sync_token(x_forge_sync_token, s)
        body = await request.json()
        from .sync_handlers import apply_sync_push
        with _session(request) as ses:
            counts = apply_sync_push(ses, body)
            ses.commit()
        return JSONResponse(counts)

    @app.get("/sync/pending")
    def sync_pending(
        request: Request,
        x_forge_sync_token: str | None = Header(None),
    ):
        s: Settings = request.app.state.settings
        _check_sync_token(x_forge_sync_token, s)
        with _session(request) as ses:
            pending = ses.exec(
                select(PendingAction).where(PendingAction.status == "approved")
            ).all()
            return JSONResponse([
                {"id": p.id, "kind": p.kind, "payload": p.payload_json}
                for p in pending
            ])

    @app.post("/sync/applied/{action_id}")
    async def sync_applied(
        request: Request, action_id: str,
        x_forge_sync_token: str | None = Header(None),
    ):
        s: Settings = request.app.state.settings
        _check_sync_token(x_forge_sync_token, s)
        diff = await request.json()
        with _session(request) as ses:
            action = ses.get(PendingAction, action_id)
            if action is None:
                raise HTTPException(404, "no such action")
            action.status = "applied"
            action.applied_at = datetime.now(timezone.utc)
            action.applied_diff_json = diff
            ses.add(action)
            ses.add(ChangelogEntry(
                id=f"cl_{uuid.uuid4().hex[:12]}",
                kind="agent_spawn" if action.kind == "spawn_agent"
                     else "project_start" if action.kind == "start_project"
                     else "agent_edit",
                title=f"applied: {action.kind}",
                body_md=f"```json\n{diff}\n```",
            ))
            ses.commit()
        return {"ok": True}

    @app.post("/sync/propose-design")
    async def sync_propose_design(
        request: Request,
        x_forge_sync_token: str | None = Header(None),
    ):
        """Receive a `forge new --where dashboard` design payload and queue it
        as a PendingAction for the user to Approve in the workspace."""
        s: Settings = request.app.state.settings
        _check_sync_token(x_forge_sync_token, s)
        body = await request.json()
        kind = body.get("kind", "start_project")
        payload = body.get("payload") or {}
        action_id = f"pa_{uuid.uuid4().hex[:12]}"
        with _session(request) as ses:
            ses.add(PendingAction(
                id=action_id, kind=kind, payload_json=payload,
                status="pending", proposed_by="forge-new",
            ))
            ses.commit()
        return {"id": action_id, "status": "pending"}

    # ---- pending action approve/reject (no orchestrator yet — buttons just flip status)

    @app.post("/actions/{action_id}/approve")
    def approve(
        request: Request, action_id: str,
        _user: str = Depends(require_auth),
    ):
        with _session(request) as ses:
            action = ses.get(PendingAction, action_id)
            if action is None:
                raise HTTPException(404, "no such action")
            if action.status != "pending":
                raise HTTPException(409, f"action already {action.status}")
            action.status = "approved"
            action.approved_at = datetime.now(timezone.utc)
            ses.add(action); ses.commit()
        return {"ok": True, "status": "approved"}

    @app.post("/actions/{action_id}/reject")
    def reject(
        request: Request, action_id: str,
        _user: str = Depends(require_auth),
    ):
        with _session(request) as ses:
            action = ses.get(PendingAction, action_id)
            if action is None:
                raise HTTPException(404, "no such action")
            if action.status != "pending":
                raise HTTPException(409, f"action already {action.status}")
            action.status = "rejected"
            ses.add(action); ses.commit()
        return {"ok": True, "status": "rejected"}


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def _consteq(a: str, b: str) -> bool:
    """Constant-time string compare."""
    if len(a) != len(b):
        return False
    out = 0
    for x, y in zip(a, b):
        out |= ord(x) ^ ord(y)
    return out == 0


# Module-level app for `uvicorn forge.dashboard.server:app`.
app = create_app()
