#!/usr/bin/env bash
# pre-commit-plan-check.sh — validates that code changes have a PLAN.md task entry.
# Exit 0 = allow commit. Exit 1 = block commit.
set -euo pipefail

PLAN="$(git rev-parse --show-toplevel)/PLAN.md"

# If no PLAN.md, allow commit (not a Vidux project)
[ ! -f "$PLAN" ] && exit 0

# Get list of staged files (excluding PLAN.md itself and docs)
STAGED=$(git diff --cached --name-only --diff-filter=ACM | grep -v 'PLAN.md\|\.md$' || true)

# If only docs/plan changed, allow
[ -z "$STAGED" ] && exit 0

# Check that at least one active task exists (v1 checkboxes OR v2 FSM states)
if grep -qE '^\- \[(pending|in_progress)\]|^\- \[ \] ' "$PLAN"; then
  # Active work exists — allow commit
  :
else
  echo "VIDUX: No active or pending task covers this code change. Update PLAN.md first."
  exit 1
fi

exit 0
