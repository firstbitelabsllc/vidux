#!/usr/bin/env bash
# vidux-write-verify.sh — mechanizes Recipe 9 (Edit-Then-Verify).
#
# The #1 fleet friction type (guides/recipes.md Recipe 9: "2/10 sessions") is
# an agent writing a file, believing it wrote real content, and moving on --
# a 0-byte report, a truncated JSON checkpoint, a write that silently landed
# in the wrong path. Recipe 9's re-read-and-compare pattern has existed as
# prose since it was written, but nothing enforced it; this is a thin,
# scriptable check an agent (or a PostToolUse-style hook) can call right after
# a Write/Edit to catch the failure before it compounds into corrupted state.
#
# This is a CHECK, not a retry loop. Recipe 9's "3 consecutive failures =
# degraded" retry logic stays agent-side (the script can't know how to
# regenerate content) -- this just gives that loop a deterministic pass/fail
# signal instead of "looked fine to me."
#
# Subcommands:
#   check <file> [--min-bytes N] [--contains STRING] [--json]
#
# Exit codes: 0 = passed all checks, 1 = a check failed, 2 = usage error.
set -euo pipefail

print_help() {
  cat <<'EOF'
vidux write-verify — re-read-and-compare check for a just-written file.

usage:
  vidux-write-verify.sh check <file> [--min-bytes N] [--contains STRING] [--json]

defaults: --min-bytes 1 (i.e. "not empty"). Pass a realistic --min-bytes for
the file you just wrote when you know its rough expected size -- catching a
truncated write, not just a 0-byte one.

exit codes: 0 = passed, 1 = a check failed, 2 = usage error.
EOF
}

[ $# -lt 1 ] && { print_help; exit 2; }
[ "$1" = "-h" ] || [ "$1" = "--help" ] && { print_help; exit 0; }
[ "$1" != "check" ] && { echo "write-verify: unknown subcommand: $1" >&2; print_help; exit 2; }
shift

FILE=""
MIN_BYTES=1
CONTAINS=""
AS_JSON=false

while [ $# -gt 0 ]; do
  case "$1" in
    --min-bytes)
      [ $# -ge 2 ] || { echo "write-verify: --min-bytes requires a value" >&2; exit 2; }
      MIN_BYTES="$2"; shift 2 ;;
    --contains)
      [ $# -ge 2 ] || { echo "write-verify: --contains requires a value" >&2; exit 2; }
      CONTAINS="$2"; shift 2 ;;
    --json) AS_JSON=true; shift ;;
    *) [ -z "$FILE" ] && FILE="$1"; shift ;;
  esac
done

[ -z "$FILE" ] && { echo "write-verify: check requires a file path" >&2; exit 2; }
case "$MIN_BYTES" in
  ''|*[!0-9]*) echo "write-verify: --min-bytes must be a non-negative integer, got: $MIN_BYTES" >&2; exit 2 ;;
esac

FAIL_REASON=""
if [ ! -e "$FILE" ]; then
  FAIL_REASON="missing"
elif [ ! -s "$FILE" ] && [ "$MIN_BYTES" -gt 0 ]; then
  FAIL_REASON="empty"
else
  SIZE=$(wc -c < "$FILE" | tr -d ' ')
  if [ "$SIZE" -lt "$MIN_BYTES" ]; then
    FAIL_REASON="too_small"
  elif [ -n "$CONTAINS" ] && ! grep -qF -- "$CONTAINS" "$FILE" 2>/dev/null; then
    FAIL_REASON="missing_expected_content"
  fi
fi

SIZE="${SIZE:-0}"

if $AS_JSON; then
  if [ -n "$FAIL_REASON" ]; then
    printf '{"passed":false,"reason":"%s","file":"%s","size_bytes":%s,"min_bytes":%s}\n' \
      "$FAIL_REASON" "$FILE" "$SIZE" "$MIN_BYTES"
  else
    printf '{"passed":true,"file":"%s","size_bytes":%s,"min_bytes":%s}\n' "$FILE" "$SIZE" "$MIN_BYTES"
  fi
else
  if [ -n "$FAIL_REASON" ]; then
    echo "WRITE-VERIFY FAILED ($FAIL_REASON): $FILE (${SIZE} bytes, expected >= ${MIN_BYTES})" >&2
    [ -n "$CONTAINS" ] && [ "$FAIL_REASON" = "missing_expected_content" ] && echo "  expected to contain: $CONTAINS" >&2
    echo "  Recipe 9 (guides/recipes.md): re-read failed. Log the mismatch, retry with fresh content (max 3 attempts), then mark the lane DEGRADED." >&2
  else
    echo "write-verify: ok ($FILE, ${SIZE} bytes)"
  fi
fi

[ -n "$FAIL_REASON" ] && exit 1
exit 0
