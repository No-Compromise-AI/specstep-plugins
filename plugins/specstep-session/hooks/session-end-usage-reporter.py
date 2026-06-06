#!/usr/bin/env python3
"""
session-end-usage-reporter.py — SpecStep build-session token-usage reporter.

A Claude Code `SessionEnd` hook. When a session ends it parses the just-
finished transcript (and its out-of-process subagent transcripts), sums the
authoritative token usage — the same numbers the billing system sees — and
POSTs it to SpecStep's `POST /v1/build-sessions/{id}/usage` endpoint so a
project's "cost to build" can be reported as the totals across its build
sessions. Tokens only; no dollars. Part of the SpecStep session-state kit.

WIRING
    As a Claude Code plugin, this is wired by the plugin's `hooks/hooks.json`
    (the `SessionEnd` entry, via `${CLAUDE_PLUGIN_ROOT}`) — nothing to do.

    For a manual (non-plugin) install, add to `.claude/settings.json`:
    "hooks": {
      "SessionEnd": [
        { "hooks": [ { "type": "command",
                       "command": "python3 .claude/hooks/session-end-usage-reporter.py" } ] }
      ]
    }

HOW IT FINDS THE BUILD SESSION
    `/start-session` writes the minted build-session id to
    `<repo>/.claude/state/active-build-session-<claude_session_id>` (keyed per
    Claude session so parallel worktree sessions never collide; anchored at the
    git common dir so it's shared from any worktree — same convention as
    `protocol-done-<id>`). This hook reads it back by the session_id the
    SessionEnd payload hands it. The transcript itself is too noisy to scrape
    the id from (decisions / backlog / sessions all look like `019e...`).
    Override with SPECSTEP_BUILD_SESSION_ID for testing.

ENV
    SPECSTEP_API_KEY        required to POST (needs the session_state.write scope)
    SPECSTEP_API_BASE       endpoint base; default https://specstep.com
    SPECSTEP_BUILD_SESSION_ID   override the state-file lookup (testing)
    SPECSTEP_USAGE_DRY_RUN  when set (or --dry-run), print the payload instead of POSTing

MODES
    (stdin = hook JSON)     normal operation
    --dry-run [transcript]  print the payload that WOULD be sent (manual check)
    --selftest              build a synthetic transcript tree + assert the math

A hook must NEVER block session end: every failure path logs to stderr and
exits 0.
"""
import glob
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

REPORTER_VERSION = "1.0.0"
DEFAULT_API_BASE = "https://specstep.com"
STATE_PREFIX = "active-build-session-"


def _log(msg: str) -> None:
    print(f"[usage-reporter] {msg}", file=sys.stderr)


# ── transcript aggregation (pure; unit-testable) ──────────────────────────
def _fold_file(path: str, tot: dict, seen: set, *, is_subagent: bool) -> None:
    """Fold one transcript file's deduped assistant-usage into `tot`."""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("type") != "assistant":
                    continue
                msg = o.get("message") or {}
                u = msg.get("usage")
                if not u:
                    continue
                # Dedupe by message id — transcripts replay usage lines (~3x).
                # Key is global across files so a message can't be double-counted.
                mid = msg.get("id") or o.get("requestId")
                if mid is not None:
                    if mid in seen:
                        continue
                    seen.add(mid)

                tot["turns"] += 1
                # A turn is "subagent work" if it came from a subagent file OR
                # was an inline sidechain turn in the main transcript.
                if is_subagent or o.get("isSidechain"):
                    tot["sidechain_turns"] += 1

                tot["input_tokens"] += int(u.get("input_tokens", 0) or 0)
                tot["output_tokens"] += int(u.get("output_tokens", 0) or 0)
                tot["cache_read_tokens"] += int(u.get("cache_read_input_tokens", 0) or 0)
                cc = u.get("cache_creation") or {}
                tot["cache_write_5m_tokens"] += int(cc.get("ephemeral_5m_input_tokens", 0) or 0)
                tot["cache_write_1h_tokens"] += int(cc.get("ephemeral_1h_input_tokens", 0) or 0)

                model = msg.get("model")
                if model:
                    tot["_models"].add(model)
                ts = o.get("timestamp")
                if ts:
                    if tot["window_start"] is None or ts < tot["window_start"]:
                        tot["window_start"] = ts
                    if tot["window_end"] is None or ts > tot["window_end"]:
                        tot["window_end"] = ts
    except OSError as e:
        _log(f"could not read {path}: {e}")


