"""Shell tool — Tier 3 CLI fall-through. Sandboxed-by-default via cwd allowlist."""
from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from ...kernel.types import AgentDef, ToolCall, ToolResult
from ..base import Tool


class ShellTool(Tool):
    name = "shell"
    description = "Run a shell command in a sandboxed cwd. Returns stdout+stderr (truncated)."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run."},
            "timeout_seconds": {"type": "integer", "default": 30},
        },
        "required": ["command"],
    }
    tier = "cli"

    def __init__(self, cwd: str | Path = ".forge/sandbox", max_output: int = 8000) -> None:
        self.cwd = Path(cwd)
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.max_output = max_output

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        cmd = call.arguments.get("command", "")
        timeout = int(call.arguments.get("timeout_seconds", 30))
        if not cmd:
            return ToolResult(call.id, self.name, "error: empty command", is_error=True)
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, cwd=str(self.cwd),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = (stdout + b"\n--STDERR--\n" + stderr).decode("utf-8", errors="replace")
            if len(out) > self.max_output:
                out = out[: self.max_output] + f"\n[truncated {len(out) - self.max_output} bytes]"
            return ToolResult(
                call.id, self.name, out,
                is_error=proc.returncode != 0,
                metadata={"returncode": proc.returncode, "command": cmd},
            )
        except asyncio.TimeoutError:
            return ToolResult(call.id, self.name, f"timeout after {timeout}s", is_error=True)
        except Exception as e:  # noqa: BLE001
            return ToolResult(call.id, self.name, f"error: {type(e).__name__}: {e}", is_error=True)


class CLISubprocessTool(Tool):
    """Generic wrapper for `claude code -p`, `codex run`, `gemini cli`, etc.

    Each subclass declares the binary + arg-builder. The harness is provider-neutral
    at the kernel; this lets the kernel rent a specialist CLI as a tool.
    """
    binary: str = ""
    name = ""
    description = ""
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Prompt to send to the CLI."},
            "timeout_seconds": {"type": "integer", "default": 120},
        },
        "required": ["prompt"],
    }
    tier = "cli"

    def __init__(self, cwd: str | Path = ".forge/sandbox", max_output: int = 16000) -> None:
        self.cwd = Path(cwd)
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.max_output = max_output

    def build_args(self, prompt: str) -> list[str]:
        return [self.binary, "-p", prompt]

    async def execute(self, call: ToolCall, agent: AgentDef) -> ToolResult:
        prompt = call.arguments.get("prompt", "")
        timeout = int(call.arguments.get("timeout_seconds", 120))
        args = self.build_args(prompt)
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, cwd=str(self.cwd),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            combined = out + (f"\n--STDERR--\n{err}" if err else "")
            if len(combined) > self.max_output:
                combined = combined[: self.max_output] + "\n[truncated]"
            return ToolResult(
                call.id, self.name, combined,
                is_error=proc.returncode != 0,
                metadata={"returncode": proc.returncode, "binary": self.binary},
            )
        except FileNotFoundError:
            return ToolResult(call.id, self.name, f"binary not found: {self.binary}", is_error=True)
        except asyncio.TimeoutError:
            return ToolResult(call.id, self.name, f"timeout after {timeout}s", is_error=True)


class ClaudeCodeTool(CLISubprocessTool):
    binary = "claude"
    name = "claude_code"
    description = "Delegate a coding task to Claude Code CLI. Returns its output."
    def build_args(self, prompt: str) -> list[str]:
        return [self.binary, "-p", prompt]


class CodexCLITool(CLISubprocessTool):
    binary = "codex"
    name = "codex"
    description = "Delegate a task to OpenAI Codex CLI. Returns its output."
    def build_args(self, prompt: str) -> list[str]:
        return [self.binary, "exec", prompt]


class GeminiCLITool(CLISubprocessTool):
    binary = "gemini"
    name = "gemini"
    description = "Delegate a task to Gemini CLI. Returns its output."
    def build_args(self, prompt: str) -> list[str]:
        return [self.binary, "-p", prompt]
