"""forge.dashboard — Railway-hosted FastAPI dashboard.

Three nav tabs: Workspace · Changelog · Genome.

The package is the optional `[dashboard]` extra. Base install stays
pure-Python; importing this module without the extra installed will
raise ImportError with a clear remediation message.
"""
from __future__ import annotations

# Re-exports are guarded so `from forge.dashboard import app` only works
# when the extra is installed.

try:
    from .server import app, create_app  # noqa: F401
    from .settings import Settings  # noqa: F401
    __all__ = ["app", "create_app", "Settings"]
except ImportError:
    # Graceful: caller can still `import forge` even without the extra.
    __all__ = []
