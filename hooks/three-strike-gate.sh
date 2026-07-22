#!/usr/bin/env bash
# three-strike-gate.sh — tracks consecutive failures on the same surface.
# After 3 failures, prints escalation guidance.
set -euo pipefail

PLAN="$(git rev-parse --show-toplevel)/PLAN.md"

[ ! -f "$PLAN" ] && exit 0

# Count recent commits mentioning "fix" or "retry" on the same file
RECENT_FIXES=$(git log --oneline -10 2>/dev/null | grep -ci 'fix\|retry\|attempt' || true)

if [ "$RECENT_FIXES" -ge 3 ]; then
  echo ""
  echo "VIDUX THREE-STRIKE GATE: $RECENT_FIXES fix/retry attempts in last 10 commits."
  echo "Consider moving up one abstraction layer:"
  echo "  1. Is the task too large? Break it into sub-tasks."
  echo "  2. Is evidence missing? Gather it first."
  echo "  3. Is the problem in the design, not the code?"
  echo "  4. Run dual five-whys: error root cause + agent behavior root cause."
  echo ""
fi

exit 0
