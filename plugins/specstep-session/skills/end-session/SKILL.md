---
name: end-session
description: Run the session-end protocol against the SpecStep session-state MCP tools — append a decision-log entry for every material decision shipped this session, file backlog items for anything deferred, resolve or carry forward the backlog item this session picked up, close the build session with a history entry, then ship (commit + PR). Use when ending any session that shipped material work, when the user types `/end-session`, `end session`, `close session`, `wrap up`, or signals "we're done" — and proactively right before declaring a session complete so the recorded state doesn't drift.
---

# /end-session — session-end protocol

The close that makes the open worth running. Everything material this session decided, deferred, or finished gets written to the SpecStep session-state record **before** the work ships, so the history stays true. Skipping it is how a project drifts: decisions live only in a chat log nobody re-reads, deferred work evaporates, and the next session starts blind.

**Discipline principles (the durable core):**
- **No silent state changes.** Every material decision → a decision-log entry. Every deferral → a backlog item, *at the moment you defer it*. The picked-up item gets resolved or explicitly carried forward.
- **Record before you ship.** Write the session-state first; the commit/PR references it, not the other way around.
- **Honest naming.** Reference work by your tracker's real ids (issue / ticket / PR numbers, backlog ids). Don't invent a parallel numbering scheme.
- **The session owns its records.** The session that did the work closes its build session and resolves the item it picked up — it doesn't leave that for "later."

> **Tool names / permissions.** Same as `/start-session`: tools are `mcp__specstep__*` (substitute your MCP connection prefix), self-service scopes only (`session_state.*`, `projects.*`). If a tool returns "tool not found", restart your client once.

---

## ⚙️ Project settings (the ship sequence)

The only project-specific part of the close is **how work lands** (setting 4 from `/start-session`). The session-state writes (steps 1–5) are identical everywhere; the ship (step 6) is yours to define.

