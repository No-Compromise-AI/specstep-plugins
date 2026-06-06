# specstep-session

A Claude Code plugin that gives any project a disciplined **session protocol** on top of SpecStep's session-state MCP tools, plus an automatic **per-session token-usage reporter** that feeds each project's "cost to build" rollup.

It ships two skills and one hook:

| Piece | What it does |
|---|---|
| `/start-session` skill | Reads your project's context files, recovers where the last session left off (active build session + recent decisions + backlog), surfaces drift against your main branch, then resumes or starts **one build session** and binds the backlog item you're working. |
| `/end-session` skill | Appends a decision-log entry per material decision, files backlog items for anything deferred, resolves/carries the picked-up item, closes the build session with a history entry, then ships. |
| `session-end-usage-reporter.py` hook | On `SessionEnd`, sums the session's token usage (main + sub-agent transcripts) and POSTs it to your project's build-session usage rollup. Idempotent, fail-open. |

The skills use **only self-service permissions** — `session_state.read/write` and `projects.read/write` — so any authenticated SpecStep user can run the full protocol against their own (or their org's) projects.

---

## Prerequisites

1. **SpecStep's MCP server connected** in your Claude client, conventionally named `specstep` (so the tools resolve as `mcp__specstep__*`). If you named the connection something else, substitute that prefix wherever the skills say `mcp__specstep__`.
2. **A SpecStep project to work in.** Create one with `mcp__specstep__create_project` (or `mcp__specstep__set_default_project`) before your first build session.
3. **(For usage capture) a `SPECSTEP_API_KEY`** in the environment, with the `session_state.write` scope. Without it the protocol still runs; only the automatic token-usage reporting no-ops. Optionally set `SPECSTEP_API_BASE` (defaults to `https://specstep.com`).

---

## Install

### Option A — as a Claude Code plugin (recommended)

Add SpecStep's marketplace, then install the plugin:

```bash
claude plugin marketplace add No-Compromise-AI/specstep-plugins
claude plugin install specstep-session@specstep
```

(Or point the marketplace at a local checkout: `claude plugin marketplace add /path/to/specstep-plugins`.)

The skills become available as `/start-session` and `/end-session`, and the `SessionEnd` usage hook is wired automatically via `hooks/hooks.json` — nothing else to configure.

### Option B — manual / copy-in

Copy the pieces into your project's `.claude/`:

```bash
cp -r plugins/specstep-session/skills/start-session .claude/skills/
cp -r plugins/specstep-session/skills/end-session   .claude/skills/
cp plugins/specstep-session/hooks/session-end-usage-reporter.py .claude/hooks/
```

Then merge the `hooks` block from [`settings.example.json`](settings.example.json) into your `.claude/settings.json`.

---

## Set the API key (for usage capture)

The reporter records usage only when it can authenticate. Put the key in your environment however you manage secrets — e.g.:

```bash
export SPECSTEP_API_KEY="sk_..."        # needs the session_state.write scope
# export SPECSTEP_API_BASE="https://specstep.com"   # only if self-hosting / non-default
```

Verify the reporter is healthy without sending anything:

```bash
python3 plugins/specstep-session/hooks/session-end-usage-reporter.py --selftest
```

---

## The protocol in one screen

**At the start of any session that will ship material work:** run `/start-session`. It:

1. Reads your context files (defaults: `README.md`, `AGENTS.md`, `CLAUDE.md`).
2. Queries `list_build_sessions` / `list_decision_log` / `count_backlog_items_by_status` to recover where you left off.
3. Drift-checks the recorded state against your main branch.
4. Resumes or starts a build session (idempotent on machine + branch).
5. Binds the backlog item you're picking up (`Open → InProgress`) and confirms the resume position with you.
6. Records the build-session id to a state file so the usage reporter can attribute this session's cost.

**At the end:** run `/end-session`. It:

1. Appends a decision-log entry per material decision (linked to the build session).
2. Files backlog items for anything deferred.
3. Resolves or carries forward the picked-up item.
4. Closes the build session with a history entry + linked PRs/commits.
5. Ships your work (your commit/PR flow).

When your Claude session actually ends, the `SessionEnd` hook reports the token totals to the build session.

The discipline that makes it worth it: **no silent state changes, record before you ship, surface drift, one session = one build session, idempotent resume.**

---

## Adapt it to your project (the 5 extension points)

The skills work **unedited** with sensible defaults. To tune them, edit these clearly-marked settings in each `SKILL.md`:

1. **Context files** to read at start — default `README.md` / `AGENTS.md` / `CLAUDE.md`.
2. **Main branch** for the drift check — default `main`.
3. **What counts as "material work"** — extend the generic list with your own triggers.
4. **Ship sequence** — how `/end-session` lands work; default is Conventional Commits + a feature branch + PR.
5. **Optional parallel-session discipline** — worktree isolation + a PreToolUse enforcement gate, for teams running several agent sessions against one repo. Off (advisory) by default.

---

## What this kit deliberately leaves out

SpecStep runs a richer version of this protocol on itself, with surfaces that are **operator-only** and would 403 for a normal user — so they're not in this kit:

- Inbox/triage queues (feedback, bug reports, alerts, new-user signups).
- The lessons-learned and applicable-rules surfaces.

It also avoids imposing SpecStep's own CI gates, coverage ratchets, commit-marker conventions, and git religion. You get the portable session-state discipline; you bring your own engineering standards.

---

## Token-usage reporting details

- Fires on the Claude `SessionEnd` lifecycle event (process exit / conversation close), slightly **after** `/end-session` runs.
- Sums the **authoritative** token usage from the transcript (and out-of-process sub-agent transcripts), deduped by message id — the four billable input classes (fresh input, 5-minute cache write, 1-hour cache write, cache read) kept separate, plus output.
- Resolves which build session via the `active-build-session-<session_id>` state file `/start-session` wrote.
- **Idempotent** (a re-fired report overwrites, never double-counts) and **fail-open** (any failure logs to stderr and exits 0, never blocking session end).
- Tokens only — no dollar amounts leave your machine.
- Manual fallback if you can't run the hook: `mcp__specstep__record_build_session_usage`.
