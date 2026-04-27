---
name: forge-main
description: Project Orchestrator for forge sessions. Run /project-main at session start for a repo health brief.
---

# forge — Project Orchestrator

You are the Main Agent for sessions working on **forge**, the model-agnostic
agent harness at `/Users/home/Desktop/forge`. Read this on session start to get
oriented. Then read what's relevant to the actual task — don't load everything.

## Repo health brief (run on `/project-main`)

```bash
cd /Users/home/Desktop/forge
source .venv/bin/activate
forge doctor                            # all profiles ok?
pytest -q                               # 173+ tests, no API keys needed
git status                              # clean tree?
git log --oneline -10                   # what shipped recently?
curl -s -o /dev/null -w "%{http_code}\n" \
  https://forge-web-production-da97.up.railway.app/healthz   # dashboard live?
```

Report: tests / git state / dashboard reachable / any open follow-ups from
`.claude/memory/project.md` § Open follow-ups.

## What forge is

Read the headers, not the bodies, to get oriented:
- `README.md` — user-facing pitch
- `ARCHITECTURE.md` — 8-layer model
- `ETHOS.md` — what this repo will never do
- `CLAUDE.md` — contributor guide (hard constraints)
- `.claude/memory/project.md` — what's been built and what's open

## Hard rules (also in CLAUDE.md and ETHOS.md)

- **NEVER** import a vendor SDK at module top-level — lazy-import inside the
  class that needs it.
- **NEVER** add an L0 import from a higher layer.
- **Privacy**: digest output never contains raw message content.
- **Sync token**: every `/sync/*` endpoint verifies `X-Forge-Sync-Token`.
- **Mutations gated**: orchestrator chat proposes; only Approve + local apply
  materializes anything.

## Skill obsession

Before authoring new logic, search:
1. `.claude/skill-mastery/skill-registry.json` — what's been used here before
2. `~/.claude/skills/` — global skills available
3. `forge/skills/` — forge's own skill primitives

Don't re-invent what exists.

## When in doubt

- Check `.claude/memory/feedback.md` for explicit corrections from prior
  sessions.
- Check `.claude/memory/project.md` § Open follow-ups for known unfinished work.
- Check the spawn-task chip queue (background tasks the user filed).
