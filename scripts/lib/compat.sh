#!/usr/bin/env bash
# compat.sh — OS-portable wrappers for stat/date differences
# macOS uses BSD stat/date, Linux uses GNU coreutils.
# Source this once; call the wrapper functions instead of raw stat/date.
[[ -n "${_VIDUX_COMPAT_LOADED:-}" ]] && return 0
_VIDUX_COMPAT_LOADED=1

# Detect OS once
_VIDUX_OS="$(uname -s)"

# file_mtime_epoch <path> — return mtime as Unix epoch seconds
file_mtime_epoch() {
  local path="$1"
  if [[ "$_VIDUX_OS" == "Darwin" ]]; then
    stat -f '%m' "$path" 2>/dev/null || echo 0
  else
    stat -c '%Y' "$path" 2>/dev/null || echo 0
  fi
}

# dir_newest_mtime <path> — return newest mtime among all files in a directory
dir_newest_mtime() {
  local path="$1"
  if [[ "$_VIDUX_OS" == "Darwin" ]]; then
    find "$path" -type f -print0 2>/dev/null \
      | xargs -0 stat -f '%m' 2>/dev/null \
      | sort -rn | head -1 || file_mtime_epoch "$path"
  else
    find "$path" -type f -printf '%T@\n' 2>/dev/null \
      | sort -rn | head -1 | cut -d. -f1 || file_mtime_epoch "$path"
  fi
}

# parse_date_epoch <format> <datestring> — parse a date string to epoch
# format: strftime-style for macOS, or passed to GNU date -d
parse_date_epoch() {
  local fmt="$1" datestr="$2"
  if [[ "$_VIDUX_OS" == "Darwin" ]]; then
    date -j -f "$fmt" "$datestr" "+%s" 2>/dev/null || echo 0
  else
    # GNU date: try direct parsing (ignores format, uses -d)
    date -d "$datestr" "+%s" 2>/dev/null || echo 0
  fi
}

# parse_iso_epoch <ISO-datetime> — parse ISO 8601 datetime to epoch
# Handles: 2026-04-07T12:30:00Z, 2026-04-07T12:30:00, 2026-04-07
parse_iso_epoch() {
  local ts="$1"
  # Strip trailing Z for macOS compatibility
  ts="${ts%%Z}"
  ts="${ts%%.*}"  # strip fractional seconds
  if [[ "$_VIDUX_OS" == "Darwin" ]]; then
    # Try full datetime first, fall back to date-only
    date -j -f "%Y-%m-%dT%H:%M:%S" "$ts" "+%s" 2>/dev/null || \
    date -j -f "%Y-%m-%d" "$ts" "+%s" 2>/dev/null || echo 0
  else
    date -d "$ts" "+%s" 2>/dev/null || echo 0
  fi
}
