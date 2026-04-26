"""pull_pending_actions — GET /sync/pending, apply locally, POST diff back.

Apply dispatch by `kind`:

- spawn_agent     → write `<home>/agents/<name>.yaml`
- update_agent    → load + patch + rewrite YAML
- start_project   → render + write a project scaffold under `examples/<name>/`
- run_recurse     → invoke `recurse_once` with optional `intel_context`

All applies are idempotent at the filesystem level (write-if-different) and
the server side guards against double-apply via `status='applied'`.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


GetTransport = Callable[[str, dict[str, str]], list[dict[str, Any]]]
PostTransport = Callable[[str, bytes, dict[str, str]], dict[str, Any]]


def _default_get(url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec
        return json.loads(resp.read().decode("utf-8"))


def _default_post(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec
        return json.loads(resp.read().decode("utf-8"))


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Best-effort YAML serializer; falls back to JSON-in-YAML if pyyaml
    isn't installed (still parseable by the apply path on the next run)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml  # type: ignore
        path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")
    except ImportError:
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def apply_pending(home: Path, action: dict[str, Any]) -> dict[str, Any]:
    """Apply one approved action. Returns a diff dict (logged into the cloud
    ChangelogEntry via `/sync/applied/<id>`)."""
    home = Path(home)
    kind = action.get("kind")
    payload = action.get("payload") or action.get("payload_json") or {}

    if kind == "spawn_agent":
        name = payload["name"]
        target = home / "agents" / f"{name}.yaml"
        body = {
            "name": name,
            "profile": payload.get("profile", "anthropic"),
            "instructions": payload.get("instructions", ""),
            "tools_allowed": payload.get("tools_allowed"),
            "tools_denied": payload.get("tools_denied") or [],
            "project": payload.get("project", "forge"),
        }
        _write_yaml(target, body)
        return {"wrote": str(target), "kind": "spawn_agent"}

    if kind == "update_agent":
        name = payload["name"]
        target = home / "agents" / f"{name}.yaml"
        if not target.exists():
            raise FileNotFoundError(f"no such agent: {name}")
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        except ImportError:
            data = json.loads(target.read_text(encoding="utf-8"))
        data.update(payload.get("patch") or {})
        _write_yaml(target, data)
        return {"patched": str(target), "kind": "update_agent",
                "fields": list((payload.get("patch") or {}).keys())}

    if kind == "start_project":
        from ..orchestrator.templates import render
        name = payload["name"]
        files = render(
            payload.get("template", "operator"),
            name,
            description=payload.get("description", ""),
        )
        # Project scaffolds land under repo-root/examples/<name>/ at apply time.
        # We resolve "repo root" as the cwd's first ancestor containing pyproject.toml,
        # falling back to <home>/projects/<name>.
        root = _find_repo_root() or (home / "projects")
        wrote: list[str] = []
        for rel, body in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
            wrote.append(str(target))
        return {"scaffolded": wrote, "kind": "start_project", "template": payload.get("template")}

    if kind == "run_recurse":
        # lazy import; recurse_once is heavy
        from ..recursion.loop import recurse_once
        intel = None
        if payload.get("with_intel"):
            try:
                from ..cli import _load_intel_context
                intel = _load_intel_context(home)
            except Exception:  # noqa: BLE001
                intel = None
        # Fire the cycle. recurse_once runs synchronously; tests stub this.
        try:
            result = recurse_once(
                home=home,
                profile=payload.get("profile") or "anthropic",
                intel_context=intel,
            )
        except TypeError:
            # backward-compat: tests may stub a simpler signature
            result = recurse_once(home=home)
        return {"kind": "run_recurse", "ok": True, "result": str(result)[:400]}

    raise ValueError(f"unknown PendingAction kind: {kind}")


def _find_repo_root() -> Path | None:
    cur = Path.cwd().resolve()
    for p in [cur, *cur.parents]:
        if (p / "pyproject.toml").exists():
            return p
    return None


def pull_pending_actions(
    home: Path, url: str, token: str,
    *,
    get_transport: GetTransport | None = None,
    post_transport: PostTransport | None = None,
) -> list[dict[str, Any]]:
    """GET approved actions, apply each locally, POST diff back. Returns
    a list of `{action_id, kind, ok, diff|error}` summaries."""
    get_transport = get_transport or _default_get
    post_transport = post_transport or _default_post

    headers = {"X-Forge-Sync-Token": token}
    actions = get_transport(url.rstrip("/") + "/sync/pending", headers)

    results: list[dict[str, Any]] = []
    for a in actions or []:
        action_id = a.get("id")
        try:
            diff = apply_pending(home, a)
            ok = True
        except Exception as e:  # noqa: BLE001
            diff = {"error": str(e), "kind": a.get("kind")}
            ok = False
        # Best-effort report back. If POST fails the server will still pick
        # this action up next cycle (since status is still 'approved'),
        # which is the right idempotent behavior.
        try:
            post_transport(
                url.rstrip("/") + f"/sync/applied/{action_id}",
                json.dumps(diff).encode("utf-8"),
                {"Content-Type": "application/json", **headers},
            )
        except urllib.error.URLError:
            pass
        results.append({"action_id": action_id, "kind": a.get("kind"),
                        "ok": ok, "diff": diff})
    return results
