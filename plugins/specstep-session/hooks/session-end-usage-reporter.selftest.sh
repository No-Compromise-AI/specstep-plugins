#!/usr/bin/env bash
# Self-test for session-end-usage-reporter.py. Builds a synthetic transcript
# tree (main transcript with a replayed usage line + a subagent transcript)
# and asserts the aggregation: dedup-by-message-id, the four token classes
# kept separate, and out-of-process subagent inclusion. No network, no real
# files outside a temp dir. Run locally after editing the reporter:
#   bash hooks/session-end-usage-reporter.selftest.sh
#
# A SessionEnd hook that miscounts would silently corrupt a project's
# "cost to build" rollup, so this pins the math. The heavy lifting lives in
# the reporter's own `--selftest` mode (assertions travel with the code);
# this wrapper is the conventional shell entry point.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$HERE/session-end-usage-reporter.py"
[[ -f "$HOOK" ]] || { echo "FAIL: $HOOK not found"; exit 1; }
exec python3 "$HOOK" --selftest
