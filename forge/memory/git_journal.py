"""Git-as-session-journal. Lifted from Anthropic harness paper.

Resume a killed session by reading `git diff HEAD~N`.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitJournal:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            self._run(["git", "init", "-q", "-b", "main"])
            self._run(["git", "config", "user.email", "forge@local"])
            self._run(["git", "config", "user.name", "forge"])
            (self.root / ".gitkeep").write_text("")
            self._run(["git", "add", ".gitkeep"])
            self._run(["git", "commit", "-q", "-m", "init journal"])

    def _run(self, args: list[str]) -> str:
        return subprocess.run(
            args, cwd=str(self.root), capture_output=True, text=True, check=False,
        ).stdout

    def checkpoint(self, message: str, files: list[str] | None = None) -> str | None:
        """Stage given files (or all) and commit with the message. Returns sha or None."""
        if files:
            for f in files:
                self._run(["git", "add", "--", f])
        else:
            self._run(["git", "add", "-A"])
        # Skip if nothing to commit
        status = self._run(["git", "status", "--porcelain"])
        if not status.strip():
            return None
        self._run(["git", "commit", "-q", "-m", message])
        sha = self._run(["git", "rev-parse", "HEAD"]).strip()
        return sha or None

    def diff_since(self, n: int = 1) -> str:
        return self._run(["git", "diff", f"HEAD~{n}..HEAD"])

    def log(self, n: int = 10) -> str:
        return self._run(["git", "log", "-n", str(n), "--oneline"])
