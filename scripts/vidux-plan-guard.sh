#!/usr/bin/env bash
# vidux-plan-guard.sh — detect silent PLAN.md task-count drops (plan-clobber guard).
#
# PLAN.md is the fleet's single source of truth (Doctrine 1: "Plan is the
# store"). A merge conflict resolved wrong, a stale long-lived branch, or a
# bad checkout can silently delete tasks -- the file still parses cleanly, so
# nothing catches it until a human notices work vanished (see
# investigations/2026-04-09-plan-clobber-postmortem.md, severity High, TTR:
# hours -- manual). This mechanizes postmortem fixes R2/R3: record the task
# count at every legitimate checkpoint, and flag any unexplained drop on the
# next read. R1 (.gitattributes merge=union) and R4 (Worktree Handoff
# Protocol, guides/fleet-ops.md) are separate, already-covered fixes.
#
# Subcommands:
#   snapshot <plan>                  record current task count to the sidecar
#   verify <plan> [--json]           compare current count to sidecar; exit
#                                     non-zero iff the drop exceeds threshold
#                                     with no matching [DELETION] entry dated
#                                     on/after the last snapshot
#
# Sidecar file: <plan-dir>/.plan-taskcount (JSON: {count, timestamp}).
# Threshold: 3 tasks, matching the existing circuit-breaker/auto-pause default
# (override with VIDUX_PLAN_GUARD_THRESHOLD).
#
# Task-count regex only matches the known FSM/checkbox states ([ ], [x],
# [pending], [in_progress], [in_review], [verify], [merged], [completed],
# [blocked] -- see SKILL.md's generator/evaluator and convergence-ladder FSMs)
# -- NOT bare '- [' -- because Decision Log / Progress bullets like
# [DELETION] or [2026-06-02] also start with '- [' and would silently inflate
# the count otherwise (the false-positive class documented in
# investigations/2026-06-02-plan-retrospective.md). The count also excludes the
# ## Exit Criteria section (its `- [ ]` lines are gate checkboxes, not tasks
# -- matching the exclusion vidux-loop.sh already applies to HOT/COLD counts).
#
# Known limitation (not fixed here -- would need content-matching, disproportionate
# scope): has_authorizing_deletion only checks that a [DELETION] entry exists
# dated on/after the last snapshot, not that its content actually explains
# THIS drop. A same-day DELETION entry about something unrelated (e.g. "removed
# guides/routines.md") silences a same-day clobber of a different size. Treat a
# clean verify as "an authorized deletion was logged," not "this exact drop was
# reviewed."
set -euo pipefail

THRESHOLD="${VIDUX_PLAN_GUARD_THRESHOLD:-3}"

print_help() {
  cat <<'EOF'
vidux plan-guard — detect silent PLAN.md task-count drops.

usage:
  vidux-plan-guard.sh snapshot <plan>
  vidux-plan-guard.sh verify <plan> [--json]

exit codes (verify): 0 = clean or baseline just established,
                      1 = integrity warning (drop > threshold, no matching
                          [DELETION] entry dated on/after the last snapshot),
                      2 = usage error.
EOF
}

task_count() {
  awk '
    /^## Exit Criteria/ { skip=1; next }
    skip && /^## / { skip=0 }
    !skip { print }
  ' "$1" 2>/dev/null \
    | grep -cE '^[[:space:]]*-\ \[(x| |pending|in_progress|in_review|verify|merged|completed|blocked)\]' \
    || true
}

sidecar_path() {
  printf '%s/.plan-taskcount' "$(dirname "$1")"
}

has_authorizing_deletion() {
  local plan="$1" since_date="$2"
  [ -z "$since_date" ] && return 1
  # Canonical Decision Log format (SKILL.md): - [DELETION] [YYYY-MM-DD] ...
  # The date bracket is optional here (docs/reference/
  # plan-fields.md's own template table taught an unbracketed
  # "[DELETION] YYYY-MM-DD ..." form for years before that doc was fixed to
  # match the canonical bracketed form) -- accept both so an entry written
  # against either doc still authorizes the drop instead of producing a
  # false-positive integrity warning.
  grep -oE '^-\ \[DELETION\]\ \[?[0-9]{4}-[0-9]{2}-[0-9]{2}\]?' "$plan" 2>/dev/null \
    | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' \
    | awk -v since="$since_date" '$1 >= since { found=1 } END { exit !found }'
}

