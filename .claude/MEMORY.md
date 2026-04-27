# Memory Index — forge

Typed memory split (read on session start; only load what you need):

- [project.md](memory/project.md) — what's been built, what's deployed, decisions, open questions
- [user.md](memory/user.md) — Justin's preferences, working style, decision patterns
- [feedback.md](memory/feedback.md) — explicit corrections from Justin during sessions
- [reference.md](memory/reference.md) — durable facts: API keys location, deploy URLs, secrets paths
- [archive.md](memory/archive.md) — older entries rotated out of the live files

## Adjacent infrastructure

- [`learning/dream-log.json`](learning/dream-log.json) — extracted insights from prior sessions
- [`learning/observations.json`](learning/observations.json) — recurring patterns / lessons
- [`learning/pii-blocked.json`](learning/pii-blocked.json) — anything the PII filter blocked
- [`security/pii-patterns.json`](security/pii-patterns.json) — regex patterns for PII detection
- [`healing/patterns.json`](healing/patterns.json) — known error → fix mappings
- [`skill-mastery/skill-registry.json`](skill-mastery/skill-registry.json) — skills used, success rates
- [`skill-mastery/evals.json`](skill-mastery/evals.json) — skill outcome log
- [`plans/`](plans/) — saved plan files from prior sessions
- [`agi-1/candidates/`](agi-1/candidates/) — filesystem history of learning iterations

## How to use

At session start: `Read project.md` first (always). Read others only if relevant
to the task. Don't load everything blindly — context tax adds up.

When you learn something durable, append to the right file (don't bury in
chat). Memories are append-only unless explicitly correcting an error.
