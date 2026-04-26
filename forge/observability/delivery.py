"""Digest delivery — file (default), Slack via MCP (optional).

Three deliveries:

- `MarkdownFileDelivery` — always works, writes `<home>/digests/<period>-<date>.md`.
  This is the no-key fallback and the audit trail. Every other delivery
  also writes the file (cheap insurance).
- `SlackMCPDelivery` — calls the user's already-configured Slack MCP server
  via forge's own `MCPClientPool`. Lazy-imports `mcp` (the official SDK)
  inside the constructor; if the import fails or the server is unreachable
  we fall back to file delivery.
- `make_delivery(home)` — factory. Reads `<home>/delivery.yaml` (or the
  bundled example) and returns the configured delivery. Falls back to
  `MarkdownFileDelivery` if config absent or malformed.

Lifted patterns:
- forge already wires MCP via `forge/tools/mcp_client.py::MCPClientPool` +
  `load_mcp_servers`. We reuse that — no second client, no new deps.
"""
from __future__ import annotations

import json
import logging
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .digest import Digest

log = logging.getLogger("forge.observability.delivery")


class Delivery(ABC):
    @abstractmethod
    async def send(self, digest: Digest) -> dict[str, Any]:
        """Send the digest. Returns a small dict with delivery metadata
        (path written, channel id, etc.). Implementations MUST also write
        the markdown file as an audit trail (or call the file delivery
        explicitly) — never lose the digest just because Slack is down."""


# ---------------------------------------------------------------------------
# File delivery — always available, no deps
# ---------------------------------------------------------------------------

@dataclass
class MarkdownFileDelivery(Delivery):
    """Writes `<home>/digests/{period}-{YYYY-MM-DD}.md`."""
    home: Path

    async def send(self, digest: Digest) -> dict[str, Any]:
        out_dir = self.home / "digests"
        out_dir.mkdir(parents=True, exist_ok=True)
        date = digest.ended_at.strftime("%Y-%m-%d")
        path = out_dir / f"{digest.period}-{date}.md"
        path.write_text(digest.to_markdown(), encoding="utf-8")
        # Mirror the JSON shape next to it for machine reads.
        json_path = out_dir / f"{digest.period}-{date}.json"
        json_path.write_text(
            json.dumps(digest.to_json(), indent=2, default=str),
            encoding="utf-8",
        )
        log.info("digest written to %s", path)
        return {"channel": "file", "path": str(path), "json_path": str(json_path)}


# ---------------------------------------------------------------------------
# Slack via MCP — lazy import, falls back to file on any failure
# ---------------------------------------------------------------------------

@dataclass
class SlackMCPDelivery(Delivery):
    """Slack delivery via the user's already-configured Slack MCP server.

    `server_config` is a dict of the same shape forge's `load_mcp_servers`
    accepts:
        {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-slack"], "env": {...}}
    or:
        {"transport": "http", "url": "https://...", "headers": {...}}

    `tool_name` is the MCP tool to call. Defaults to `slack_send_message`
    (matches several common Slack connectors); the user can override.

    On ANY failure (import error, transport error, tool error), we log a
    warning and fall back to `MarkdownFileDelivery` so the digest is never
    lost. The fallback path is recorded in the returned metadata.
    """
    home: Path
    server_config: dict[str, Any]
    channel: str
    tool_name: str = "slack_send_message"
    text_arg: str = "text"
    channel_arg: str = "channel"

    async def send(self, digest: Digest) -> dict[str, Any]:
        # Always write the file FIRST as an audit trail.
        file_meta = await MarkdownFileDelivery(home=self.home).send(digest)

        try:
            # Lazy import — `mcp` is in the [mcp] extra, not the base install.
            from ..tools.mcp_client import MCPClientPool  # type: ignore
        except Exception as e:  # noqa: BLE001
            log.warning("SlackMCPDelivery: cannot import MCPClientPool (%s); falling back to file", e)
            return {**file_meta, "slack": "skipped", "reason": f"import_error: {e}"}

        try:
            pool = MCPClientPool({"slack": self.server_config})
        except Exception as e:  # noqa: BLE001
            log.warning("SlackMCPDelivery: pool construction failed (%s); falling back to file", e)
            return {**file_meta, "slack": "skipped", "reason": f"pool_error: {e}"}
        try:
            await pool.connect_all()
            try:
                client = pool.get("slack")
            except Exception as e:  # noqa: BLE001
                log.warning("SlackMCPDelivery: no client (%s); falling back to file", e)
                return {**file_meta, "slack": "skipped", "reason": f"no_client: {e}"}
            args = {self.channel_arg: self.channel, self.text_arg: digest.to_markdown()}
            try:
                # MCPClientPool exposes call_tool(server_name, tool, args).
                # Some pool implementations expose the client directly — try both.
                if hasattr(pool, "call_tool"):
                    result = await pool.call_tool("slack", self.tool_name, args)
                elif hasattr(client, "call_tool"):
                    result = await client.call_tool(self.tool_name, args)
                else:
                    raise RuntimeError("MCPClientPool exposes neither call_tool() nor client.call_tool()")
            except Exception as e:  # noqa: BLE001
                log.warning("SlackMCPDelivery: tool call failed (%s); falling back to file", e)
                return {**file_meta, "slack": "failed", "reason": f"call_error: {e}"}
            return {
                **file_meta,
                "slack": "sent",
                "channel": self.channel,
                "tool": self.tool_name,
                "result": str(result)[:500],
            }
        finally:
            try:
                if hasattr(pool, "close_all"):
                    await pool.close_all()
                elif hasattr(pool, "aclose"):
                    await pool.aclose()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_delivery(home: str | Path, *, override: str | None = None) -> Delivery:
    """Read `<home>/delivery.yaml` and return the configured Delivery.

    Falls back to `MarkdownFileDelivery` if:
    - config file is missing,
    - config doesn't parse,
    - configured channel isn't recognized,
    - or `override == "file"`.

    `override` accepts `"file"` or `"slack-mcp"` to force a channel from the CLI.
    """
    home_p = Path(home)
    file_default = MarkdownFileDelivery(home=home_p)

    if override == "file":
        return file_default

    cfg_path = home_p / "delivery.yaml"
    cfg: dict[str, Any] = {}
    if cfg_path.exists():
        try:
            import yaml  # type: ignore  # already a dep elsewhere in forge
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception as e:  # noqa: BLE001
            log.warning("delivery.yaml unreadable (%s); using file delivery", e)
            return file_default

    channel = override or cfg.get("channel") or "file"
    if channel == "file":
        return file_default
    if channel == "slack-mcp":
        slack = cfg.get("slack") or {}
        server_config = slack.get("server")
        slack_channel = slack.get("channel")
        if not server_config or not slack_channel:
            log.warning(
                "delivery.yaml missing slack.server or slack.channel; using file delivery"
            )
            return file_default
        return SlackMCPDelivery(
            home=home_p,
            server_config=server_config,
            channel=slack_channel,
            tool_name=slack.get("tool_name", "slack_send_message"),
            text_arg=slack.get("text_arg", "text"),
            channel_arg=slack.get("channel_arg", "channel"),
        )
    log.warning("unknown delivery channel '%s'; using file delivery", channel)
    return file_default


# ---------------------------------------------------------------------------
# Convenience entry — used by `forge report`
# ---------------------------------------------------------------------------

async def deliver(home: str | Path, digest: Digest, override: str | None = None) -> dict[str, Any]:
    delivery = make_delivery(home, override=override)
    return await delivery.send(digest)
