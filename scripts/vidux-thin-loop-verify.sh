#!/usr/bin/env bash
# Thin-token health check for Vidux product work.
# Load guides/thin-token.md + run this — not full SKILL.md.
# Exit 0 only when focused gates are green.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:${PATH}"

echo "vidux-thin-loop-verify @ $(git rev-parse --short HEAD) ($(git rev-parse --abbrev-ref HEAD))"

npm run test:js

python3 -m unittest \
  tests.test_vidux_contracts.ViduxContractTests.test_deleted_auto_publish_rules_are_rehomed_without_skip \
  tests.test_vidux_contracts.ViduxContractTests.test_goal_navigation_and_deleted_auto_contract \
  tests.test_plan_guard \
  tests.test_write_verify \
  tests.test_step_journal \
  -q

# Structural Simple-default + thin-token docs
test -f guides/thin-token.md
rg -q "Recipe 13" guides/recipes.md
rg -q "function isAdvancedMode" browser/static/app.js
rg -q "getItem\\('vidux:advancedMode'\\) === '1'" browser/static/index.html

# Mount health (opt-in single-skill root, not full repo as default source)
ACTIVE="${HOME}/.ai/skills-active/vidux"
if [[ -L "$ACTIVE" ]]; then
  target="$(readlink "$ACTIVE")"
  if [[ "$target" == "${HOME}/Development/vidux" ]]; then
    echo "WARN: skills-active/vidux points at full repo; prefer vidux-main-active" >&2
  fi
  echo "mount: $target"
fi

echo "THIN_LOOP_VERIFY_PASS"
