#!/usr/bin/env bash
# vidux-step-journal.sh — crash-safe intra-row step memoization (durable resume).
#
# The vidux cycle checkpoints at ROW granularity: a SIGTERM mid-cycle restarts
# the whole task. This adds STEP granularity — an append-only JSONL write-ahead
# log per row. After each durable step, record it; on resume, skip any step
# already marked `done` and reuse its result. Idempotency key = (row, step).
#
# This is the durable-execution write-ahead-log pattern (Temporal / Inngest / DBOS)
# reduced to its essence, with ZERO dependencies beyond jq — it rides the existing
# append-only ledger/journal stack. See SKILL.md (Step journal).
#
# Subcommands:
#   record <row> <step> <status> [result-json]   append a step event
#   is-done <row> <step>                          exit 0 iff step recorded `done`
#   resume-point <row> <step1,step2,...>          print first not-done step, else DONE
#   status <row>                                  human-readable step table
#   clear <row>                                   archive the journal (fresh start)
#
# Journal file: ${VIDUX_JOURNAL_DIR:-$HOME/.vidux/journals}/<row>.jsonl
# Status values: done | failed | started  (only `done` gates a skip)
set -euo pipefail

JOURNAL_DIR="${VIDUX_JOURNAL_DIR:-$HOME/.vidux/journals}"

print_help() {
  cat <<'EOF'
vidux step-journal — append-only JSONL step memoization for crash-safe resume.

usage:
  vidux-step-journal.sh record <row> <step> <status> [result-json]
  vidux-step-journal.sh is-done <row> <step>
  vidux-step-journal.sh resume-point <row> <step1,step2,...>
  vidux-step-journal.sh status <row>
  vidux-step-journal.sh clear <row>

status values: done | failed | started   (only `done` gates a skip)
EOF
}

require_jq() {
  command -v jq >/dev/null 2>&1 || { echo "vidux step-journal: jq is required" >&2; exit 3; }
}

# Real PLAN.md task lines carry trailing annotation tags that get added/edited
# WHILE a task is [in_progress] -- exactly the crash-resume window this journal
# exists for (e.g. "API-1: Add an endpoint. [Evidence: fixture]",
# "Task foo [ETA: 1h]"). vidux-loop.sh's TASK_DESC retains these tags; callers
# of `clear`/`record` (vidux-checkpoint.sh, agents) commonly pass the bare
# description without them. Without normalization the two resolve to different
# sanitized filenames, so a checkpoint's clear silently orphans the tagged
# journal instead of archiving it. Strip trailing "[...]" tags before hashing
# so both forms key to the same row.
normalize_row() {
  local r="$1"
  while [[ "$r" =~ ^(.*[^[:space:]])[[:space:]]*\[[^]]*\][[:space:]]*$ ]]; do
    r="${BASH_REMATCH[1]}"
  done
  printf '%s' "$r"
}

sanitize() { printf '%s' "$(normalize_row "$1")" | tr '/ ' '__'; }
journal_file() { printf '%s/%s.jsonl' "$JOURNAL_DIR" "$(sanitize "$1")"; }

last_status() {
  local f; f="$(journal_file "$1")"
  [ -f "$f" ] || { printf 'none'; return 0; }
  jq -R 'fromjson? // empty' < "$f" \
    | jq -rs --arg step "$2" '[.[] | select(.step == $step)] | (last.status // "none")'
}

cmd_record() {
  [ $# -ge 3 ] || { echo "record: need <row> <step> <status> [result-json]" >&2; exit 2; }
  local row="$1" step="$2" status="$3" result="{}"
  [ $# -ge 4 ] && result="$4"
  echo "$result" | jq -e . >/dev/null 2>&1 || { echo "record: result must be valid JSON" >&2; exit 2; }
  mkdir -p "$JOURNAL_DIR"
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  jq -cn --arg ts "$ts" --arg row "$row" --arg step "$step" --arg status "$status" --argjson result "$result" \
    '{ts:$ts, row:$row, step:$step, status:$status, result:$result}' >> "$(journal_file "$row")"
}

cmd_is_done() {
  [ $# -ge 2 ] || { echo "is-done: need <row> <step>" >&2; exit 2; }
  [ "$(last_status "$1" "$2")" = "done" ]
}

cmd_resume_point() {
  [ $# -ge 2 ] || { echo "resume-point: need <row> <step1,step2,...>" >&2; exit 2; }
  local row="$1" steps s
  local IFS=','; read -ra steps <<< "$2"
  for s in "${steps[@]}"; do
    [ -n "$s" ] || continue
    if [ "$(last_status "$row" "$s")" != "done" ]; then printf '%s\n' "$s"; return 0; fi
  done
  printf 'DONE\n'
}

cmd_status() {
  [ $# -ge 1 ] || { echo "status: need <row>" >&2; exit 2; }
  local f; f="$(journal_file "$1")"
  [ -f "$f" ] || { echo "(no journal for row '$1')"; return 0; }
  jq -R 'fromjson? // empty' < "$f" \
    | jq -rs 'group_by(.step) | map(last) | .[] | "  \(.step)\t\(.status)\t\(.ts)"'
}

cmd_clear() {
  [ $# -ge 1 ] || { echo "clear: need <row>" >&2; exit 2; }
  local f; f="$(journal_file "$1")"
  [ -f "$f" ] || { echo "(no journal for row '$1')"; return 0; }
  local bak; bak="${f}.$(date -u +%Y%m%dT%H%M%SZ).bak"
  mv "$f" "$bak"
  echo "archived -> $bak"
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    record)            require_jq; cmd_record "$@" ;;
    is-done)           require_jq; cmd_is_done "$@" ;;
    resume-point)      require_jq; cmd_resume_point "$@" ;;
    status)            require_jq; cmd_status "$@" ;;
    clear)             cmd_clear "$@" ;;
    --help|-h|help|"")  print_help ;;
    *) echo "vidux step-journal: unknown command: $cmd" >&2; print_help >&2; exit 2 ;;
  esac
}

main "$@"
