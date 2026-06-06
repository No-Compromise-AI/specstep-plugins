#!/usr/bin/env node
//
// run-reporter.js — cross-platform launcher for session-end-usage-reporter.py.
//
// WHY THIS EXISTS
//   A Claude Code hook `command` has no portable way to name the Python
//   interpreter: it's `py` / `python` on Windows and `python3` on macOS/Linux,
//   and the hook shell isn't guaranteed (PowerShell or Git Bash on Windows).
//   Hardcoding `python3` breaks the SessionEnd reporter on Windows — see
//   anthropics/claude-code#46449, which the maintainers resolved with exactly
//   this shape: a tiny Node shim that resolves whichever interpreter exists.
//
//   The hook wires this via the EXEC form (`command: "node"`, `args: [<this>]`),
//   so no shell is involved and path placeholders with spaces are safe.
//
// CONTRACT
//   Resolves the first working Python and runs the reporter with stdin (the
//   SessionEnd payload) + argv (e.g. --selftest / --backfill) passed straight
//   through. Fail-open: if no Python is found, or anything errors, it exits 0 so
//   it never blocks session end — same guarantee as the reporter itself. A
//   non-zero exit is only propagated for the deliberate manual modes (e.g. a
//   bad --backfill invocation), which the SessionEnd hook never triggers.
//
"use strict";

const { spawnSync } = require("node:child_process");
const path = require("node:path");

const script = path.join(__dirname, "session-end-usage-reporter.py");
const forwarded = process.argv.slice(2);

// Most-specific first. `py -3` is the Windows Python launcher (the recommended
// Windows entry point); `python3` is the macOS/Linux standard. Each is only
// *tried* — a missing interpreter spawns ENOENT and we fall through.
const candidates =
  process.platform === "win32"
    ? [["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3", []], ["python", []]];

for (const [bin, prefix] of candidates) {
  const result = spawnSync(bin, [...prefix, script, ...forwarded], { stdio: "inherit" });
  if (result.error) {
    continue; // not installed / couldn't launch → try the next interpreter
  }
  // Ran (whatever its exit code) — we're done. The hook path always exits 0
  // (the reporter is fail-open); manual modes may return a real code.
  process.exit(typeof result.status === "number" ? result.status : 0);
}

process.stderr.write(
  "[usage-reporter] no Python interpreter found (tried " +
    candidates.map(([bin]) => bin).join(", ") +
    "); usage not recorded.\n"
);
process.exit(0);
