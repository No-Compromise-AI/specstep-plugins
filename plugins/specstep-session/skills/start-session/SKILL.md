---
name: start-session
description: Run the session-start protocol against the SpecStep session-state MCP tools — read your project's context files, query MCP for the active build session + recent decision-log entries + backlog counts, surface drift against your main branch, then resume the existing build session or start a fresh one and bind the backlog item you're picking up. Use BEFORE any material work (new feature, behavior-changing fix, schema/migration, public-contract change, scope change, drift resolution). Trigger when the user types `/start-session`, `start session`, `start a new session`, `pick up where we left off`, or is about to commit material work without a confirmed resume position.
---

# /start-session — session-start protocol

A portable protocol for driving SpecStep's **session-state** MCP tools (build sessions, decision log, backlog, projects, cross-aggregate, token-usage rollup) with discipline. Run it at the start of any session that will ship material work.

**What it buys you.** The session-state tools are inert without a protocol that says *when* to call them. This skill gives an agent a repeatable open: load context → recover where the last session left off → surface drift before it compounds → start (or resume) one build session that everything this session ships will link back to. The payoff is a queryable history — every decision, every deferred item, every session's token cost — instead of state scattered across chat logs and memory.

**Discipline principles (the durable core — keep these whatever else you adapt):**
- **No silent state changes.** Every material decision gets a decision-log entry (at `/end-session`). Picking up a backlog item moves it to `InProgress`. State changes are recorded, not implied.
- **Surface drift, don't hide it.** If the recorded state and the repo disagree, report the gap before doing new work.
- **One session = one build session.** Thread its id through everything you ship so the history links up.
- **Idempotent resume.** Re-running the open recovers the same session rather than spawning duplicates.
- **Confirm before you start.** Report the resume position and let the user course-correct.

> **Tool names.** This kit assumes you connected SpecStep's MCP server as `specstep`, so the tools are `mcp__specstep__*`. If you named the connection differently, substitute your prefix. If a tool returns "tool not found", restart your client once — MCP tool catalogs are fetched at client startup, so tools added after your client launched won't appear until a restart.

