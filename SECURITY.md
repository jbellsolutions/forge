# Security Policy

## Supported versions

forge is pre-1.0. Security fixes land on the latest minor release only.

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅        |
| < 0.1   | ❌        |

## Reporting a vulnerability

**Do not open a public GitHub issue for security reports.**

Email **security@usingaitoscale.com** (or open a [private security advisory](https://github.com/jbellsolutions/forge/security/advisories/new)) with:

- A description of the issue and its impact.
- Steps to reproduce, ideally with a minimal `forge` script.
- The forge version (`pip show forge-harness`), Python version, and OS.
- Any relevant `forge doctor` output.

You'll get an acknowledgment within **3 business days** and a fix or
mitigation timeline within **14 days** for confirmed issues.

## Scope

In scope:

- Code execution / sandbox escape via the L2 tool layer (`ShellTool`,
  `CLISubprocessTool` family, `FSWriteTool`).
- Hook-bus bypass (an action reaching `execute` without `PreToolUse` firing).
- Credential leakage from `~/.forge/.env`, provider profiles, or trace files.
- Prompt-injection paths that escape the recursion proposer's `# === FIXED
  ADAPTER BOUNDARY ===` sentinel.
- Path-traversal in `FSReadTool`/`FSWriteTool` sandbox anchors.
- Genome (`~/.forge/genome.json`) integrity — unauthorized writes that
  poison cross-project memory.

Out of scope:

- Issues that require a malicious provider profile YAML the user themselves
  installed (treat as untrusted code; don't run unreviewed YAMLs).
- DoS via expensive prompts (cost gating is the user's responsibility via
  `Telemetry`).
- Vulnerabilities in optional vendor SDKs (`anthropic`, `openai`, `mcp`,
  `composio`, `opentelemetry`) — report those upstream.

## Hardening recommendations for users

1. **Run with deny-lists.** Default tool stance is full-access; tighten per
   persona via `AgentDef.allowed_tools`.
2. **Use dry-run hooks.** Subscribe a `PreToolUse` hook that returns
   `BLOCKED` for destructive ops until manually approved.
3. **Rotate keys in `~/.forge/.env`.** Don't commit it. forge auto-loads
   it on import; treat it like `~/.aws/credentials`.
4. **Audit traces before sharing.** `traces/<run_id>/messages.jsonl`
   contains full conversation history including tool inputs/outputs.
5. **Pin the FIXED ADAPTER BOUNDARY sentinel.** If you customize the
   recursion proposer, keep the sentinel — it's the only thing stopping
   a misaligned proposer from rewriting its own guards.

## Disclosure timeline

- Day 0: Report received, acknowledged within 3 business days.
- Day 0–14: Triage + fix + private advisory drafted.
- Day 14+: Coordinated disclosure. Reporter credited unless they opt out.
- A CVE is requested for any issue rated High or Critical (CVSS 3.1).
