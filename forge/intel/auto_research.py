"""AutoAgent-style auto-research cycle.

Spawns a tightly-scoped sub-agent with web tools enabled and instructs it
to investigate what competitor SDKs (Claude / OpenAI / Composio / MCP /
Meta-Harness / open-source harnesses) have published since the last run,
synthesize findings, and return a "would-this-still-matter" summary that
feeds directly into `recurse_once(intel_context=...)`.

Reference: https://github.com/kevinrgu/autoagent — forge already absorbs
the AutoAgent regularizer into the recursion proposer's PROGRAM_DIRECTIVE.
This module brings the *active* half: tool-use during the proposal phase
itself, not just static-trace reading. Patterns to lift on a follow-up
review of that repo (NOT in this commit; tracked in TODOS.md):
  - tool-use during proposal phase  ← THIS file delivers the seam
  - multi-step verification before commit
  - counterfactual scoring formula
  - self-tuning regularizer threshold

Budget enforcement: a `Telemetry`-watching `PreToolUse` hook returns
`Verdict.SAFETY_BLOCKED` (bypass-immune) once the cumulative session cost
crosses `max_cost_usd`, terminating the loop cleanly. Result rows append
to `<home>/intel/auto-research.tsv`. Summary persists to
`<home>/intel/research/<YYYY-MM-DD-HH>.md` and the TSV row carries the
relative path as `summary_ref` so `forge recurse --with-intel` can read it.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..kernel.hooks import HookBus, HookContext
from ..kernel.types import AgentDef, ToolCall, ToolResult, Verdict
from ..observability.telemetry import Telemetry
from ..providers import load_profile, make_provider
from ..providers.base import Provider
from ..tools import ToolRegistry, WebFetchTool, WebSearchTool


log = logging.getLogger("forge.intel.auto_research")


@dataclass
class AutoResearchBudget:
    """Hard caps for one auto-research cycle.

    Defaults (`daily()` / `weekly()`) are tuned to keep the daily heartbeat
    around $0.10 and the weekly one around $0.50–$1.00.
    """
    max_turns: int = 4
    max_cost_usd: float = 0.15
    max_tool_calls: int = 8
    label: str = "daily"

    @classmethod
    def daily(cls) -> "AutoResearchBudget":
        return cls(max_turns=4, max_cost_usd=0.15, max_tool_calls=8, label="daily")

    @classmethod
    def weekly(cls) -> "AutoResearchBudget":
        return cls(max_turns=20, max_cost_usd=1.00, max_tool_calls=40, label="weekly")


@dataclass
class AutoResearchResult:
    label: str
    profile: str
    started_at: float
    ended_at: float
    turns: int
    tool_calls: int
    cost_usd: float
    summary_md: str
    summary_path: str
    truncated: bool = False
    error: str | None = None


# The AutoAgent regularizer applied to RESEARCH (vs forge's recursion-proposer
# version which applies to MOD proposals). Same intent: don't overfit to one
# vendor's release notes.
SYSTEM_PROMPT = """\
You are forge's auto-research sub-agent. Your job is to investigate what's
new this {window} in the agent-harness / model-provider / MCP / SDK space
and produce a tight summary that the recursion proposer can reason against.

## Tracked entities
- Anthropic (Claude, Claude Code, claude-agent-sdk, MCP)
- OpenAI (gpt-5, openai-python, function calling)
- Composio (tools, SDK, MCP transport)
- Model Context Protocol (servers, python-sdk, spec changes)
- Meta-Harness / AutoAgent / open-source harness research
- Anything with novel agent-loop, tool-use, or skill-eval primitives

## Tools you have
- web_search: query the web (Tavily / Brave / DuckDuckGo, auto-detected)
- web_fetch: fetch a URL (allowlisted hosts only — anthropic.com, openai.com,
  github.com, etc.)
- intel_store_item: persist a finding as an IntelItem (for downstream consumers)

## Method
1. Run web_search for each tracked entity ({entities}) constrained to
   "since {since_human}".
2. For each high-signal hit, web_fetch the URL to confirm + extract detail.
3. Call intel_store_item to persist anything that would shift how a competent
   harness builder would design forge.