cmd_snapshot() {
  local plan="$1"
  [ -f "$plan" ] || { echo "plan-guard: plan not found: $plan" >&2; exit 2; }
  local count; count="$(task_count "$plan")"
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"count":%s,"timestamp":"%s"}\n' "${count:-0}" "$ts" > "$(sidecar_path "$plan")"
}

cmd_verify() {
  local plan="$1"; shift || true
  local as_json=false
  [ "${1:-}" = "--json" ] && as_json=true
  [ -f "$plan" ] || { echo "plan-guard: plan not found: $plan" >&2; exit 2; }

  local sidecar; sidecar="$(sidecar_path "$plan")"
  local current; current="$(task_count "$plan")"
  current="${current:-0}"

  if [ ! -f "$sidecar" ]; then
    cmd_snapshot "$plan"
    if $as_json; then
      printf '{"integrity_warning":false,"reason":"no_baseline","current_count":%s,"previous_count":null,"drop":0,"threshold":%s}\n' "$current" "$THRESHOLD"
    else
      echo "plan-guard: no baseline sidecar -- created one at $current tasks."
    fi
    return 0
  fi

  local sidecar_data
  if ! sidecar_data="$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get('count', 0))
print(d.get('timestamp', ''))
" "$sidecar" 2>/dev/null)"; then
    # Corrupt/unreadable sidecar -- do NOT silently treat as previous=0 (that
    # fails open: drop would read as 0 and never warn). An integrity guard
    # must not go quiet just because its own baseline got corrupted.
    cmd_snapshot "$plan"
    if $as_json; then
      printf '{"integrity_warning":true,"reason":"corrupt_baseline","current_count":%s,"previous_count":null,"drop":0,"threshold":%s}\n' "$current" "$THRESHOLD"
    else
      echo "PLAN_INTEGRITY_WARNING: sidecar at $sidecar was corrupt or unreadable -- baseline lost, reset to $current tasks. If this wasn't expected, something wrote a bad .plan-taskcount." >&2
    fi
    return 1
  fi
  local previous previous_ts since_date
  previous="$(printf '%s' "$sidecar_data" | sed -n '1p')"
  previous_ts="$(printf '%s' "$sidecar_data" | sed -n '2p')"
  since_date="${previous_ts%%T*}"

  local drop=$(( previous - current ))
  [ "$drop" -lt 0 ] && drop=0

  local warning=false
  if [ "$drop" -gt "$THRESHOLD" ] && ! has_authorizing_deletion "$plan" "$since_date"; then
    warning=true
  fi

  if $as_json; then
    printf '{"integrity_warning":%s,"current_count":%s,"previous_count":%s,"drop":%s,"threshold":%s}\n' \
      "$warning" "$current" "$previous" "$drop" "$THRESHOLD"
  else
    if $warning; then
      echo "PLAN_INTEGRITY_WARNING: task count dropped from $previous to $current (>$THRESHOLD) with no [DELETION] entry dated on/after $since_date." >&2
      echo "  See investigations/2026-04-09-plan-clobber-postmortem.md. If this drop is intentional, add a Decision Log entry: - [DELETION] [<date>] <what and why>." >&2
    else
      echo "plan-guard: clean (previous=$previous current=$current drop=$drop)"
    fi
  fi

  $warning && return 1
  return 0
}

[ $# -lt 1 ] && { print_help; exit 2; }
case "$1" in
  snapshot) shift; cmd_snapshot "$@" ;;
  verify)   shift; cmd_verify "$@" ;;
  -h|--help) print_help; exit 0 ;;
  *) echo "plan-guard: unknown subcommand: $1" >&2; print_help; exit 2 ;;
esac
