#!/usr/bin/env bash
# post-commit-checkpoint.sh — prints a reminder to update PLAN.md Progress section.
# Runs after each commit. Does not block anything.
set -euo pipefail

PLAN="$(git rev-parse --show-toplevel)/PLAN.md"

# If no PLAN.md, skip silently
[ ! -f "$PLAN" ] && exit 0

TODAY=$(date +%Y-%m-%d)

# Check if Progress was updated today
if ! grep -q "$TODAY" "$PLAN" 2>/dev/null; then
  echo ""
  echo "VIDUX REMINDER: PLAN.md has no progress entry for today ($TODAY)."
  echo "Update PLAN.md, then emit ledger-emit.sh --event publish before branch/PR/release publish."
  echo ""
fi

exit 0
