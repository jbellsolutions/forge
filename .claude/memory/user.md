---
name: User Profile — Justin Bellware
type: user
last_updated: 2026-04-27
---

# User Profile — Justin (forge owner)

Email: justin@usingaitoscale.com
GitHub: jbellsolutions

## Working style observed during this build

- **Decisive on architecture, light on ceremony.** Says "let's build it" and
  trusts me to scope reasonable defaults. Course-corrects on specifics rather
  than litigating every option up-front.
- **Wants honest framing of trade-offs**, not advocacy. Asked about paperclip:
  "Is it easier and better, or too complicated?" — wanted my read, not a sales
  pitch. Best response shape is a side-by-side table + a recommendation +
  the "what's pulling you toward this?" question.
- **Prefers building over planning** once intent is clear. Auto mode on by
  default. Plan mode only when explicitly invoked.
- **Cost-conscious but not penny-wise.** OK with $0.10–$1 LLM spend per cycle
  for live verification. Eval-gated automation is fine; unbounded autonomy is not.
- **Values visibility over autonomy.** Self-improvement should produce
  reports; agents should propose, humans approve.

## Decision-making patterns

- Quickly accepts recommended-default options when there's a clear "(Recommended)"
  flag.
- Pushes back when a phrase doesn't ring true (e.g. corrected the README's
  code-first opening — wanted plain-English "what does this do" first).
- Will ask the same question two ways to test the answer holds (e.g. "is this
  what it should do?" then "build that into it").

## Tooling

- macOS, Mac mini (`Justins-Mac-mini-3`).
- Python via `.venv` per project. Python 3.14 in forge.
- Railway CLI `4.42.1`, logged in as `jbellsolutions`.
- Has Anthropic API key in `~/.forge/.env`.

## Other projects (out of scope for forge sessions but worth knowing)

- **Notion-Native Ops Agent System v4.0** — separate project at
  `/Users/home/Desktop/AI Inetgraterz Ops Home`. Different stack (Next.js +
  Notion Custom Agents + Slack). Don't mix the two.
- **Brand-voice plugin work** referenced in some session reminders.