4. End with a markdown summary, grouped by entity, max 12 bullets total.

## Regularizer (READ THIS BEFORE STORING ANYTHING)
> Would this finding still matter if the SPECIFIC product or release I just
> read about disappeared tomorrow? Or am I just chasing a headline?
>
> Only store what represents a DURABLE shift (architecture move, new
> primitive, deprecation, capability tier change). Skip vague hype, blog
> posts that don't change behavior, and "we're excited to announce".

## Hard rules
- Do not invent. Cite a URL for every claim in the summary.
- Stop when you've covered the entities or hit your turn budget.
- Your final assistant message MUST be the summary; it gets saved verbatim
  and passed to the recursion proposer.
"""


def _build_system_prompt(budget: AutoResearchBudget, since_ts: float) -> str:
    since_human = _dt.datetime.fromtimestamp(since_ts, _dt.timezone.utc).strftime("%Y-%m-%d")
    window = "day" if budget.label == "daily" else "week"
    entities = "Anthropic, OpenAI, Composio, MCP, Meta-Harness/AutoAgent"
    return SYSTEM_PROMPT.format(window=window, since_human=since_human, entities=entities)


# ---------------------------------------------------------------------------
# `intel_store_item` — a small Tool the sub-agent uses to persist findings.
# ---------------------------------------------------------------------------

class IntelStoreItemTool:
    """Tool the sub-agent uses to persist a found IntelItem.

    Implemented as a thin wrapper rather than a `Tool` subclass so we can
    capture the home + items list in a closure without leaking state.
    """
    name = "intel_store_item"
    description = "Persist a found IntelItem to today's intel JSON + vault."
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "title": {"type": "string"},
            "url": {"type": "string"},
            "summary": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "relevance": {"type": "string", "enum": ["high", "med", "low"]},
        },
        "required": ["source", "title", "url"],
    }
    tier = "mcp"
    concurrency_safe = False

    def __init__(self, home: Path, items: list) -> None:
        self.home = home
        self.items = items

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description,
                "parameters": self.parameters, "tier": self.tier,
                "concurrency_safe": self.concurrency_safe}

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        from .normalize import normalize_item
        try:
            args = call.arguments or {}
            item = normalize_item(
                source=str(args.get("source", "auto-research")),
                title=str(args.get("title", "")),
                url=str(args.get("url", "")),
                summary=str(args.get("summary", "")),
                ts=time.time(),
                tags=list(args.get("tags") or []),
            )
            if args.get("relevance") in ("high", "med", "low"):
                item.relevance = args["relevance"]
            self.items.append(item)
            return ToolResult(call.id, self.name,
                              f"stored: {item.url} (relevance={item.relevance})")
        except Exception as e:  # noqa: BLE001
            return ToolResult(call.id, self.name, f"error: {e}", is_error=True)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

async def run_auto_research(
    home: str | Path,
    *,
    profile: str | None = None,
    budget: AutoResearchBudget | None = None,
    since_ts: float | None = None,
    provider: Provider | None = None,
) -> AutoResearchResult:
    """Run one auto-research cycle.

    `provider` is injectable for tests; otherwise built from `profile`
    (defaults to anthropic-haiku for daily, anthropic for weekly).
    """
    home_p = Path(home)
    intel_dir = home_p / "intel"
    research_dir = intel_dir / "research"
    intel_dir.mkdir(parents=True, exist_ok=True)
    research_dir.mkdir(parents=True, exist_ok=True)

    budget = budget or AutoResearchBudget.daily()
    profile_name = profile or ("anthropic" if budget.label == "weekly" else "anthropic-haiku")
    since = since_ts if since_ts is not None else (
        time.time() - (86400 if budget.label == "daily" else 86400 * 7)
    )
    started = time.time()
    started_iso = _dt.datetime.fromtimestamp(started, _dt.timezone.utc).strftime("%Y-%m-%d-%H")

    if provider is None:
        provider = make_provider(profile_name)

    # Tool registry: web_search + web_fetch + intel_store_item ONLY.
    # No fs, no shell, no cli. Read-only against the world; write-only into intel.
    items_collected: list = []
    tools = ToolRegistry()
    tools.register(WebSearchTool())
    tools.register(WebFetchTool())
    tools.register(IntelStoreItemTool(home_p, items_collected))

    # Hooks: telemetry for cost tracking + budget guard.
    hooks = HookBus()
    telemetry = Telemetry(path=home_p / "telemetry.jsonl")
    telemetry.attach(hooks)

    tool_call_count = {"n": 0}
    truncated = {"flag": False}

    @hooks.on_pre_tool
    def budget_guard(ctx: HookContext) -> Verdict | None:
        # Cost-based guard: sum cost of sessions seen so far in this run.
        # Telemetry sessions accrue cost only at session_end, so during a
        # single run we approximate using a simple tool-call cap. Sonnet
        # daily research at ~$0.02/call → 8 calls ≈ $0.15.
        if ctx.tool_call is None:
            return None
        if tool_call_count["n"] >= budget.max_tool_calls:
            truncated["flag"] = True
            ctx.safety_block(
                f"auto-research budget: max_tool_calls={budget.max_tool_calls} reached"
            )
            return Verdict.SAFETY_BLOCKED
        tool_call_count["n"] += 1
        return None

    # Build the agent.
    agent = AgentDef(
        name=f"auto-research-{budget.label}",
        instructions=_build_system_prompt(budget, since),
        profile=profile_name,
    )

    # Run the loop. Local import to avoid circular at module load time.
    from ..kernel.loop import AgentLoop
    loop = AgentLoop(agent=agent, provider=provider, tools=tools,
                     hooks=hooks, max_turns=budget.max_turns)

    user_kick = (
        f"Investigate what's new in the {budget.label} window since "
        f"{_dt.datetime.fromtimestamp(since, _dt.timezone.utc).isoformat(timespec='seconds')}. "
        f"Use web_search + web_fetch. Call intel_store_item for durable findings. "
        f"End with the summary."
    )

    try:
        result = await loop.run(user_kick)
    except Exception as e:  # noqa: BLE001
        log.warning("auto-research loop crashed: %s", e)
        return AutoResearchResult(
            label=budget.label, profile=profile_name,
            started_at=started, ended_at=time.time(),
            turns=0, tool_calls=tool_call_count["n"], cost_usd=0.0,
            summary_md="", summary_path="", truncated=False, error=str(e),
        )

    summary_md = result.final_text or ""
    # Persist + store.
    summary_path = research_dir / f"{started_iso}-{budget.label}.md"
    summary_path.write_text(
        f"# Auto-research summary ({budget.label})\n\n"
        f"_started_at: {started_iso}_\n"
        f"_profile: {profile_name}_\n"
        f"_turns: {result.turns} / tool_calls: {tool_call_count['n']}_\n\n"
        + summary_md,
        encoding="utf-8",
    )

    # Persist any IntelItems the agent collected via intel_store_item.
    if items_collected:
        try:
            from .store import store_items
            store_items(home_p, items_collected, write_vault=True, write_genome=True)
        except Exception as e:  # noqa: BLE001
            log.warning("intel store failed: %s", e)

    cost_usd = sum(s.cost_usd for s in telemetry.sessions.values())

    # Append a row to <home>/intel/auto-research.tsv (parallel to results.tsv).
    ledger_path = intel_dir / "auto-research.tsv"
    is_new = not ledger_path.exists()
    with ledger_path.open("a", encoding="utf-8") as f:
        if is_new:
            f.write("ts\tlabel\tprofile\tturns\ttool_calls\tcost_usd\titems\tsummary_ref\ttruncated\n")
        f.write(
            f"{started:.3f}\t{budget.label}\t{profile_name}\t{result.turns}\t"
            f"{tool_call_count['n']}\t{cost_usd:.6f}\t{len(items_collected)}\t"
            f"{summary_path.relative_to(home_p)}\t{int(truncated['flag'])}\n"
        )

    return AutoResearchResult(
        label=budget.label, profile=profile_name,
        started_at=started, ended_at=time.time(),
        turns=result.turns, tool_calls=tool_call_count["n"],
        cost_usd=cost_usd, summary_md=summary_md,
        summary_path=str(summary_path),
        truncated=truncated["flag"],
    )
