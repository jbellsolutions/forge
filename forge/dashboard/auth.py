"""Single-password auth for the Railway dashboard.

The shared password is hashed with bcrypt at startup and never
stored in plaintext outside of the env var. Sessions ride signed
cookies (itsdangerous). When `DASHBOARD_PASSWORD` is empty, the
dashboard runs in OPEN MODE (local-dev only — a warning is logged).
"""
from __future__ import annotations

import logging
import secrets
import time
from typing import Annotated, Optional

try:
    import bcrypt
    from fastapi import Cookie, Depends, HTTPException, Request, Response, status
    from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "forge.dashboard requires the [dashboard] extra "
        "(fastapi, bcrypt, itsdangerous). Install with: "
        "pip install 'forge-harness[dashboard]'"
    ) from e

from .settings import Settings


log = logging.getLogger("forge.dashboard.auth")


# ---------------------------------------------------------------------------
# Password handling
# ---------------------------------------------------------------------------

def hash_password(password: str) -> bytes:
    """bcrypt-hash a plaintext password. Returns the hash bytes."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10))


def verify_password(password: str, hashed: bytes) -> bool:
    if not hashed or not password:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Auth state — module-level for simplicity (single-tenant).
# ---------------------------------------------------------------------------

class _Auth:
    """Shared auth state. Initialized at app startup via `setup_auth(settings)`."""

    def __init__(self) -> None:
        self.password_hash: bytes | None = None
        self.signer: TimestampSigner | None = None
        self.cookie_name: str = "forge_session"
        self.max_age: int = 60 * 60 * 24 * 30
        self.open_mode: bool = True
        # Simple in-process per-IP rate limit on /login.
        self._login_attempts: dict[str, list[float]] = {}

    def setup(self, settings: Settings) -> None:
        if settings.dashboard_password:
            self.password_hash = hash_password(settings.dashboard_password)
            self.open_mode = False
        else:
            self.password_hash = None
            self.open_mode = True
            log.warning(
                "DASHBOARD_PASSWORD not set — running in OPEN MODE. "
                "Do NOT expose to the public internet."
            )
        secret = settings.session_secret or secrets.token_urlsafe(32)
        self.signer = TimestampSigner(secret)
        self.cookie_name = settings.session_cookie_name
        self.max_age = settings.session_max_age

    def issue_session(self, response: Response, user: str = "operator") -> None:
        if self.signer is None:
            raise RuntimeError("auth not configured; call setup_auth() first")
        token = self.signer.sign(user.encode("utf-8")).decode("utf-8")
        response.set_cookie(
            key=self.cookie_name,
            value=token,
            max_age=self.max_age,
            httponly=True,
            samesite="lax",
        )

    def revoke_session(self, response: Response) -> None:
        response.delete_cookie(self.cookie_name)

    def verify_cookie(self, cookie: str | None) -> str | None:
        if self.open_mode:
            return "open-mode"
        if not cookie or self.signer is None:
            return None
        try:
            user = self.signer.unsign(cookie, max_age=self.max_age)
            return user.decode("utf-8")
        except (BadSignature, SignatureExpired):
            return None

    def can_login(self, ip: str) -> bool:
        """Allow up to 5 attempts per minute per IP."""
        now = time.time()
        bucket = [t for t in self._login_attempts.get(ip, []) if now - t < 60]
        bucket.append(now)
        self._login_attempts[ip] = bucket
        return len(bucket) <= 5


auth = _Auth()


def setup_auth(settings: Settings) -> None:
    auth.setup(settings)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def require_auth(request: Request) -> str:
    """Dependency: return the session user, or raise 401 (HTML pages render
    a redirect to /login; JSON callers see a real 401)."""
    cookie = request.cookies.get(auth.cookie_name)
    user = auth.verify_cookie(cookie)
    if user is None:
        # Distinguish JSON vs HTML clients via Accept header.
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            # Trigger a 303 to /login; HTMLException for routers that catch it.
            raise HTTPException(status_code=303, headers={"Location": "/login"})
        raise HTTPException(status_code=401, detail="not authenticated")
    return user
