# .agent/ — forge identity for Project Orchestrator

Lightweight, structured project metadata that the orchestrator reads on session
start to know what this repo is without re-deriving it from filesystem scans.

| File | Purpose |
|---|---|
| `identity.json` | Stable facts (name, language, layer map, deploy URLs) |
| `state.json` | Mutable state (last session id, open follow-ups, active iterations) |
| `README.md` | This file |

Update `identity.json` when:
- A new top-level module gets added (update `key_components`)
- The deploy URL changes
- A new fragile-area regression bites (add to `fragile_areas`)

Update `state.json` after each session. The Project Orchestrator can do this
automatically via `/project-main`.
