#!/usr/bin/env bash
# resolve-plan-store.sh — returns the absolute plan store path from vidux.config.json
# Usage: source this file, then call resolve_plan_store
# Falls back to $VIDUX_ROOT/projects if no config exists.

resolve_plan_store() {
  local vidux_root="${VIDUX_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
  local config="$vidux_root/vidux.config.json"
  local plan_path=""

  if [ -f "$config" ]; then
    # Extract plan_store.path from JSON (portable: no jq dependency)
    plan_path="$(grep -A5 '"plan_store"' "$config" \
      | grep '"path"' \
      | head -1 \
      | sed 's/.*"path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' \
      || true)"
  fi

  # Expand ~ to $HOME
  if [ -n "$plan_path" ]; then
    plan_path="${plan_path/#\~/$HOME}"
  fi

  # Fall back to repo-local projects/
  if [ -z "$plan_path" ] || [ "$plan_path" = "" ]; then
    plan_path="$vidux_root/projects"
  fi

  # Resolve to absolute path
  if [[ "$plan_path" != /* ]]; then
    plan_path="$vidux_root/$plan_path"
  fi

  printf '%s' "$plan_path"
}
