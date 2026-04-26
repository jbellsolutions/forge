"""forge — top-level CLI.

Subcommands:
  forge doctor                       Health check: keys, providers, MCP, tests
  forge run <vertical>               Run an example vertical (operator, operator_real, ...)
  forge recurse [--home DIR]         One self-mod cycle (mock if no key)
  forge recurse-loop [--home DIR]    N self-mod cycles in series (for nightly cron)
  forge dashboard [--home DIR]       Print telemetry + trace summary
  forge skill list|search|eval       Skill registry ops
  forge vault note|search|backlinks  Obsidian vault ops
  forge heartbeat run                Run every .claude/heartbeats/*.md

Entry point in pyproject: forge = "forge.cli:main"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

__version__ = "0.0.1"


def _load_dotenv() -> None:
    """Load ~/.forge/.env into os.environ if present. Outside repo by design.

    Format: simple KEY=VALUE per line, # comments, no quoting tricks.
    """
    path = Path.home() / ".forge" / ".env"
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            # Don't clobber existing env (lets shell exports override)
            os.environ.setdefault(k, v)
    except OSError:
        pass


_load_dotenv()


def _cmd_doctor(args: argparse.Namespace) -> int:
    from .health import doctor
    report = doctor(home=Path(args.home).expanduser() if args.home else None)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


def _cmd_run(args: argparse.Namespace) -> int:
    """Run an example vertical by name. Looks for examples/<vertical>/run.py."""
    repo_root = _repo_root()
    target = repo_root / "examples" / args.vertical / "run.py"
    if not target.exists():
        print(f"vertical {args.vertical!r} not found at {target}", file=sys.stderr)
        return 2
    # exec it as a subprocess so its sys.path tweaks work cleanly
    import subprocess
    return subprocess.call([sys.executable, str(target), *args.extra])


def _cmd_recurse(args: argparse.Namespace) -> int:
    from .recursion import recurse_once
    from .providers import make_provider, load_profile
    from .providers.mock import MockProvider
    from .kernel.types import AssistantTurn

    home = Path(args.home).expanduser()
    home.mkdir(parents=True, exist_ok=True)

    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        provider = make_provider(args.profile)
        print(f"[recurse] using profile={args.profile}")
    else:
        canned = AssistantTurn(text="[]", tool_calls=[],
                               usage={"input_tokens": 1, "output_tokens": 1})
        provider = MockProvider.scripted(load_profile("mock"), [canned])
        print("[recurse] no API key; mock provider returns no diffs (safe no-op)")

    def score_fn(p: Path) -> float:
        # Default: count cells in circuits.json as a proxy for "has the harness learned?"
        c = p / ".forge" / "healing" / "circuits.json"
        if not c.exists():
            return 0.0
        try:
            return float(len(json.loads(c.read_text())))
        except json.JSONDecodeError:
            return 0.0

    intel_ctx: str | None = None
    if getattr(args, "with_intel", False):
        intel_ctx = _load_intel_context(home)
        if intel_ctx:
            print(f"[recurse] injecting intel context: {len(intel_ctx)} chars")
        else:
            print("[recurse] --with-intel set but no intel found; running without")

    result = asyncio.run(recurse_once(home, provider, score_fn, intel_context=intel_ctx))
    print(f"[recurse] diffs={len(result.diffs)} kept={result.kept} "
          f"base={result.base_score:.2f} cand={result.candidate_score:.2f}")
    return 0


def _load_intel_context(home: Path) -> str | None:
    """Load today's intel digest + most recent auto-research summary
    as a single text block to inject into the recursion proposer.
    Returns None if neither artifact exists.
    """
    import datetime as _dt
    parts: list[str] = []
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    intel_today = home / "intel" / f"{today}.json"
    if intel_today.exists():
        try:
            items = json.loads(intel_today.read_text(encoding="utf-8"))
            if isinstance(items, list) and items:
                lines = ["### Industry signals (today)"]
                for it in items[:12]:
                    if isinstance(it, dict):
                        rel = it.get("relevance", "?")
                        lines.append(
                            f"- [{rel}] {it.get('source','?')}: "
                            f"{it.get('title','?')} ({it.get('url','')})"
                        )
                parts.append("\n".join(lines))
        except (json.JSONDecodeError, OSError):
            pass
    ar_tsv = home / "intel" / "auto-research.tsv"
    if ar_tsv.exists():
        try:
            import csv as _csv
            with ar_tsv.open("r", encoding="utf-8") as f:
                rows = list(_csv.DictReader(f, delimiter="\t"))
            if rows:
                last = max(rows, key=lambda r: float(r.get("ts", 0) or 0))
                ref = last.get("summary_ref") or ""
                if ref:
                    refp = home / ref
                    if refp.exists():
                        parts.append(
                            "### Auto-research summary (latest)\n"
                            + refp.read_text(encoding="utf-8")[:4000]
                        )
        except (ValueError, OSError):
            pass
    return "\n\n".join(parts) if parts else None


def _cmd_recurse_loop(args: argparse.Namespace) -> int:
    """Run N recursion iterations in series. Designed for `cron`/`launchd`."""
    from .recursion import recurse_once
    from .providers import make_provider, load_profile
    from .providers.mock import MockProvider
    from .kernel.types import AssistantTurn

    home = Path(args.home).expanduser()
    home.mkdir(parents=True, exist_ok=True)

    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        provider_factory = lambda: make_provider(args.profile)
    else:
        provider_factory = lambda: MockProvider.scripted(
            load_profile("mock"),
            [AssistantTurn(text="[]", tool_calls=[], usage={"input_tokens": 1, "output_tokens": 1})],
        )

    def score_fn(p: Path) -> float:
        c = p / ".forge" / "healing" / "circuits.json"
        if not c.exists():
            return 0.0
        try:
            return float(len(json.loads(c.read_text())))
        except json.JSONDecodeError:
            return 0.0

    kept = 0
    for i in range(args.n):
        result = asyncio.run(recurse_once(home, provider_factory(), score_fn))
        kept += int(result.kept)
        print(f"[recurse-loop] iter {i+1}/{args.n}: diffs={len(result.diffs)} kept={result.kept}")
    print(f"[recurse-loop] done. kept={kept}/{args.n}")
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    from .observability.dashboard import summarize
    print(json.dumps(summarize(args.home), indent=2))
    return 0


def _cmd_intel(args: argparse.Namespace) -> int:
    home = Path(args.home).expanduser()
    if args.action == "pull":
        from .intel import pull_intel, store_items, load_sources
        from .intel.normalize import maybe_haiku_rerank
        sources = load_sources(home)
        items = pull_intel(home, sources)
        if not args.dry_run and items:
            items = maybe_haiku_rerank(items, use_llm=False)  # cheap default
            meta = store_items(home, items)
        else:
            meta = {"dry_run": True}
        print(json.dumps({
            "fetched": len(items),
            "by_relevance": {
                r: sum(1 for i in items if i.relevance == r)
                for r in ("high", "med", "low")
            },
            "store": meta,
        }, indent=2, default=str))
        return 0
    if args.action == "show":
        from datetime import datetime, timezone
        date = args.at or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        p = home / "intel" / f"{date}.json"
        if not p.exists():
            print(f"(no intel for {date} at {p})")
            return 0
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"(corrupt JSON at {p})")
            return 1
        from .intel import build_intel_digest, IntelItem
        digest = build_intel_digest([
            IntelItem(**{k: v for k, v in it.items() if k in IntelItem.__dataclass_fields__})
            for it in items if isinstance(it, dict)
        ])
        print(digest.to_markdown())
        return 0
    return 1


def _cmd_report(args: argparse.Namespace) -> int:
    """Build a digest and deliver it via the configured channel."""
    import asyncio
    from datetime import datetime, timezone
    from .observability.delivery import deliver
    from .observability.digest import build_digest

    at = None
    if args.at:
        try:
            at = datetime.strptime(args.at, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"--at must be YYYY-MM-DD, got: {args.at}", file=sys.stderr)
            return 2

    home = Path(args.home)
    digest = build_digest(home, period=args.period, at=at)
    override = None if args.to == "auto" else args.to
    meta = asyncio.run(deliver(home, digest, override=override))
    print(json.dumps({
        "period": args.period,
        "kept": digest.kept_count,
        "rolled": digest.rolled_count,
        "denials": len(digest.denials),
        "skill_events": len(digest.skills),
        "cost_usd": digest.telemetry.total_cost_usd,
        "delivery": meta,
    }, indent=2, default=str))
    return 0


def _cmd_skill(args: argparse.Namespace) -> int:
    from .skills import SkillStore, SkillSearchIndex, evaluate
    store = SkillStore(args.root)
    if args.action == "list":
        for s in store.list_skills():
            try:
                cur = store.current_version(s)
                runs = store.runs(s)
                print(f"{s:30s} v={cur:5s} runs={len(runs)}")
            except FileNotFoundError:
                print(f"{s:30s} (no current version)")
        return 0
    if args.action == "search":
        idx = SkillSearchIndex(store)
        for hit in idx.search(args.query, k=args.k):
            print(f"{hit.score:.3f}  {hit.name:30s} {hit.version}")
        return 0
    if args.action == "eval":
        report = evaluate(store, args.skill, args.candidate)
        print(json.dumps(report.__dict__, indent=2))
        return 0
    return 2


def _cmd_vault(args: argparse.Namespace) -> int:
    from .memory import ObsidianVault
    vault = ObsidianVault(args.root)
    if args.action == "note":
        path = vault.write_note(args.title, args.body, folder=args.folder,
                                tags=args.tags or [])
        print(f"wrote {path}")
        return 0
    if args.action == "search":
        for n in vault.search(args.query, k=args.k):
            print(f"{n.path}  tags={n.tags}")
        return 0
    if args.action == "backlinks":
        for n in vault.backlinks(args.target):
            print(n.path)
        return 0
    return 2


def _cmd_heartbeat(args: argparse.Namespace) -> int:
    from .scheduler.heartbeat import run_all
    return asyncio.run(run_all(Path(args.dir).expanduser()))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="forge", description="forge agent harness CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="health check")
    d.add_argument("--home", default=None)
    d.set_defaults(func=_cmd_doctor)

    r = sub.add_parser("run", help="run an example vertical")
    r.add_argument("vertical")
    r.add_argument("extra", nargs=argparse.REMAINDER)
    r.set_defaults(func=_cmd_run)

    rc = sub.add_parser("recurse", help="one self-mod cycle")
    rc.add_argument("--home", default=str(Path.home() / ".forge" / "default"))
    rc.add_argument("--profile", default="anthropic")
    rc.add_argument("--with-intel", action="store_true",
                    help="inject today's intel digest as proposer context")
    rc.set_defaults(func=_cmd_recurse)

    rl = sub.add_parser("recurse-loop", help="N self-mod cycles (cron-friendly)")
    rl.add_argument("--home", default=str(Path.home() / ".forge" / "default"))
    rl.add_argument("--profile", default="anthropic")
    rl.add_argument("-n", type=int, default=5)
    rl.set_defaults(func=_cmd_recurse_loop)

    db = sub.add_parser("dashboard", help="telemetry + trace summary")
    db.add_argument("--home", default=".forge")
    db.set_defaults(func=_cmd_dashboard)

    sk = sub.add_parser("skill")
    sk.add_argument("action", choices=["list", "search", "eval"])
    sk.add_argument("--root", default=".forge/operator-real/.claude/skills")
    sk.add_argument("--query", default="")
    sk.add_argument("--k", type=int, default=5)
    sk.add_argument("--skill", default="")
    sk.add_argument("--candidate", default="")
    sk.set_defaults(func=_cmd_skill)

    v = sub.add_parser("vault")
    v.add_argument("action", choices=["note", "search", "backlinks"])
    v.add_argument("--root", default=str(Path.home() / ".forge" / "vault"))
    v.add_argument("--title", default="")
    v.add_argument("--body", default="")
    v.add_argument("--folder", default="inbox")
    v.add_argument("--tags", nargs="*")
    v.add_argument("--query", default="")
    v.add_argument("--target", default="")
    v.add_argument("--k", type=int, default=5)
    v.set_defaults(func=_cmd_vault)

    hb = sub.add_parser("heartbeat", help="run heartbeat markdown files")
    hb.add_argument("action", choices=["run"])
    hb.add_argument("--dir", default=str(Path.home() / ".forge" / "default" / ".claude" / "heartbeats"))
    hb.set_defaults(func=_cmd_heartbeat)

    mcp = sub.add_parser("mcp", help="run forge as a stdio MCP server")
    mcp.set_defaults(func=lambda a: __import__("forge.mcp_server", fromlist=["main"]).main())

    intel = sub.add_parser("intel", help="industry-signal pull / show")
    intel.add_argument("action", choices=["pull", "show"])
    intel.add_argument("--home", default=str(Path.home() / ".forge" / "default"))
    intel.add_argument("--dry-run", action="store_true",
                       help="for `pull`: fetch + parse but do not write")
    intel.add_argument("--at", default=None,
                       help="for `show`: YYYY-MM-DD; defaults to today")
    intel.set_defaults(func=_cmd_intel)

    rep = sub.add_parser("report", help="build + deliver a self-improvement digest")
    rep.add_argument("--period", choices=["day", "week"], default="day")
    rep.add_argument("--home", default=str(Path.home() / ".forge" / "default"))
    rep.add_argument("--to", choices=["file", "slack-mcp", "auto"], default="auto",
                     help="delivery channel; 'auto' reads <home>/delivery.yaml")
    rep.add_argument("--at", default=None,
                     help="window end as ISO date (YYYY-MM-DD); defaults to now")
    rep.set_defaults(func=_cmd_report)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
