"""OrchestratorAgent — chats with the user, emits PendingActions.

Runs INSIDE the dashboard process (Anthropic API key from env). One
turn = one provider call, possibly with tool_use blocks. Tool calls
modify the DB (insert PendingAction, list agents, etc.). Final
assistant text is the chat reply.

For v1 simplicity we run one turn per HTTP request rather than SSE
streaming. The HTMX form posts a message and gets back the rendered
chat-message HTML appended to the chat-log div.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..dashboard.db import (
    AgentRow, ChangelogEntry, GenomeMemory, OrchestratorMessage,
    PendingAction, Project,
)
from . import actions as A


log = logging.getLogger("forge.orchestrator.agent")

PERSONA_PATH = Path(__file__).parent / "persona.md"


def _persona() -> str:
    try:
        return PERSONA_PATH.read_text(encoding="utf-8")
    except OSError:
        return "You are forge's orchestrator. Be concise. Use propose_* tools to suggest mutations."


# Tool schemas (Anthropic message-format-compatible). The OrchestratorAgent
# dispatches each tool call to a handler that touches the DB session.
_TOOLS_SCHEMA = [
    {
        "name": "list_agents",
        "description": "List every agent across all projects.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_status",
        "description": "Get full detail on one agent by name.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "recent_changelog",
        "description": "Recent self-improvement events. Optional kind filter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "genome_search",
        "description": "Search cross-project memories by substring.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "propose_spawn",
        "description": "Propose a new agent. Inserts a PendingAction; user must Approve in the dashboard.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "name": {"type": "string"},
                "instructions": {"type": "string"},
                "profile": {"type": "string"},
                "tools_allowed": {"type": "array", "items": {"type": "string"}},
                "tools_denied": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["project", "name", "instructions", "profile"],
        },
    },
    {
        "name": "propose_update",
        "description": "Propose an update to an existing agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "patch": {"type": "object"},
            },
            "required": ["name", "patch"],
        },
    },
    {
        "name": "propose_start_project",
        "description": "Propose scaffolding a new vertical. template ∈ {operator, research, sdr, custom}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "template": {"type": "string", "enum": ["operator", "research", "sdr", "custom"]},
                "description": {"type": "string"},
            },
            "required": ["name", "template"],
        },
    },
    {
        "name": "propose_run_recurse",
        "description": "Request a recursion cycle on a forge home dir.",
        "input_schema": {
            "type": "object",
            "properties": {
                "home": {"type": "string"},
                "with_intel": {"type": "boolean"},
                "profile": {"type": "string"},
            },
        },
    },
]


class OrchestratorAgent:
    """One instance per dashboard process. Stateless across turns —
    chat history persists in `orchestrator_messages` table."""

    def __init__(
        self,
        ses_factory,                  # callable: () -> Session (per-turn)
        provider=None,                 # injectable; defaults to anthropic make_provider
        profile: str = "anthropic",
        max_tool_iterations: int = 6,
    ) -> None:
        self.ses_factory = ses_factory
        self.profile_name = profile
        self.max_tool_iterations = max_tool_iterations
        self._provider = provider

    def _ensure_provider(self):
        if self._provider is not None:
            return self._provider
        from ..providers import make_provider
        self._provider = make_provider(self.profile_name)
        return self._provider

    async def chat_turn(
        self, session_id: str, user_msg: str,
    ) -> dict[str, Any]:
        """Run one chat turn. Returns {"reply": str, "actions": [ids],
        "tool_calls": [{name, input, result}]}.

        Persists user + assistant messages to OrchestratorMessage. Loops
        on tool_use up to `max_tool_iterations` times before forcing a
        final text response.
        """
        from ..kernel.types import Message

        provider = self._ensure_provider()
        with self.ses_factory() as ses:
            self._persist_msg(ses, session_id, "user", user_msg)
            history = self._load_history(ses, session_id, limit=20)

        system_text = _persona() + "\n\n" + self._render_workspace_context()
        messages: list[Message] = [Message(role="system", content=system_text)]
        messages.extend(
            Message(role=m["role"], content=m["content"])
            for m in history
        )

        actions_emitted: list[str] = []
        tool_log: list[dict] = []

        for _ in range(self.max_tool_iterations):
            turn = await provider.generate(
                messages=messages,
                tools=_TOOLS_SCHEMA,
                max_tokens=2048,
            )
            if not turn.tool_calls:
                # Final text turn — done.
                final_text = turn.text or "(no reply)"
                with self.ses_factory() as ses:
                    self._persist_msg(ses, session_id, "assistant", final_text)
                return {
                    "reply": final_text,
                    "actions": actions_emitted,
                    "tool_calls": tool_log,
                }
            # Run each tool call, append a tool_result message, loop.
            messages.append(Message(role="assistant", content=turn.text or "",
                                    metadata={"tool_calls": [
                                        {"id": tc.id, "name": tc.name, "input": tc.arguments}
                                        for tc in turn.tool_calls
                                    ]}))
            for tc in turn.tool_calls:
                with self.ses_factory() as ses:
                    result, action_id = self._dispatch(ses, tc.name, tc.arguments)
                tool_log.append({"name": tc.name, "input": tc.arguments,
                                 "result": result, "action_id": action_id})
                if action_id:
                    actions_emitted.append(action_id)
                messages.append(Message(
                    role="tool", content=json.dumps(result, default=str),
                    tool_call_id=tc.id, name=tc.name,
                ))

        # Iteration cap reached — force a final reply.
        fallback = ("(orchestrator: tool-call iteration cap reached; "
                    "review the partial results above and rephrase if needed)")
        with self.ses_factory() as ses:
            self._persist_msg(ses, session_id, "assistant", fallback)
        return {"reply": fallback, "actions": actions_emitted, "tool_calls": tool_log}

    # ---- helpers --------------------------------------------------------

    def _persist_msg(self, ses: Session, session_id: str, role: str, content: str) -> None:
        ses.add(OrchestratorMessage(
            id=f"om_{uuid.uuid4().hex[:12]}",
            session_id=session_id, role=role, content=content,
        ))
        ses.commit()

    def _load_history(self, ses: Session, session_id: str, limit: int) -> list[dict]:
        rows = ses.exec(
            select(OrchestratorMessage).where(OrchestratorMessage.session_id == session_id)
            .order_by(OrchestratorMessage.ts).limit(limit)
        ).all()
        return [{"role": r.role, "content": r.content} for r in rows]

    def _render_workspace_context(self) -> str:
        """Snapshot of the workspace state, prepended to every system prompt
        so the orchestrator has live context."""
        with self.ses_factory() as ses:
            agents = ses.exec(select(AgentRow).limit(50)).all()
            projects = ses.exec(select(Project).limit(20)).all()
            recent_cl = ses.exec(
                select(ChangelogEntry).order_by(ChangelogEntry.ts.desc()).limit(10)
            ).all()
            pending = ses.exec(
                select(PendingAction).where(PendingAction.status == "pending").limit(10)
            ).all()
        lines = ["## Workspace snapshot", f"projects: {[p.name for p in projects] or 'none'}"]
        if agents:
            lines.append("agents:")
            for a in agents:
                lines.append(f"  - {a.name} (project={a.project_id}, profile={a.profile})")
        if recent_cl:
            lines.append("recent changelog (newest first):")
            for c in recent_cl:
                lines.append(f"  - [{c.kind}] {c.title}")
        if pending:
            lines.append(f"pending actions ({len(pending)}):")
            for p in pending:
                lines.append(f"  - {p.id} {p.kind} {p.payload_json}")
        return "\n".join(lines)

    def _dispatch(
        self, ses: Session, name: str, args: dict,
    ) -> tuple[Any, str | None]:
        """Run one tool call against the DB. Returns (result, action_id?)."""
        try:
            if name == "list_agents":
                rows = ses.exec(select(AgentRow).limit(50)).all()
                return [
                    {"id": r.id, "name": r.name, "project": r.project_id,
                     "profile": r.profile, "status": r.status}
                    for r in rows
                ], None
            if name == "agent_status":
                row = ses.exec(
                    select(AgentRow).where(AgentRow.name == args["name"])
                ).first()
                if not row:
                    return {"error": f"no agent named {args['name']!r}"}, None
                return {
                    "id": row.id, "name": row.name, "profile": row.profile,
                    "instructions": row.instructions[:600],
                    "tools_allowed": row.tools_allowed,
                    "tools_denied": row.tools_denied,
                    "total_runs": row.total_runs, "total_cost_usd": row.total_cost_usd,
                }, None
            if name == "recent_changelog":
                stmt = select(ChangelogEntry).order_by(ChangelogEntry.ts.desc())
                if args.get("kind"):
                    stmt = stmt.where(ChangelogEntry.kind == args["kind"])
                limit = min(int(args.get("limit", 20)), 50)
                rows = ses.exec(stmt.limit(limit)).all()
                return [
                    {"ts": r.ts.isoformat(), "kind": r.kind, "title": r.title}
                    for r in rows
                ], None
            if name == "genome_search":
                q = args["query"]
                k = min(int(args.get("k", 5)), 20)
                rows = ses.exec(
                    select(GenomeMemory).where(GenomeMemory.text.contains(q)).limit(k)
                ).all()
                return [
                    {"id": r.id, "text": r.text[:240], "tags": r.tags,
                     "confidence": r.confidence}
                    for r in rows
                ], None
            if name == "propose_spawn":
                aid = A.propose_spawn(ses, **{k: v for k, v in args.items()
                                              if k in {"project","name","instructions","profile",
                                                       "tools_allowed","tools_denied"}})
                return {"action_id": aid, "status": "pending",
                        "instruction": "user must Approve in dashboard"}, aid
            if name == "propose_update":
                aid = A.propose_update(ses, name=args["name"], patch=args["patch"])
                return {"action_id": aid, "status": "pending"}, aid
            if name == "propose_start_project":
                aid = A.propose_start_project(
                    ses, name=args["name"], template=args["template"],
                    description=args.get("description", ""),
                )
                return {"action_id": aid, "status": "pending"}, aid
            if name == "propose_run_recurse":
                aid = A.propose_run_recurse(
                    ses, home=args.get("home"),
                    with_intel=bool(args.get("with_intel", False)),
                    profile=args.get("profile"),
                )
                return {"action_id": aid, "status": "pending"}, aid
            return {"error": f"unknown tool: {name}"}, None
        except Exception as e:  # noqa: BLE001
            log.warning("orchestrator tool %s failed: %s", name, e)
            return {"error": str(e)}, None
