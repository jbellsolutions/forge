---
name: Feedback Log — forge
type: feedback
last_updated: 2026-04-27
---

# Explicit corrections from Justin during forge sessions

Newest first. Each entry: date, what was suggested vs. what was correct, and the
generalizable lesson.

---

## 2026-04-27 — Memory location matters; keep projects separate

- **Suggested:** I built forge while running Claude Code from inside the Notion
  Superagent project's worktree. All session metadata, plans, and memory were
  attributed to the wrong project.
- **Correct approach:** Each significant project gets its own `.claude/`
  directory. Sessions are launched from the project root, not from a sibling
  project's worktree. Don't pollute one project's memory with another's
  learnings.
- **Lesson:** Before doing substantial work on a repo, check `pwd` and the
  loaded MEMORY.md path. If they don't match the repo, `cd` first.

## 2026-04-26 — README leads with what it does, not with code

- **Suggested:** README's 60-second pitch was a code block.
- **Correct approach:** Top of README is plain-English "What forge does" +
  "How to use it" with the three runtime targets table. Code lives below the
  fold, in install + 60-second SDK pitch sections.
- **Lesson:** A README's first 200 words are a pitch, not a tutorial. Code
  before the user understands the value proposition is friction.

## 2026-04-26 — Drop-in-and-build flow is load-bearing

- **Suggested:** Initial dashboard chat could only `propose_start_project`
  with one of 4 fixed templates.
- **Correct approach:** `forge new "<description>"` does LLM-driven swarm
  design + asks where to run + emits artifacts in terminal / Claude Code
  subagents / dashboard PendingAction. The user expects "drop the link, describe
  the swarm, get the swarm" as a first-class flow.
- **Lesson:** The advertised UX has to be the actual UX. If the README implies
  "drop and describe," then dropping and describing must work end-to-end.

## 2026-04-26 — Don't ask before doing, when intent is clear

- **Suggested:** Initial Railway deploy: I asked for confirmation before each
  CLI command.
- **Correct approach:** Auto mode means "make reasonable assumptions and
  proceed." When the user says "let's build it" they've authorized the
  reasonable defaults; ask only if a real fork emerges (cost-spend, destructive
  action, irreversible config).
- **Lesson:** Per-step confirmation is friction in auto mode. Surface the
  decisions, then move.
