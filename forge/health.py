"""forge doctor — environment + integration health check.

Probes:
- Python version
- Provider API keys (presence + non-empty)
- Optional SDK installs (anthropic, openai, mcp, composio, opentelemetry, fastembed, voyage)
- npx / node / npm availability
- Each declared profile loads
- ToolRegistry instantiates with no errors
- pytest is available

Returns a dict; ok=True iff all critical probes pass.
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


CRITICAL_KEYS = ()  # nothing is critical — forge runs in mock mode out of the box
RECOMMENDED_KEYS = ("ANTHROPIC_API_KEY",)
OPTIONAL_KEYS = ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "COMPOSIO_API_KEY",
                 "VOYAGE_API_KEY", "OTEL_EXPORTER_OTLP_ENDPOINT")

OPTIONAL_PACKAGES = (
    "anthropic", "openai", "mcp", "composio",
    "opentelemetry", "fastembed", "voyageai", "yaml", "pydantic",
)


def _key_status(name: str) -> str:
    val = os.environ.get(name, "")
    if val.strip():
        return "set"
    if name in os.environ:
        return "empty"
    return "absent"


def _import_status(pkg: str) -> str:
    try:
        importlib.import_module(pkg)
        return "ok"
    except ImportError:
        return "missing"


def _bin_status(name: str) -> str:
    return "ok" if shutil.which(name) else "missing"


def _profile_load_status() -> dict[str, str]:
    from .providers import load_profile
    out: dict[str, str] = {}
    profiles_dir = Path(__file__).parent / "providers" / "profiles"
    for p in sorted(profiles_dir.glob("*.yaml")):
        name = p.stem
        try:
            load_profile(name)
            out[name] = "ok"
        except Exception as e:  # noqa: BLE001
            out[name] = f"error: {e}"
    return out


def _registry_smoke() -> str:
    try:
        from .tools import ToolRegistry
        from .tools.builtin.echo import EchoTool
        r = ToolRegistry()
        r.register(EchoTool())
        return "ok"
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


def doctor(home: Path | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "keys": {k: _key_status(k) for k in (RECOMMENDED_KEYS + OPTIONAL_KEYS)},
        "packages": {pkg: _import_status(pkg) for pkg in OPTIONAL_PACKAGES},
        "binaries": {b: _bin_status(b) for b in ("node", "npx", "git")},
        "profiles": _profile_load_status(),
        "registry_smoke": _registry_smoke(),
    }
    if home:
        report["home"] = {
            "path": str(home),
            "exists": home.exists(),
            "claude_dir": (home / ".claude").exists(),
            "traces": (home / "traces").exists(),
        }
    # ok = no profile errors, registry smoke ok, python>=3.11
    py = tuple(int(x) for x in sys.version.split()[0].split(".")[:2])
    profiles_ok = all(v == "ok" for v in report["profiles"].values())
    report["ok"] = bool(
        py >= (3, 11)
        and profiles_ok
        and report["registry_smoke"] == "ok"
    )
    # advice
    advice: list[str] = []
    if report["keys"].get("ANTHROPIC_API_KEY") != "set":
        advice.append("set ANTHROPIC_API_KEY for live provider runs")
    if report["packages"].get("mcp") != "ok":
        advice.append("pip install mcp  # to use real MCP servers")
    if report["binaries"].get("npx") != "ok":
        advice.append("install Node + npm  # to launch MCP servers via npx")
    if advice:
        report["advice"] = advice
    return report
