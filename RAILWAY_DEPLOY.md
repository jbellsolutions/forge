# Deploying the forge dashboard to Railway

The dashboard is the cloud-hosted control surface for forge. Local
forge runtime stays the source of truth; the dashboard mirrors via the
sync API. v1 = single-operator (one shared password).

## Prerequisites

- A Railway account (https://railway.app — free tier works for v1)
- The Railway CLI: `brew install railway` (or `npm i -g @railway/cli`)
- An Anthropic API key (for the orchestrator chat in C-2)

## One-shot deploy

```bash
# from the forge repo root
railway login
railway init                          # name the project: "forge-dashboard"
railway add --plugin postgresql       # provisions Postgres; sets DATABASE_URL
```

Set required env vars in Railway (CLI or dashboard):

```bash
railway variables set DASHBOARD_PASSWORD="<choose a strong password>"
railway variables set SESSION_SECRET="$(openssl rand -hex 32)"
railway variables set SYNC_SHARED_SECRET="$(openssl rand -hex 32)"
railway variables set ANTHROPIC_API_KEY="sk-ant-..."
# Optional (defaults sane):
# railway variables set ORCHESTRATOR_PROFILE=anthropic
```

Push and deploy:

```bash
railway up
```

Railway autodetects Python via nixpacks, runs the `buildCommand` from
`railway.json` (`pip install -e ".[dashboard]"`), and starts via the
`startCommand` (`python -m forge.dashboard.bootstrap && uvicorn ...`).

Open the URL Railway prints (or `railway open`). Log in with
`DASHBOARD_PASSWORD`. You should see Workspace · Changelog · Genome —
all empty until the first sync push.

## First sync push

From your laptop:

```bash
export FORGE_SYNC_URL="https://<your-railway-app>.up.railway.app"
export FORGE_SYNC_TOKEN="<the SYNC_SHARED_SECRET you set above>"
forge sync push
```

Refresh the dashboard. Existing local agents, recursion ledger rows,
and genome memories appear.

(`forge sync` ships with section C-3.)

## Updating

```bash
git push origin main      # GitHub
railway up                # or wire a Railway → GitHub auto-deploy
```

## Security notes

- The Railway URL is **public** by default. `DASHBOARD_PASSWORD` is the only
  gate in v1.
- A compromised Railway deploy can ENQUEUE actions (PendingAction rows)
  but cannot execute them on your laptop — local `forge sync pull-and-apply`
  decides what runs. Never expose this distinction to a third party.
- Rotate `SYNC_SHARED_SECRET` if you suspect leakage. Local clients
  re-read `~/.forge/.env` at next sync.