*Default ship sequence:* a single [Conventional Commits](https://www.conventionalcommits.org/) commit on a feature branch → push → open a PR → let your CI gate the merge. Adapt to your team's flow (trunk-based, merge vs. squash, required checks, deploy watch). Whatever you choose, **the session-state writes happen first** — they go to the DB via MCP, not into the git diff, so they're done regardless of how the code lands.

---

## Steps

### 1. Did this session ship material work?

**Material** (→ run this protocol): a new feature, a behavior-changing fix, a schema/migration change, a public-contract or wire-shape change, a security-posture change, a pricing/public-copy change, a scope change (deferred/expanded/killed work), or a drift resolution.

**Not material** (→ you can skip the close, but still flag any drift): read-only investigation, exploratory questions, planning that shipped no code, pure formatting / typo / comment-only edits.

When in doubt, log it — a cheap decision-log entry beats a silent state change.

### 2. Append a decision-log entry per material decision

```
mcp__specstep__append_decision_log(
    title: "<short title naming the decision>",
    body: "<markdown — what changed, why, any contract/schema/test impact, and the source>",
    entry_date: "<YYYY-MM-DD — the SHIPPING date, not today if you're backfilling>",
    backfilled_at: <timestamp, only when entry_date != today>,
    public_contract_impact: <string when the change is user/API-visible, else null>,
    files_touched: <array of paths, or null>,
    source_pr_url: "<pr url, when known>",
    source_commit_sha: "<sha, when known>",
    related_build_session_id: "<this session's build-session id from /start-session>")
```

Rules:
- **`entry_date` is the shipping date.** Catching up on something from two days ago? Use that date and set `backfilled_at` to now so the gap stays visible.
- **Don't invent rationale.** Pull it from the PR body / commit message. If thin, say so plainly rather than fabricating.
- **Always pass `related_build_session_id`** (your id from `/start-session`). It links the decision to the session in the cross-aggregate view. Omit it and the entry orphans from that view.
- **Use real ids** in the body — issue/PR numbers, backlog ids. No parallel numbering scheme.

### 3. File a backlog item for anything deferred

Capture deferred work **at the moment you defer it** — anything you described as "out of scope", "later", "follow-up", "next session", or "polish" is a backlog item, not a passing remark.

```
mcp__specstep__file_backlog_item(
    title: "<title>",
    body_markdown: "<what + why + enough to act on it cold, incl. recurrence/search terms>",
    priority: "Critical" | "High" | "Medium" | "Low",
    category: "<short tag>",
    estimated_hours_min: <decimal or null>,
    estimated_hours_max: <decimal or null>,
    source_pr_url: <url or null>,
    source_commit_sha: <sha or null>,
    related_decision_log_entry_ids: [<ids from step 2, if applicable>])
```

If the deferred work is already tracked, cross-reference the existing id via `mcp__specstep__query_backlog` instead of filing a duplicate.

### 4. Resolve or carry forward the picked-up item

If `/start-session` bound a backlog item to this session (the `**Active backlog:** <id>` lead on the build session — read it with `mcp__specstep__get_build_session`), close it out now. The session that did the work owns the record's status.

- **The work shipped it** → resolve it:
  ```
  mcp__specstep__triage_backlog_item(
      backlog_item_id: "<id>",
      new_status: "Resolved",
      closing_pr_url: "<pr url>",
      closing_commit_sha: "<sha>",
      closing_notes_markdown: "<one line: what shipped that closes this>")
  ```
  (`Resolved` requires `closing_pr_url` or `closing_notes_markdown` — pass both when you have them.) If the work only partially satisfied a larger umbrella item, leave the umbrella `InProgress` and file/resolve the specific sub-item instead — don't mark an umbrella done off one slice.
- **The work continues next session** → leave it `InProgress` and note "Backlog `<id>` still in progress — resume here" in the step 5 history entry so the next `/start-session` picks it up.

If nothing was bound, skip this step.

### 5. Close the build session

```
mcp__specstep__end_build_session(
    build_session_id: "<this session's id>",
    session_history_entry_markdown: "<Duration / What shipped / What was attempted but not finished / Drift surfaced / Notes for next session / PRs verified>",
    related_pr_urls: [<every PR url this session touched>],
    related_commit_shas: [<every commit sha>])
```

This flips the session Active → Closed, stamps the end time, and persists the history entry + linked PRs/commits. After this, the next `/start-session` from this (computer, branch) mints a fresh session rather than resuming.

**Verify your PRs before you write that history entry.** For each PR this session created or pushed to, confirm its real state — merged (and that the merge actually contains your latest commit), or in-flight with green checks. Don't record "done" for a PR whose CI is red or whose merge is conflicted; fix it first. Record the verified state in the history entry — that's the audit trail that the check happened. If the session opened no PRs, say "no PRs created" so the absence isn't ambiguous.

### 6. Ship (your ship sequence)

Run your **ship sequence** (the ⚙️ setting above). For the default flow:

```bash
git add <explicit paths>          # stage what you changed — avoid `git add -A` if other work is in flight
git commit -m "<type>(<scope>): <summary>

<body: what shipped, what's deferred, what was verified>

build-session: <your build-session id>"
git push -u origin <branch>
# open a PR via your tool of choice; let CI gate the merge
```

The `build-session: <id>` commit trailer lets a future reader cross-link the commit back to the build-session record without searching. The decision-log entries and the build-session close already landed via MCP in steps 2–5 — they live in the DB, not the git diff, so there's nothing session-state-related to stage.

If this session shipped **no file changes** (a state-only session — a pivot, a drift note, a backlog re-triage), stop after step 5. There's nothing to commit.

### 7. (Optional) clean up the worktree

If you used the optional worktree tier, remove this session's worktree once the PR is pushed:

```bash
cd <primary checkout>
git worktree remove .work/<short-name>     # refuses if uncommitted changes remain — resolve them first
git branch -d <branch> 2>/dev/null || true # the remote + PR keep the work
```

Never remove a worktree with uncommitted changes, and never remove another session's worktree.

---

## Token-usage reporting (automatic — nothing to do here)

Per-session token usage is captured by the **`SessionEnd` hook** bundled with this kit
(`hooks/session-end-usage-reporter.py`), **not** by this skill. When your Claude
session actually ends, the hook parses the transcript (and any sub-agent transcripts),
sums the token totals, and POSTs them to `POST /v1/build-sessions/{id}/usage` — feeding
the project's "cost to build" rollup (`get_build_session_cross_aggregate` → `usage_rollup`).
It resolves *which* build session via the `active-build-session-<session_id>` state file
that `/start-session` step 6 wrote, is idempotent (a re-fired report overwrites, never
duplicates), and fail-open (a reporting failure never blocks session end). So there's
nothing to do here — just be aware the capture happens at the lifecycle boundary, slightly
after this skill runs.

Recording needs `SPECSTEP_API_KEY` (with the `session_state.write` scope) in the
environment; absent it, the reporter no-ops. If you can't run the hook, you can record the
totals manually with `mcp__specstep__record_build_session_usage` instead.

## Common mistakes

- **Skipping because "it's just docs."** A docs change can be material (a terms-of-service edit, a pricing claim, a public protocol change). When in doubt, log it.
- **Forgetting `related_build_session_id`.** The entry then orphans from the cross-aggregate view. Always pass it.
- **Marking an umbrella item Resolved off one slice.** Resolve the specific sub-item; leave the umbrella `InProgress`.
- **Staging everything with `git add -A`** when other work is in flight. Stage explicit paths.
