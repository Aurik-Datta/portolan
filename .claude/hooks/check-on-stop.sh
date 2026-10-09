#!/usr/bin/env bash
# Stop hook: before Claude finishes a turn, run `make check` if code, tests or evals changed.
# Exit 2 blocks the stop and feeds the failure back to Claude so it keeps fixing.
set -u
input=$(cat)
# Already continuing because of this hook: don't loop forever, let the turn end.
if [ "$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("stop_hook_active", False))' 2>/dev/null)" = "True" ]; then
  exit 0
fi
cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" || exit 0
changed=$( { git diff --name-only HEAD; git ls-files --others --exclude-standard; } 2>/dev/null \
  | grep -E '^(portolan|tests|evals)/|^Makefile$' || true)
[ -z "$changed" ] && exit 0
if ! out=$(make check 2>&1); then
  echo "make check failed after changes to: $(echo "$changed" | tr '\n' ' ')" >&2
  echo "$out" | grep -E 'REGRESSION|FAILED|Error|error:|failed|passed' | head -40 >&2
  exit 2
fi
exit 0
