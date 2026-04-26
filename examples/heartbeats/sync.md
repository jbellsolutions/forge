---
schedule: "*/5 * * * *"
agent: sync
---

# sync — local↔cloud bridge heartbeat

Every 5 minutes:

1. Push local deltas (agents, recursion ledger rows, genome) to the
   Railway-hosted dashboard.
2. Pull any approved PendingActions and apply them locally (write
   `<home>/agents/<name>.yaml`, scaffold projects, fire `recurse_once`),
   then report the diff back so the dashboard's Changelog reflects what
   actually happened.

The dashboard is the control plane; the laptop is the runtime. This
heartbeat is what keeps them in sync.

```bash
forge sync push
forge sync pull-and-apply
```

Set `FORGE_SYNC_URL` and `SYNC_SHARED_SECRET` in `~/.forge/.env` (or pass
`--url` + `--token` explicitly).
