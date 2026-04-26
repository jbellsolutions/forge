"""CLI surface — argparse + each subcommand's smoke path."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from forge.cli import build_parser, _cmd_doctor


def test_parser_has_all_subcommands():
    p = build_parser()
    # argparse stores subparsers in choices; pull them
    sp = next(a for a in p._actions if a.dest == "cmd")
    expected = {"doctor", "run", "recurse", "recurse-loop", "dashboard",
                "skill", "vault", "heartbeat"}
    assert expected.issubset(set(sp.choices.keys()))


def test_cli_help_runs(tmp_path):
    # Use the venv interpreter path so this works in pytest cleanly
    rc = subprocess.run([sys.executable, "-m", "forge.cli", "--help"],
                        capture_output=True, text=True)
    assert rc.returncode == 0
    assert "doctor" in rc.stdout
    assert "recurse" in rc.stdout


def test_doctor_returns_report(capsys):
    import argparse
    args = argparse.Namespace(home=None)
    rc = _cmd_doctor(args)
    out = capsys.readouterr().out
    report = json.loads(out)
    assert "python" in report
    assert "keys" in report
    assert "profiles" in report
    assert "registry_smoke" in report
    assert isinstance(report["ok"], bool)
    assert rc in (0, 1)


def test_dashboard_subcommand_on_empty_home(tmp_path, capsys):
    from forge.cli import _cmd_dashboard
    import argparse
    rc = _cmd_dashboard(argparse.Namespace(home=str(tmp_path)))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["sessions"] == []
    assert rc == 0


def test_skill_list_subcommand(tmp_path, capsys):
    from forge.cli import _cmd_skill
    import argparse
    from forge.skills import SkillStore
    SkillStore(tmp_path).write_skill("alpha", "# alpha\n", version="v1")
    rc = _cmd_skill(argparse.Namespace(
        action="list", root=str(tmp_path), query="", k=5, skill="", candidate="",
    ))
    out = capsys.readouterr().out
    assert "alpha" in out
    assert rc == 0


def test_vault_note_and_search(tmp_path, capsys):
    from forge.cli import _cmd_vault
    import argparse
    rc = _cmd_vault(argparse.Namespace(
        action="note", root=str(tmp_path / "vault"),
        title="Test Note", body="content here",
        folder="inbox", tags=["t1"], query="", target="", k=5,
    ))
    assert rc == 0
    capsys.readouterr()
    rc = _cmd_vault(argparse.Namespace(
        action="search", root=str(tmp_path / "vault"),
        title="", body="", folder="", tags=[],
        query="content", target="", k=3,
    ))
    out = capsys.readouterr().out
    assert "Test" in out or "test" in out
    assert rc == 0
