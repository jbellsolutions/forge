"""SQLModel schema for the cloud dashboard.

Six tables, mirroring forge's local artifacts:

- Project           — agents grouped by project (default "forge")
- AgentRow          — every AgentDef known across all projects
- RunRow            — mirror of SessionStat (one per agent run)
- ChangelogEntry    — feed of self-improvement events
- GenomeMemory      — cross-project memories from ~/.forge/genome.json
- PendingAction     — orchestrator-proposed mutations awaiting Approve

OrchestratorMessage rounds out the seven (chat history).

All IDs are stable strings — local forge uses content-addressable hashes
on push so retry / replay is idempotent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    from sqlmodel import Column, Field, JSON, SQLModel, create_engine, Session, select
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "forge.dashboard requires the [dashboard] extra (sqlmodel). "
        "Install with: pip install 'forge-harness[dashboard]'"
    ) from e


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    slug: str = Field(unique=True, index=True)
    created_at: datetime = Field(default_factory=_now)


class AgentRow(SQLModel, table=True):
    __tablename__ = "agents"

    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    name: str = Field(index=True)
    profile: str
    instructions: str = ""
    tools_allowed: list[str] | None = Field(default=None, sa_column=Column(JSON))
    tools_denied: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "active"   # active | paused | retired
    created_at: datetime = Field(default_factory=_now)
    last_seen_at: datetime | None = None
    total_runs: int = 0
    total_cost_usd: float = 0.0


class RunRow(SQLModel, table=True):
    __tablename__ = "runs"

    id: str = Field(primary_key=True)
    agent_id: str = Field(foreign_key="agents.id", index=True)
    session_id: str = Field(index=True)
    started_at: datetime
    ended_at: datetime | None = None
    tool_calls: int = 0
    tool_errors: int = 0
    blocked: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class ChangelogEntry(SQLModel, table=True):
    __tablename__ = "changelog"

    id: str = Field(primary_key=True)
    ts: datetime = Field(default_factory=_now, index=True)
    kind: str = Field(index=True)
    # Allowed kinds (no enum to keep schema soft):
    # recursion | skill_create | skill_promo | skill_rollback |
    # intel_pull | auto_research | mod_kept | mod_rolled |
    # denial_loop | circuit_open | agent_edit | agent_spawn |
    # project_start | digest
    title: str
    body_md: str = ""
    ref_path: str | None = None  # local path/url for drill-down


class GenomeMemory(SQLModel, table=True):
    __tablename__ = "genome"

    id: str = Field(primary_key=True)   # mem_id from ReasoningBank
    text: str
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    confidence: float = 0.5
    ts: datetime = Field(default_factory=_now, index=True)


class PendingAction(SQLModel, table=True):
    __tablename__ = "pending_actions"

    id: str = Field(primary_key=True)
    kind: str = Field(index=True)
    # spawn_agent | update_agent | start_project | run_recurse
    payload_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="pending", index=True)
    # pending | approved | rejected | applied | expired
    proposed_by: str = "orchestrator"
    proposed_at: datetime = Field(default_factory=_now)
    approved_at: datetime | None = None
    applied_at: datetime | None = None
    applied_diff_json: dict | None = Field(default=None, sa_column=Column(JSON))


class OrchestratorMessage(SQLModel, table=True):
    __tablename__ = "orchestrator_messages"

    id: str = Field(primary_key=True)
    session_id: str = Field(index=True)
    role: str
    content: str
    ts: datetime = Field(default_factory=_now, index=True)


# ---------------------------------------------------------------------------
# Engine + session helper
# ---------------------------------------------------------------------------

def make_engine(database_url: str):
    """Create SQLModel engine. SQLite gets check_same_thread=False so the
    test client can hit the same connection across requests."""
    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(database_url, echo=False, connect_args=connect_args)


def init_db(engine) -> None:
    """Create all tables. In production, run Alembic migrations instead."""
    SQLModel.metadata.create_all(engine)
