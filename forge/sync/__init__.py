"""forge.sync — local↔cloud bridge.

Local forge stays the source of truth for the filesystem (agents YAML,
results.tsv, traces, vault, genome). The Railway-hosted dashboard is the
control plane: it shows everything and queues mutations as PendingAction
rows. This module is the bridge.

Two flows:

- `push_deltas(home, url, token)` scans local artifacts since the last
  push and POSTs them to `<url>/sync/push`. Idempotent (server upserts by
  stable ID).
- `pull_pending_actions(home, url, token)` GETs `/sync/pending` (status=
  approved), applies each one to the local filesystem via `apply_pending`,
  and POSTs the resulting diff back to `/sync/applied/<id>`.

Both run via HTTP (stdlib `urllib`); the test suite injects a fake
transport that forwards directly into a FastAPI test client.
"""
from __future__ import annotations

from .pull import apply_pending, pull_pending_actions
from .push import push_deltas
from .state import SyncState

__all__ = [
    "push_deltas", "pull_pending_actions", "apply_pending", "SyncState",
]
