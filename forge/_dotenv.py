"""Tiny .env loader. Single source of truth across CLI + example scripts.

Loads ~/.forge/.env into os.environ on import. Existing env values win
(so you can override per-shell-invocation without editing the file).
"""
from __future__ import annotations

import os
from pathlib import Path


def load(path: str | Path | None = None) -> int:
    """Load a .env file. Returns count of keys set."""
    p = Path(path) if path else Path.home() / ".forge" / ".env"
    if not p.exists():
        return 0
    n = 0
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            # Override only if missing OR existing value is empty.
            if k and (not os.environ.get(k, "").strip()):
                os.environ[k] = v
                n += 1
    except OSError:
        pass
    return n


# Eager load on import.
load()