def _subagent_files(transcript_path: str) -> list:
    """Out-of-process subagent transcripts live at
    `<dir>/<session-id>/subagents/agent-*.jsonl` — the parent session is the
    directory name, so association needs no field-scraping."""
    d = os.path.dirname(transcript_path)
    sid = os.path.basename(transcript_path)
    if sid.endswith(".jsonl"):
        sid = sid[: -len(".jsonl")]
    return sorted(glob.glob(os.path.join(d, sid, "subagents", "*.jsonl")))


def aggregate(transcript_path: str) -> dict:
    """Sum the main transcript + its subagent transcripts into a usage dict.
    Cache-read dominates by ~1000x, so the four billable input classes are
    kept separate."""
    tot = {
        "turns": 0, "sidechain_turns": 0,
        "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
        "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0,
        "window_start": None, "window_end": None, "_models": set(),
    }
    seen: set = set()
    _fold_file(transcript_path, tot, seen, is_subagent=False)
    for sub in _subagent_files(transcript_path):
        _fold_file(sub, tot, seen, is_subagent=True)
    return tot


def build_payload(transcript_path: str, claude_session_id: str) -> dict:
    tot = aggregate(transcript_path)
    return {
        "claude_session_id": claude_session_id,
        "agent": "claude-code",
        "models": sorted(tot.pop("_models")),
        "input_tokens": tot["input_tokens"],
        "cache_write_5m_tokens": tot["cache_write_5m_tokens"],
        "cache_write_1h_tokens": tot["cache_write_1h_tokens"],
        "cache_read_tokens": tot["cache_read_tokens"],
        "output_tokens": tot["output_tokens"],
        "turns": tot["turns"],
        "sidechain_turns": tot["sidechain_turns"],
        "window_start": tot["window_start"],
        "window_end": tot["window_end"],
        "reporter_version": REPORTER_VERSION,
    }