> **Permissions.** This protocol uses only **self-service** tools, callable by any authenticated SpecStep user against their own (or their org's) projects: `session_state.read` / `session_state.write` and `projects.read` / `projects.write`. It deliberately does **not** use operator-only surfaces (inbox/triage queues, lessons, applicable-rules) — those will 403 for a normal user. If you need a project to write into, create one with `mcp__specstep__create_project` (or set a default with `mcp__specstep__set_default_project`) before your first build session.

---

## ⚙️ Project settings (adapt these once, then leave them)

These are the only parts that change per project. Sensible defaults are baked in, so the protocol works **unedited** — fill these in to tune it to your repo.

1. **Context files** — what to read at session start to load conventions.
   *Default:* `README.md`, `AGENTS.md`, `CLAUDE.md` (whichever exist). Add your own standards/architecture docs.
2. **Main branch** — the integration branch the drift check compares against.
   *Default:* `main`.
3. **What counts as "material work"** — see the list in step 1; extend it with your project's own triggers (a wire-shape file, a pricing table, a public schema).
4. **Ship sequence** — how `/end-session` lands work (commit message style, PR flow, CI gates). *Default:* Conventional Commits + a feature branch + PR. Defined in the `end-session` skill.
5. **Optional discipline tier** — worktree isolation + a PreToolUse enforcement gate, for teams running several agent sessions in parallel against one repo. *Default:* **off** (advisory — the agent simply follows this skill). See "Optional: parallel-session discipline" at the end.

---

## Steps

Run in order.

### 1. Read your project's context files

Read the **context files** (setting 1) in full to load this project's conventions before doing anything. They're authoritative for how this project wants work done.

While you read, hold the working definition of **material work** (setting 3) — the protocol applies whenever the session will ship any of:
- A new feature, a behavior-changing bug fix, or a refactor with externally-visible effects.
- A schema / migration change.
- A public-contract change (an API endpoint shape, an exported type, a wire format) or a wire-shape break.
- A security-posture change (auth, scopes, secret handling, redaction).
- A pricing / public-copy change.
- A scope change (work deferred, expanded, or killed).
- A drift resolution.

Read-only investigation, exploratory questions, planning that ships no code, and pure formatting fixes are **not** material — you can skip the protocol for those (but still flag any drift you notice).

### 2. Query MCP for the resume context

Run these in parallel:

```
mcp__specstep__list_build_sessions status="Active" limit=5
mcp__specstep__list_decision_log limit=10
mcp__specstep__count_backlog_items_by_status
```

- **Active build sessions** — compare each session's `computer` and `branch` against this machine + branch:
  - **Same `computer`, same `branch`** → resume target. You're picking up where the last session left off here.
  - **Same `computer`, different `branch`** → a parallel session on this machine. Leave it alone.
  - **Different `computer`** → another machine (or teammate). Note its `intent` so you don't duplicate it; don't reach into it. If you're continuing *that* session's work here, you can link the two after step 4 (see "Continuing another machine's session").
  - **No match** → you'll start a fresh build session in step 4.
- **Last 10 decision-log entries** — the material decisions, scope changes, and drift resolutions since the last session. If the newest entry is much older than the work would suggest, that's itself a drift signal.
- **Backlog counts** — Open / InProgress / Resolved / Dismissed. A spike in Open or a non-zero `stale_count` is a cue to triage before piling on more.

### 3. Drift check

Cross-check the recorded state against the actual repo:

- Compare the newest decision-log entry's `source_commit_sha` against your **main branch** (setting 2) tip: `git log -1 origin/<main> --format=%H`.
- Compare the newest entry's date against today.
- If either is more than ~24h stale, list the gap — `git log --oneline <last_recorded_sha>..origin/<main>` — and report how many commits landed, whether any look material (features, schema/contract changes, security commits), and whether any migrations landed. Drift is not a failure; **failing to surface it** is.

If you find genuine drift (the recorded state doesn't match reality), that's itself a material event worth a decision-log entry at `/end-session`.

### 4. Start (or resume) the build session

```
mcp__specstep__start_build_session(
    computer: "<this machine's identifier>",     # stable per machine (e.g. `hostname -s`)
    branch: "<current branch>",
    intent: "<one paragraph: what this session is doing, ≤200 chars>",
    opened_by_client_type: "Mcp",
    worktree_path: "<absolute path>",             # optional; useful with the worktree tier
    initial_current_state_markdown: "<short resume brief>"
)
```

The call is **idempotent on (computer, branch, actor)** — if step 2 found a matching Active session, it returns that id instead of minting a new one. Either way you now hold **the build-session id** to thread through the whole session.

> **Pick a stable `computer`.** Use the same machine identifier every session (e.g. `hostname -s` on macOS/Linux, `%COMPUTERNAME%` on Windows) so resume + cross-machine signals stay meaningful.

> **Continuing another machine's session.** If step 2 surfaced an Active session on a *different* machine and you're genuinely continuing its work here, link them after you have your new id:
> ```
> mcp__specstep__link_session_continuation(
>     build_session_id: "<your new id>",
>     continuation_of_build_session_id: "<the other machine's session id>")
> ```
> Don't auto-link — independent work on the same project is normal and shouldn't be chained.

### 5. Identify + confirm the backlog item you're picking up

If this session is working an existing backlog item, move it to `InProgress` so the board reflects reality — but identify it first, don't move blindly.

- **Explicit id** — if the user named a backlog id (or your `intent` did), use it.
- **Infer** — otherwise find the closest open match:
  ```
  mcp__specstep__query_backlog search="<key terms from the intent>"
  mcp__specstep__list_backlog_items statuses=["Open","InProgress"]
  ```
  Pick the record whose title actually describes this session's work — often exactly one, sometimes none.
- **Resume case** — if step 2 resumed an existing session, read the `**Active backlog:** <ids>` lead already on its current state instead of re-inferring.
- **No match** — brand-new, not-yet-filed work has nothing to move. That's fine.

**Confirm in chat**, then bind it. Report: the resume position (last decision, last commit, drift), backlog counts, the candidate backlog record, and the build-session id (mark it `[resumed]` or `[new]`). Give the user a chance to redirect. Once settled, for each confirmed `Open` record:

```
mcp__specstep__triage_backlog_item(
    backlog_item_id: "<id>",
    new_status: "InProgress",
    triage_notes: "Picked up by build session <id from step 4> (<branch>).")

mcp__specstep__update_session_current_state(
    build_session_id: "<id from step 4>",
    current_state_markdown: "**Active backlog:** <id>. <prior lead, demoted with an **Earlier:** prefix>",
    computer: "<this machine's identifier>")
```

The `**Active backlog:**` lead is what lets `/end-session` find the item to resolve when the work ships. Never move an item silently — surface it in the report first. If the user corrects you after a move, revert it (`new_status="Open"`) and move the right one.

### 6. Record the active build session for the usage reporter

So the token-usage reporter (the `SessionEnd` hook bundled with this kit) can attribute this session's cost to the right build session, write its id to a state file keyed by your Claude session id:

```bash
SF_STATE_DIR="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/.claude/state"
mkdir -p "$SF_STATE_DIR"
printf '%s' "<BUILD_SESSION_ID from step 4>" > "$SF_STATE_DIR/active-build-session-${CLAUDE_CODE_SESSION_ID}"
```

The transcript is too noisy to scrape the id from (decisions / backlog / sessions all look like `019e…`), so this state file is the reliable handoff. It's anchored at the git common dir so it's shared from any worktree, and keyed per Claude session so parallel sessions never collide. If you skip this, the reporter simply logs "not attributed" and no-ops — usage isn't recorded, nothing breaks. (Recording also needs `SPECSTEP_API_KEY` with the `session_state.write` scope in the environment; absent it the reporter no-ops too.)

> Using the **optional enforcement tier**? Also `touch "$SF_STATE_DIR/protocol-done-${CLAUDE_CODE_SESSION_ID}"` here to lift the PreToolUse gate. See the end of this file.

---

## Mid-session

**Update the current state when the direction shifts.** Newest-first, rolling paragraph — demote the prior lead with an `**Earlier:**` prefix, don't delete it:

```
mcp__specstep__update_session_current_state(
    build_session_id: "<id>",
    current_state_markdown: "<new lead>. **Earlier:** <prior>",
    computer: "<this machine's identifier>")
```

**Ping during long stretches without state writes.** If you're doing extended work (deep debugging, a multi-file refactor) without touching state for a while, ping so a background stale-sweep doesn't mistake a working session for a crashed one:

```
mcp__specstep__session_ping(build_session_id: "<id>", computer: "<this machine's identifier>")
```

Pass `computer` on every state-touching call — it stamps "last touched by this machine" in the same write, keeping cross-machine signals honest.

## Researching prior decisions / backlog mid-session

History is queryable, not grep-able:

- `mcp__specstep__query_decisions search="<keywords>"` — full-text over decision-log title + body.
- `mcp__specstep__query_backlog search="<keywords>"` — full-text over backlog title + body.
- `mcp__specstep__list_decision_log entry_date_from=… entry_date_to=…` — date-range filter.
- `mcp__specstep__list_backlog_items statuses=["Open"]` — board-shaped queries.
- `mcp__specstep__get_build_session_cross_aggregate build_session_id=…` — a build session plus every decision-log entry linked to it, every backlog item those decisions touched, and the token-usage rollup, in one call.

## When NOT to run the full protocol

Skip it for read-only research ("how does X work", "where is Y defined") and for sub-agents whose parent already ran it. **Don't** skip it because memory says you "already read the context files" (memory is point-in-time; re-read every session and re-query MCP) or because the task "feels small" (a one-line wire-shape change is material).

---

## Optional: parallel-session discipline

The baseline protocol is **advisory** — it works by the agent following these steps. Teams running several agent sessions against one repo simultaneously can opt into two structural guards. Most single-session users don't need either.

- **Worktree isolation.** Give each session its own git worktree so a branch switch in one never moves `HEAD` for another:
  ```bash
  git fetch origin <main>
  git worktree add .work/<short-name> -b <branch> origin/<main>
  cd .work/<short-name>
  ```
  Then run steps 4–6 from inside it; clean it up at `/end-session` after the PR is pushed.
- **A PreToolUse enforcement gate.** A hook that blocks edit/commit tools until step 6 has written `protocol-done-<session_id>`, turning "run the protocol first" from a convention into a precondition. This kit ships the *pattern*, not a wired-on gate — adopt it only if you want the hard stop. (SpecStep itself runs both guards; that's overlay, not the portable spine.)

If you adopt neither, that's the intended default. The discipline lives in following the steps.
