"""Obsidian vault tools — Tier 1 (knowledge graph)."""
from __future__ import annotations

from ...kernel.types import AgentDef, ToolCall, ToolResult
from ...memory.obsidian import ObsidianVault
from ..base import Tool


class ObsidianWriteTool(Tool):
    name = "obsidian_write"
    description = (
        "Write a markdown note to the Obsidian vault. Use [[wiki-links]] in the body "
        "to connect concepts. Pick folder=inbox|daily|decisions|topics|agents."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "folder": {"type": "string", "default": "inbox",
                       "enum": ["inbox", "daily", "decisions", "skills", "topics", "agents"]},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "body"],
    }
    tier = "mcp"

    def __init__(self, vault: ObsidianVault) -> None:
        self.vault = vault

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        try:
            path = self.vault.write_note(
                title=call.arguments["title"],
                body=call.arguments["body"],
                folder=call.arguments.get("folder", "inbox"),
                tags=call.arguments.get("tags") or [],
            )
            return ToolResult(call.id, self.name,
                              f"wrote {path.relative_to(self.vault.root)}")
        except Exception as e:  # noqa: BLE001
            return ToolResult(call.id, self.name, f"error: {e}", is_error=True)


class ObsidianSearchTool(Tool):
    name = "obsidian_search"
    description = "Search the Obsidian vault by query (filename/title/body) and optional tags."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "k": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    }
    tier = "mcp"

    def __init__(self, vault: ObsidianVault) -> None:
        self.vault = vault

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        hits = self.vault.search(
            call.arguments["query"],
            k=int(call.arguments.get("k", 5)),
            tags=call.arguments.get("tags") or [],
        )
        if not hits:
            return ToolResult(call.id, self.name, "no matches")
        lines = [f"- {n.path}  (tags: {', '.join(n.tags) or '-'})" for n in hits]
        return ToolResult(call.id, self.name, "\n".join(lines))


class ObsidianReadTool(Tool):
    name = "obsidian_read"
    description = "Read a note by path or title. Returns frontmatter + body."
    parameters = {
        "type": "object",
        "properties": {"path_or_title": {"type": "string"}},
        "required": ["path_or_title"],
    }
    tier = "mcp"

    def __init__(self, vault: ObsidianVault) -> None:
        self.vault = vault

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        note = self.vault.read_note(call.arguments["path_or_title"])
        if not note:
            return ToolResult(call.id, self.name, "not found", is_error=True)
        meta = (
            f"# {note.title}\n"
            f"path: {note.path}\n"
            f"tags: {note.tags}\n"
            f"forward_links: {note.forward_links}\n\n"
        )
        return ToolResult(call.id, self.name, meta + note.body)


class ObsidianBacklinksTool(Tool):
    name = "obsidian_backlinks"
    description = "List notes that link to a target title."
    parameters = {
        "type": "object",
        "properties": {"target": {"type": "string"}},
        "required": ["target"],
    }
    tier = "mcp"

    def __init__(self, vault: ObsidianVault) -> None:
        self.vault = vault

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        notes = self.vault.backlinks(call.arguments["target"])
        if not notes:
            return ToolResult(call.id, self.name, "no backlinks")
        return ToolResult(call.id, self.name, "\n".join(f"- {n.path}" for n in notes))
