"""Railway boot helper — initializes DB schema before uvicorn starts.

Used by the Procfile: `python -m forge.dashboard.bootstrap && uvicorn ...`
For SQLite (local dev), this just ensures the file exists. For Postgres
(Railway), it runs `init_db` which is a SQLModel `create_all` — adequate
for v1; future versions move to Alembic migrations.
"""
from __future__ import annotations

import logging
import sys

from .db import init_db, make_engine
from .settings import Settings


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[bootstrap] %(message)s")
    log = logging.getLogger("forge.dashboard.bootstrap")
    s = Settings()
    log.info("database_url kind=%s", s.database_url.split("://", 1)[0])
    engine = make_engine(s.database_url)
    init_db(engine)
    log.info("schema ready (auth_enabled=%s)", bool(s.dashboard_password))
    if not s.dashboard_password:
        log.warning("DASHBOARD_PASSWORD not set — dashboard will run in OPEN MODE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
