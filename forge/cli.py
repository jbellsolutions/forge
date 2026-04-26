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

    result = asyncio.run(recurse_once(home, provider, score_fn))
    print(f"[recurse] diffs={len(result.diffs)} kept={result.kept} "
          f"base={result.base_score:.2f} cand={result.candidate_score:.2f}")
    return 0


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

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
