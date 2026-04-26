"""Dashboard runtime settings — read from env (Railway-friendly)."""
from __future__ import annotations

from typing import Any

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "forge.dashboard requires the [dashboard] extra. "
        "Install with: pip install 'forge-harness[dashboard]'"
    ) from e


class Settings(BaseSettings):
    """Read from env (Railway sets these via dashboard or `railway variables`).

    Local dev: place in `~/.forge/.env` or pass via shell.
    """
    # Database — Railway addon exposes DATABASE_URL. SQLite for local dev.
    database_url: str = "sqlite:///./forge_dashboard.db"

    # Auth — single shared password (bcrypt-hashed at startup).
    # If empty, the dashboard runs in OPEN MODE (no auth) — suitable only
    # for local dev. A loud warning is logged when bound to a non-loopback host.
    dashboard_password: str = ""

    # Session secret for signed cookies. Auto-generated on first start if empty,
    # but you should set this in production so sessions survive restarts.
    session_secret: str = ""

    # Sync push — clients (local forge runtimes) send this in `X-Forge-Sync-Token`.
    sync_shared_secret: str = ""

    # Provider key for the orchestrator agent (consumed only when chatting).
    anthropic_api_key: str = ""

    # Orchestrator profile — defaults to anthropic; can swap to anthropic-haiku
    # to keep chat costs down.
    orchestrator_profile: str = "anthropic"

    # Cookie/session settings.
    session_cookie_name: str = "forge_session"
    session_max_age: int = 60 * 60 * 24 * 30  # 30 days

    model_config = SettingsConfigDict(
        env_file=None,        # the dashboard host (Railway) supplies env directly
        case_sensitive=False,
        extra="ignore",
    )


def settings_dict() -> dict[str, Any]:
    """Cheap snapshot for the /healthz endpoint and tests."""
    s = Settings()
    return {
        "database_url_kind": s.database_url.split("://", 1)[0],
        "auth_enabled": bool(s.dashboard_password),
        "orchestrator_profile": s.orchestrator_profile,
        "anthropic_configured": bool(s.anthropic_api_key),
        "sync_token_configured": bool(s.sync_shared_secret),
    }
