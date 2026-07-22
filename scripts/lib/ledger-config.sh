#!/usr/bin/env bash
# ledger-config.sh — Portable ledger discovery for vidux scripts
# Source this file; do not execute directly.
#
# Provides:
#   LEDGER_FILE        — path to activity.jsonl (empty if not found)
#   LEDGER_DIR         — path to ~/.agent-ledger/ (empty if not found)
#   LEDGER_AVAILABLE   — "true" or "false"
#   LEDGER_APPEND_HOOK — path to ledger-append.sh (empty if not found)
#   ledger_available() — returns 0 if ledger exists and is readable
#   ledger_jq()        — runs jq on the ledger file, no-op if unavailable
#
# Discovery order for ledger location:
#   1. VIDUX_LEDGER_FILE env var (explicit override)
#   2. vidux.config.json ledger.path field
#   3. ~/.agent-ledger/activity.jsonl (default)
#
# Discovery order for append hook:
#   1. VIDUX_LEDGER_APPEND env var
#   2. vidux.config.json ledger.append_hook field
#   3. <vidux-root>/scripts/lib/ledger-append.sh (vendored)

# Guard against double-sourcing
[[ -n "${_VIDUX_LEDGER_CONFIG_LOADED:-}" ]] && return 0
_VIDUX_LEDGER_CONFIG_LOADED=1

# --- Locate vidux root ---------------------------------------------------- #
_LEDGER_CFG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_VIDUX_ROOT="${_LEDGER_CFG_SCRIPT_DIR}/../.."
_VIDUX_CONFIG="${_VIDUX_ROOT}/vidux.config.json"

# --- Helper: read a JSON field from config -------------------------------- #
_cfg_get() {
  local path="$1" default="$2"
  if [[ -f "$_VIDUX_CONFIG" ]] && command -v jq &>/dev/null; then
    local val
    val=$(jq -r "$path // empty" "$_VIDUX_CONFIG" 2>/dev/null)
    [[ -n "$val" ]] && printf '%s' "$val" && return
  fi
  printf '%s' "$default"
}

# --- Discover ledger file ------------------------------------------------- #
_discover_ledger_file() {
  # 1. Explicit env var
  if [[ -n "${VIDUX_LEDGER_FILE:-}" && -f "$VIDUX_LEDGER_FILE" ]]; then
    printf '%s' "$VIDUX_LEDGER_FILE"
    return
  fi

  # 2. Config file
  local cfg_path
  cfg_path=$(_cfg_get '.ledger.path' '')
  if [[ -n "$cfg_path" && -f "$cfg_path" ]]; then
    printf '%s' "$cfg_path"
    return
  fi

  # 3. Default location
  local default="${HOME}/.agent-ledger/activity.jsonl"
  if [[ -f "$default" ]]; then
    printf '%s' "$default"
    return
  fi

  printf ''
}

# --- Discover append hook ------------------------------------------------- #
_discover_append_hook() {
  # 1. Explicit env var
  if [[ -n "${VIDUX_LEDGER_APPEND:-}" && -x "$VIDUX_LEDGER_APPEND" ]]; then
    printf '%s' "$VIDUX_LEDGER_APPEND"
    return
  fi

  # 2. Config file
  local cfg_hook
  cfg_hook=$(_cfg_get '.ledger.append_hook' '')
  if [[ -n "$cfg_hook" && -x "$cfg_hook" ]]; then
    printf '%s' "$cfg_hook"
    return
  fi

  # 3. Vendored
  local vendored="${_LEDGER_CFG_SCRIPT_DIR}/ledger-append.sh"
  if [[ -x "$vendored" ]]; then
    printf '%s' "$vendored"
    return
  fi

  printf ''
}

# --- Set exports ---------------------------------------------------------- #
LEDGER_FILE="$(_discover_ledger_file)"
LEDGER_DIR="$(dirname "$LEDGER_FILE" 2>/dev/null || echo '')"
LEDGER_APPEND_HOOK="$(_discover_append_hook)"

if [[ -n "$LEDGER_FILE" && -r "$LEDGER_FILE" ]]; then
  LEDGER_AVAILABLE="true"
else
  LEDGER_AVAILABLE="false"
fi

export LEDGER_FILE LEDGER_DIR LEDGER_AVAILABLE LEDGER_APPEND_HOOK

# --- Public functions ----------------------------------------------------- #

ledger_available() {
  [[ "$LEDGER_AVAILABLE" == "true" ]]
}

# Run a jq query against the ledger. Returns empty/fails silently if unavailable.
ledger_jq() {
  ledger_available || return 0
  command -v jq &>/dev/null || return 0
  jq "$@" "$LEDGER_FILE" 2>/dev/null
}

# Count entries matching a jq filter expression
ledger_count() {
  local filter="${1:-.}"
  ledger_available || { echo 0; return; }
  command -v jq &>/dev/null || { echo 0; return; }
  jq -s "[.[] | select($filter)] | length" "$LEDGER_FILE" 2>/dev/null || echo 0
}

# Get the last N entries matching a jq filter, as JSON array
ledger_last() {
  local n="${1:-10}" filter="${2:-.}"
  ledger_available || { echo '[]'; return; }
  command -v jq &>/dev/null || { echo '[]'; return; }
  jq -s "[.[] | select($filter)] | sort_by(.ts) | .[-${n}:]" "$LEDGER_FILE" 2>/dev/null || echo '[]'
}

# Print diagnostic status line
ledger_status() {
  if ledger_available; then
    local count
    count=$(wc -l < "$LEDGER_FILE" | tr -d ' ')
    local size
    size=$(du -h "$LEDGER_FILE" 2>/dev/null | cut -f1 | tr -d ' ')
    printf 'ledger: %s entries, %s at %s\n' "$count" "$size" "$LEDGER_FILE"
  else
    printf 'ledger: not available\n'
  fi
}