# ── build-session id resolution ───────────────────────────────────────────
def _state_dir(cwd: str) -> str:
    """The shared .claude/state dir (git common dir's parent), so the marker
    written from any worktree is found from any worktree. Falls back to
    <cwd>/.claude/state."""
    try:
        common = subprocess.run(
            ["git", "-C", cwd or ".", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=5,
        )
        if common.returncode == 0 and common.stdout.strip():
            return os.path.join(os.path.dirname(common.stdout.strip()), ".claude", "state")
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.join(cwd or ".", ".claude", "state")


def resolve_build_session_id(claude_session_id: str, cwd: str) -> str | None:
    env = os.environ.get("SPECSTEP_BUILD_SESSION_ID")
    if env:
        return env.strip()
    if not claude_session_id:
        return None
    path = os.path.join(_state_dir(cwd), STATE_PREFIX + claude_session_id)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


# ── POST ──────────────────────────────────────────────────────────────────
def post_usage(build_session_id: str, payload: dict) -> None:
    base = (os.environ.get("SPECSTEP_API_BASE") or DEFAULT_API_BASE).rstrip("/")
    url = f"{base}/v1/build-sessions/{build_session_id}/usage"
    api_key = os.environ.get("SPECSTEP_API_KEY")
    if not api_key:
        _log("SPECSTEP_API_KEY not set — cannot POST usage; skipping (no-op).")
        return
    req = urllib.request.Request(
        url, method="POST", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            _log(f"recorded usage for build session {build_session_id} "
                 f"({payload['cache_read_tokens']} cache-read, {payload['turns']} turns) → HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        _log(f"POST {url} failed: HTTP {e.code} {e.read()[:200]!r} (non-fatal)")
    except (urllib.error.URLError, OSError) as e:
        _log(f"POST {url} failed: {e} (non-fatal)")


def run(hook: dict) -> None:
    transcript = hook.get("transcript_path")
    claude_session_id = hook.get("session_id") or ""
    cwd = hook.get("cwd") or os.getcwd()

    if not transcript or not os.path.exists(transcript):
        _log(f"no transcript ({transcript!r}); nothing to report.")
        return
    if not claude_session_id:
        claude_session_id = os.path.splitext(os.path.basename(transcript))[0]

    build_session_id = resolve_build_session_id(claude_session_id, cwd)
    payload = build_payload(transcript, claude_session_id)

    if os.environ.get("SPECSTEP_USAGE_DRY_RUN"):
        print(json.dumps({"build_session_id": build_session_id, "url_base":
                          (os.environ.get("SPECSTEP_API_BASE") or DEFAULT_API_BASE),
                          "payload": payload}, indent=2))
        return

    if not build_session_id:
        _log(f"no active build session for claude session {claude_session_id} "
             f"(no state file / env) — not attributed; skipping.")
        return

    post_usage(build_session_id, payload)


# ── entrypoints ────────────────────────────────────────────────────────────
def main(argv: list) -> int:
    try:
        if "--selftest" in argv:
            return _selftest()
        if "--dry-run" in argv:
            os.environ["SPECSTEP_USAGE_DRY_RUN"] = "1"
            argv = [a for a in argv if a != "--dry-run"]
            transcript = argv[1] if len(argv) > 1 else None
            run({"transcript_path": transcript, "session_id": "", "cwd": os.getcwd()})
            return 0

        raw = "" if sys.stdin.isatty() else sys.stdin.read()
        hook = {}
        if raw.strip():
            try:
                hook = json.loads(raw)
            except ValueError:
                _log("stdin was not valid JSON; nothing to report.")
                return 0
        run(hook)
    except Exception as e:  # noqa: BLE001 — a hook must never block session end
        _log(f"unexpected error (non-fatal): {e}")
    return 0


def _selftest() -> int:
    """Synthetic transcript tree → assert dedup, the four token classes, and
    subagent inclusion. No network, no real files outside a temp dir."""
    import tempfile

    def rec(mid, out, cr, cw1h=0, ts="2026-06-05T00:00:00Z", model="claude-opus-4-8"):
        return json.dumps({
            "type": "assistant", "timestamp": ts,
            "message": {"id": mid, "model": model, "usage": {
                "input_tokens": 1, "output_tokens": out,
                "cache_read_input_tokens": cr,
                "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": cw1h}}},
        })

    failures = []
    with tempfile.TemporaryDirectory() as d:
        sid = "11111111-1111-1111-1111-111111111111"
        main_path = os.path.join(d, f"{sid}.jsonl")
        with open(main_path, "w", encoding="utf-8") as fh:
            fh.write(rec("m1", out=10, cr=100, cw1h=5) + "\n")
            fh.write(rec("m1", out=10, cr=100, cw1h=5) + "\n")   # replay → must dedupe
            fh.write(rec("m2", out=20, cr=200) + "\n")
        subdir = os.path.join(d, sid, "subagents")
        os.makedirs(subdir)
        with open(os.path.join(subdir, "agent-x.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(rec("s1", out=3, cr=5000, model="claude-haiku-4-5-20251001") + "\n")

        p = build_payload(main_path, sid)

        def check(name, got, want):
            if got != want:
                failures.append(f"{name}: got {got}, want {want}")

        check("turns (2 main deduped + 1 subagent)", p["turns"], 3)
        check("sidechain_turns (subagent only)", p["sidechain_turns"], 1)
        check("output (10+20+3)", p["output_tokens"], 33)
        check("cache_read (100+200+5000)", p["cache_read_tokens"], 5300)
        check("cache_write_1h (5)", p["cache_write_1h_tokens"], 5)
        check("input (1+1+1)", p["input_tokens"], 3)
        check("models include both tiers", p["models"], ["claude-haiku-4-5-20251001", "claude-opus-4-8"])
        check("claude_session_id", p["claude_session_id"], sid)

    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("SELFTEST PASS — dedup + 4 token classes + subagent inclusion verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
