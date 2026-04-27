---
name: Durable Reference — forge
type: reference
last_updated: 2026-04-27
---

# forge — Reference

Stable facts. Update only when something actually changes.

## Repos / packages

- **GitHub:** `github.com/jbellsolutions/forge`
- **PyPI:** `forge-harness` (import name: `forge`)
- **Branch:** `main`
- **License:** MIT

## Live deployments

| Service | URL | Notes |
|---|---|---|
| Dashboard | https://forge-web-production-da97.up.railway.app | Railway, Postgres-backed, password-gated |
| Healthcheck | `/healthz` | Used by Railway, returns `ok` (200) when up |

## Local layout

- **Repo root:** `/Users/home/Desktop/forge`
- **Default forge home:** `~/.forge/default/` (artifacts: traces, results.tsv, intel/, vault/)
- **Genome (cross-project memory):** `~/.forge/genome.json`
- **Env:** `~/.forge/.env` (ANTHROPIC_API_KEY, optional TAVILY_API_KEY)
- **Railway secrets:** `~/.forge/railway-secrets.env` (chmod 600) — DASHBOARD_PASSWORD,
  SESSION_SECRET, SYNC_SHARED_SECRET. **Never commit.**

## Railway IDs (in case the URL changes)

- Project: `d8c3eab5-f6dd-4433-a4f7-f46e0c01d720` (`forge-dashboard`)
- Web service: `6d162c95-2172-4493-a42b-9ea025478dd3` (`forge-web`)
- Postgres: provisioned via `railway add --database postgres`

## Sync envelope

- Push: `POST /sync/push`, header `X-Forge-Sync-Token: <SYNC_SHARED_SECRET>`
- Pull approved actions: `GET /sync/pending`
- Report applied diff: `POST /sync/applied/{action_id}`
- Propose forge-new design: `POST /sync/propose-design`

## Architecture invariants (don't break)

- 8 layers, lower never imports upper (`forge.kernel` is L0).
- Vendor SDKs lazy-imported inside class constructors.
- Privacy: digest output contains no raw message content.
- All `/sync/*` endpoints verify shared-secret token.
- Local forge is filesystem source of truth; cloud Postgres is mirror + control plane.
