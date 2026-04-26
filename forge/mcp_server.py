"""forge as an MCP server.

Claude Code (or any MCP client) can call forge primitives natively:
- forge_council        : spawn a 3-member role-injected council on a task
- forge_recurse        : run one self-mod cycle on a home dir
- forge_vault_write    : write a markdown note to the Obsidian vault
- forge_vault_search   : search the vault by query/tag
- forge_vault_read     : read a note by path or title
- forge_vault_backlinks: list notes linking to a target
- forge_memory_remember: distill + consolidate into ReasoningBank (cross-project genome)
- forge_memory_recall  : retrieve top-k memories from the genome
- forge_skill_list     : list registered skills
- forge_skill_search   : vector search over skills
- forge_doctor         : health check
- forge_dashboard      : telemetry summary

Run via:
    forge mcp     # stdio MCP server

Register in Claude Code:
    claude mcp add forge -- /path/to/.venv/bin/forge mcp
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from . import _dotenv  # noqa: F401  -- ensure ~/.forge/.env loaded

log = logging.getLogger("forge.mcp_server")


# ---- lazy primitive helpers -------------------------------------------------

def _genome_path() -> Path:
    return Path.home() / ".forge" / "genome.json"


def _project_home() -> Path:
    """Per-project working memory under <cwd>/.claude/forge/."""
    home = Path.cwd() / ".claude" / "forge"
    home.mkdir(parents=True, exist_ok=True)
    return home


def _vault_path() -> Path:
    p = Path.home() / ".forge" / "vault"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _vault():
    from .memory import ObsidianVault
    return ObsidianVault(_vault_path())


def _genome_bank():
    """Cross-project ReasoningBank at ~/.forge/genome.json."""
    from .memory import ReasoningBank
    from .memory.embeddings import hash_embedder
    return ReasoningBank(path=_genome_path(), embedder=hash_embedder())


def _project_skills():
    from .skills import SkillStore
    root = Path.cwd() / ".claude" / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return SkillStore(root)


# ---- tool implementations ---------------------------------------------------

async def _tool_council(arguments: dict[str, Any]) -> str:
    """Run a 3-member parallel council; return verdict + members."""
    from .healing import attach_healing
    from .kernel import HookBus
    from .observability import Telemetry, TraceStore
    from .swarm import Consensus, RoleAssignment, RoleCouncilSpawner, SwarmSpec, Topology
    from .tools import ToolRegistry
    from .tools.builtin.echo import EchoTool

    task = arguments["task"]
    profiles = arguments.get(
        "profiles",
        ["anthropic", "anthropic-haiku", "anthropic-contrarian"],
    )
    if len(profiles) != 3:
        return json.dumps({"error": "council requires exactly 3 profiles"})

    home = _project_home() / "council"
    home.mkdir(parents=True, exist_ok=True)
    tools = ToolRegistry(); tools.register(EchoTool())
    hooks = HookBus()
    TraceStore(root=home / "traces").attach(hooks)
    tel = Telemetry(path=home / "telemetry.jsonl"); tel.attach(hooks)
    attach_healing(hooks)

    spec = SwarmSpec(
        topology=Topology.PARALLEL_COUNCIL,
        consensus=Consensus.MAJORITY,
        members=profiles,
    )
    spawner = RoleCouncilSpawner(
        tools=tools, hooks=hooks,
        base_instructions=arguments.get(
            "base_instructions",
            "You are a council member. Reach a brief, decisive answer.",
        ),
        max_turns=int(arguments.get("max_turns", 4)),
    )
    spawner.set_assignments([
        RoleAssignment(profile=profiles[0], role="optimist"),
        RoleAssignment(profile=profiles[1], role="skeptic"),
        RoleAssignment(profile=profiles[2], role="pragmatist"),
    ])

    result = await spawner.run(task, spec)
    return json.dumps({
        "verdict": result.verdict.winner if result.verdict else "",
        "members": [
            {"agent": name, "output": lr.final_text, "turns": lr.turns}
            for name, lr in result.members
        ],
        "telemetry": tel.summary(),
    }, indent=2)


async def _tool_recurse(arguments: dict[str, Any]) -> str:
    """One self-mod cycle. Default home = <cwd>/.claude/forge/recurse."""
    from .providers import load_profile, make_provider
    from .providers.mock import MockProvider
    from .kernel.types import AssistantTurn
    from .recursion import recurse_once

    home = Path(arguments.get("home") or _project_home() / "recurse").expanduser()
    home.mkdir(parents=True, exist_ok=True)

    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        provider = make_provider(arguments.get("profile", "anthropic"))
    else:
        provider = MockProvider.scripted(load_profile("mock"), [
            AssistantTurn(text="[]", tool_calls=[], usage={"input_tokens": 1, "output_tokens": 1}),
        ])

    def score_fn(p: Path) -> float:
        c = p / ".forge" / "healing" / "circuits.json"
        if not c.exists():
            return 0.0
        try:
            return float(len(json.loads(c.read_text())))
        except json.JSONDecodeError:
            return 0.0

    result = await recurse_once(home, provider, score_fn)
    return json.dumps({
        "diffs_proposed": len(result.diffs),
        "applied": len(result.applied),
        "base_score": result.base_score,
        "candidate_score": result.candidate_score,
        "kept": result.kept,
        "notes": result.notes,
        "rationales": [d.rationale for d in result.diffs],
    }, indent=2)


def _tool_vault_write(arguments: dict[str, Any]) -> str:
    v = _vault()
    p = v.write_note(
        title=arguments["title"],
        body=arguments["body"],
        folder=arguments.get("folder", "inbox"),
        tags=arguments.get("tags") or [],
    )
    return f"wrote {p.relative_to(v.root)}"


def _tool_vault_search(arguments: dict[str, Any]) -> str:
    v = _vault()
    hits = v.search(
        arguments["query"], k=int(arguments.get("k", 5)),
        tags=arguments.get("tags") or [],
    )
    if not hits:
        return "no matches"
    return "\n".join(f"- {n.path}  tags={n.tags}" for n in hits)


def _tool_vault_read(arguments: dict[str, Any]) -> str:
    v = _vault()
    note = v.read_note(arguments["path_or_title"])
    if not note:
        return "not found"
    return f"# {note.title}\npath: {note.path}\ntags: {note.tags}\nforward_links: {note.forward_links}\n\n{note.body}"


def _tool_vault_backlinks(arguments: dict[str, Any]) -> str:
    v = _vault()
    notes = v.backlinks(arguments["target"])
    if not notes:
        return "no backlinks"
    return "\n".join(f"- {n.path}" for n in notes)


def _tool_memory_remember(arguments: dict[str, Any]) -> str:
    """Distill text into the cross-project genome ReasoningBank."""
    bank = _genome_bank()
    m = bank.distill(arguments["text"], tags=arguments.get("tags") or [])
    bank.consolidate(m)
    if arguments.get("score") is not None:
        bank.judge(m.id, float(arguments["score"]))
    stored = bank._mems[m.id]
    return json.dumps({
        "id": stored.id, "tags": stored.tags,
        "confidence": stored.confidence,
        "genome_path": str(_genome_path()),
        "genome_size": len(bank),
    }, default=str)


def _tool_memory_recall(arguments: dict[str, Any]) -> str:
    bank = _genome_bank()
    hits = bank.retrieve(
        arguments["query"], k=int(arguments.get("k", 5)),
        min_confidence=float(arguments.get("min_confidence", 0.0)),
    )
    if not hits:
        return "no matches"
    return "\n".join(
        f"({m.confidence:.2f}) [{','.join(m.tags) or '-'}] {m.text[:200]}"
        for m in hits
    )


def _tool_skill_list(arguments: dict[str, Any]) -> str:
    store = _project_skills()
    out: list[dict[str, Any]] = []
    for s in store.list_skills():
        try:
            out.append({
                "name": s,
                "current": store.current_version(s),
                "runs": len(store.runs(s)),
            })
        except FileNotFoundError:
            pass
    return json.dumps(out, indent=2)


def _tool_skill_search(arguments: dict[str, Any]) -> str:
    from .skills import SkillSearchIndex
    store = _project_skills()
    idx = SkillSearchIndex(store)
    hits = idx.search(arguments["query"], k=int(arguments.get("k", 5)))
    return json.dumps([{"name": h.name, "version": h.version, "score": h.score}
                       for h in hits], indent=2)


def _tool_doctor(arguments: dict[str, Any]) -> str:
    from .health import doctor
    return json.dumps(doctor(home=_project_home()), indent=2, default=str)


def _tool_dashboard(arguments: dict[str, Any]) -> str:
    from .observability.dashboard import summarize
    home = arguments.get("home") or str(_project_home())
    return json.dumps(summarize(home), indent=2)


# ---- registry ---------------------------------------------------------------

TOOLS = [
    ("forge_council",
     "Spawn a 3-member parallel council on a task. Members are role-injected "
     "(optimist/skeptic/pragmatist) on three Anthropic profiles by default.",
     {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Question for the council to decide."},
            "profiles": {"type": "array", "items": {"type": "string"},
                         "description": "Three forge profile names. Defaults to anthropic+haiku+contrarian."},
            "base_instructions": {"type": "string"},
            "max_turns": {"type": "integer", "default": 4},
        },
        "required": ["task"],
     },
     _tool_council, True),
    ("forge_recurse",
     "Run one self-modification cycle: read traces, propose harness diffs via LLM, "
     "fork, apply, score, keep-or-rollback, write ledger row.",
     {
        "type": "object",
        "properties": {
            "home": {"type": "string", "description": "Forge home dir (default <cwd>/.claude/forge/recurse)."},
            "profile": {"type": "string", "default": "anthropic"},
        },
     },
     _tool_recurse, True),
    ("forge_vault_write",
     "Write a markdown note to the Obsidian vault at ~/.forge/vault.",
     {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "folder": {"type": "string", "enum":
                       ["inbox", "daily", "decisions", "skills", "topics", "agents"],
                       "default": "inbox"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "body"],
     },
     _tool_vault_write, False),
    ("forge_vault_search",
     "Search the vault by query (filename/title/body) and optional tags.",
     {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "k": {"type": "integer", "default": 5},
        },
        "required": ["query"],
     },
     _tool_vault_search, False),
    ("forge_vault_read",
     "Read a vault note by path or title. Returns frontmatter + body.",
     {
        "type": "object",
        "properties": {"path_or_title": {"type": "string"}},
        "required": ["path_or_title"],
     },
     _tool_vault_read, False),
    ("forge_vault_backlinks",
     "List vault notes that wiki-link to a target title or path.",
     {
        "type": "object",
        "properties": {"target": {"type": "string"}},
        "required": ["target"],
     },
     _tool_vault_backlinks, False),
    ("forge_memory_remember",
     "Save a memory into the CROSS-PROJECT genome at ~/.forge/genome.json.",
     {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "score": {"type": "number", "description": "Outcome score in [-1,1] for JUDGE step."},
        },
        "required": ["text"],
     },
     _tool_memory_remember, False),
    ("forge_memory_recall",
     "Retrieve top-k memories from the cross-project genome.",
     {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "k": {"type": "integer", "default": 5},
            "min_confidence": {"type": "number", "default": 0.0},
        },
        "required": ["query"],
     },
     _tool_memory_recall, False),
    ("forge_skill_list",
     "List skills registered for THIS project (.claude/skills/).",
     {"type": "object", "properties": {}},
     _tool_skill_list, False),
    ("forge_skill_search",
     "Vector search over project skills' bodies + outcome history.",
     {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "k": {"type": "integer", "default": 5},
        },
        "required": ["query"],
     },
     _tool_skill_search, False),
    ("forge_doctor",
     "Health check: env keys, optional packages, profiles, registry smoke.",
     {"type": "object", "properties": {}},
     _tool_doctor, False),
    ("forge_dashboard",
     "Telemetry + trace summary for a forge home dir.",
     {
        "type": "object",
        "properties": {"home": {"type": "string"}},
     },
     _tool_dashboard, False),
]


# ---- MCP server entry point -------------------------------------------------

async def serve() -> None:
    """Run the forge MCP server over stdio. Call from `forge mcp`."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool as McpTool
    except ImportError as e:
        raise SystemExit("install MCP SDK: pip install mcp") from e

    server = Server("forge")

    @server.list_tools()
    async def _list_tools() -> list[McpTool]:
        return [
            McpTool(name=name, description=desc, inputSchema=schema)
            for (name, desc, schema, _impl, _is_async) in TOOLS
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        for n, _desc, _schema, impl, is_async in TOOLS:
            if n != name:
                continue
            try:
                result = await impl(arguments) if is_async else impl(arguments)
            except Exception as e:  # noqa: BLE001
                log.exception("forge tool %r failed", name)
                result = json.dumps({"error": f"{type(e).__name__}: {e}"})
            return [TextContent(type="text", text=str(result))]
        return [TextContent(type="text", text=f"unknown tool: {name}")]

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> int:
    asyncio.run(serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
