#!/usr/bin/env bash
# ledger-emit.sh — Emit vidux-specific events into the agent ledger
# Source this file; do not execute directly.
#
# Provides:
#   vidux_emit()              — generic event emitter
#   vidux_emit_loop_start()   — emitted when a vidux loop cycle begins
#   vidux_emit_loop_end()     — emitted when a vidux loop cycle completes
#   vidux_emit_checkpoint()   — emitted after checkpoint state is recorded and before git transport
#   vidux_emit_plan_modified()— emitted when PLAN.md is updated
#   vidux_emit_fleet_health() — emitted by vidux-manager fleet-health
#
# All functions are no-ops if the ledger is unavailable.
# Events use the standard ledger JSONL schema with vidux-prefixed event names.

# Source config if not already loaded
_EMIT_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./scripts/lib/ledger-config.sh
source "${_EMIT_SCRIPT_DIR}/ledger-config.sh"

# Guard against double-sourcing
[[ -n "${_VIDUX_LEDGER_EMIT_LOADED:-}" ]] && return 0
_VIDUX_LEDGER_EMIT_LOADED=1

# --- Internal helpers ----------------------------------------------------- #

_vidux_ts() {
  date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%S.000Z"
}

_vidux_eid() {
  local event="$1" ts="$2"
  local hash
  hash=$(printf '%s%s%s' "$event" "$ts" "$$" | shasum -a 256 2>/dev/null | cut -c1-12)
  printf 'evt_vidux_%s_%s' "$event" "$hash"
}

_vidux_detect_agent() {
  if [[ -n "${CODEX_SESSION_ID:-}${CODEX_THREAD_ID:-}" ]]; then
    local sid="${CODEX_SESSION_ID:-${CODEX_THREAD_ID:-unknown}}"
    printf 'codex/%s' "${sid:0:8}"
  elif [[ -n "${CLAUDE_SESSION_ID:-}" ]]; then
    printf 'claude-code/%s' "${CLAUDE_SESSION_ID:0:8}"
  elif [[ -n "${CURSOR_SESSION_ID:-}" ]]; then
    printf 'cursor/%s' "${CURSOR_SESSION_ID:0:8}"
  else
    printf 'vidux/%s' "$$"
  fi
}

_vidux_detect_repo() {
  if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    basename "$CLAUDE_PROJECT_DIR"
  elif [[ -n "${CODEX_PROJECT_DIR:-}" ]]; then
    basename "$CODEX_PROJECT_DIR"
  elif git rev-parse --show-toplevel &>/dev/null; then
    basename "$(git rev-parse --show-toplevel)"
  else
    basename "$(pwd)"
  fi
}

_vidux_json_string() {
  local value="${1:-}"
  if command -v jq &>/dev/null; then
    jq -Rn --arg value "$value" '$value'
  else
    value=$(printf '%s' "$value" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '"%s"' "$value"
  fi
}

_vidux_abs_path() {
  local path="${1:-}"
  [[ -z "$path" ]] && return 0
  local dir base abs_dir
  dir="$(dirname "$path")"
  base="$(basename "$path")"
  if abs_dir="$(cd "$dir" 2>/dev/null && pwd -P)"; then
    printf '%s/%s' "$abs_dir" "$base"
  else
    printf '%s/%s' "$(pwd -P)" "$path"
  fi
}

# Convergence ladder (Harness Contract block 8): branch_pushed < pr_open < merged < findable.
# "done"/"completed" are NOT terminal status words — they map down to the rung the
# caller can actually prove. A row is only `findable` (the true terminal) with a
# merge SHA reachable from trunk AND a build/URL locator; `merged` requires a SHA.
# Legacy callers passing done|completed are mapped to `merged` ONLY when a merge SHA
# is present in the environment (VIDUX_MERGE_SHA), else demoted to `pr_open` so the
# ledger can never overclaim convergence the work has not reached.
_vidux_handoff_status() {
  local raw="${1:-pr_open}"
  case "$raw" in
    findable)
      printf 'findable'
      ;;
    merged)
      printf 'merged'
      ;;
    pr_open|branch_pushed)
      printf '%s' "$raw"
      ;;
    done|completed)
      # Honest-status rule: a bare "done"/"completed" cannot certify a merge.
      # Only stamp `merged` when a SHA proves it; otherwise it is still `pr_open`.
      if [[ -n "${VIDUX_MERGE_SHA:-}" ]]; then
        printf 'merged'
      else
        printf 'pr_open'
      fi
      ;;
    blocked)
      printf 'blocked'
      ;;
    in_progress)
      printf 'in_progress'
      ;;
    done_with_concerns|needs_review)
      printf 'needs_review'
      ;;
    *)
      printf 'needs_review'
      ;;
  esac
}

_vidux_task_id_from_text() {
  local task="${1:-}"
  [[ -z "$task" ]] && return 0
  if [[ "$task" =~ ^(Task[[:space:]]+[[:alnum:]._-]+): ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  elif [[ "$task" =~ ^([[:alnum:]._-]+): ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  elif [[ "$task" =~ ^(Task[[:space:]]+[[:alnum:]._-]+)[[:space:]] ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  elif [[ "$task" =~ ^([[:alnum:]._-]+)[[:space:]] ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  else
    printf '%s' "$task"
  fi
}

# --- Generic emitter ------------------------------------------------------ #

# vidux_emit EVENT SUMMARY [FILES_JSON] [EXTRA_FIELDS]
#   EVENT       — event name (e.g., "vidux_loop_start")
#   SUMMARY     — human-readable description
#   FILES_JSON  — JSON array of files (default: "[]")
#   EXTRA_FIELDS— additional JSON fields to merge (e.g., ',"score":85')
vidux_emit() {
  ledger_available || return 0

  local event="$1"
  local summary="${2:-}"
  local files="${3:-[]}"
  local extra="${4:-}"
  local ts agent_id repo eid

  ts=$(_vidux_ts)
  agent_id=$(_vidux_detect_agent)
  repo=$(_vidux_detect_repo)
  eid=$(_vidux_eid "$event" "$ts")

  # Truncate summary to 240 chars (ledger convention)
  if [[ ${#summary} -gt 240 ]]; then
    summary="${summary:0:237}..."
  fi

  local entry
  if command -v jq &>/dev/null; then
    entry=$(jq -n -c \
      --arg ts "$ts" \
      --arg eid "$eid" \
      --arg agent_id "$agent_id" \
      --arg repo "$repo" \
      --arg event "$event" \
      --arg summary "$summary" \
      --argjson files "$files" \
      '{ts:$ts, eid:$eid, agent_id:$agent_id, repo:$repo, event:$event, summary:$summary, files:$files}')
    # Merge extra fields if provided
    if [[ -n "$extra" ]]; then
      entry=$(printf '%s' "$entry" | jq -c ". + {${extra}}" 2>/dev/null || printf '%s' "$entry")
    fi
  else
    # Fallback: manual JSON construction (no jq)
    summary=$(printf '%s' "$summary" | sed 's/"/\\"/g; s/\\/\\\\/g')
    entry="{\"ts\":\"${ts}\",\"eid\":\"${eid}\",\"agent_id\":\"${agent_id}\",\"repo\":\"${repo}\",\"event\":\"${event}\",\"summary\":\"${summary}\",\"files\":${files}${extra:+,${extra}}}"
  fi

  # Append atomically
  printf '%s\n' "$entry" >> "$LEDGER_FILE"
}

# --- Vidux-specific emitters ---------------------------------------------- #

# Emitted at the start of a vidux loop cycle
# Args: PROJECT_NAME PLAN_PATH [CYCLE_NUMBER]
vidux_emit_loop_start() {
  local project="${1:-unknown}" plan="${2:-}" cycle="${3:-}"
  local summary="Vidux loop start: ${project}"
  [[ -n "$cycle" ]] && summary="${summary} (cycle ${cycle})"
  local files='[]'
  [[ -n "$plan" ]] && files="[\"${plan}\"]"
  local extra=""
  [[ -n "$cycle" ]] && extra="\"cycle\":${cycle}"
  [[ -n "$project" ]] && extra="${extra:+${extra},}\"project\":\"${project}\""
  vidux_emit "vidux_loop_start" "$summary" "$files" "$extra"
}

# Emitted at the end of a vidux loop cycle
# Args: PROJECT_NAME PLAN_PATH OUTCOME [CYCLE_NUMBER] [TASK_COMPLETED]
vidux_emit_loop_end() {
  local project="${1:-unknown}" plan="${2:-}" outcome="${3:-unknown}"
  local cycle="${4:-}" task="${5:-}"
  local summary="Vidux loop end: ${project} — ${outcome}"
  [[ -n "$task" ]] && summary="${summary}. Task: ${task}"
  local files='[]'
  [[ -n "$plan" ]] && files="[\"${plan}\"]"
  local extra="\"outcome\":\"${outcome}\""
  [[ -n "$cycle" ]] && extra="${extra},\"cycle\":${cycle}"
  [[ -n "$project" ]] && extra="${extra},\"project\":\"${project}\""
  [[ -n "$task" ]] && extra="${extra},\"task\":\"$(printf '%s' "$task" | sed 's/"/\\"/g')\""
  vidux_emit "vidux_loop_end" "$summary" "$files" "$extra"
}

# Emitted after checkpoint state is recorded and before git transport; commit hash is optional for legacy callers.
# Args: PROJECT_NAME PLAN_PATH COMMIT_HASH [STATUS] [NEXT_TASK] [TASK_TEXT]
vidux_emit_checkpoint() {
  local project="${1:-unknown}" plan="${2:-}" commit="${3:-}" status="${4:-done}" next_task="${5:-}" task_text="${6:-}"
  local plan_path handoff proof resume task_id
  plan_path="$(_vidux_abs_path "$plan")"
  handoff="$(_vidux_handoff_status "$status")"
  task_id="$(_vidux_task_id_from_text "$task_text")"
  proof="vidux-checkpoint handoff_status=${handoff}"
  [[ -n "$commit" ]] && proof="${proof}; commit=${commit}"
  [[ -n "$plan_path" ]] && proof="${proof}; plan=${plan_path}"
  [[ -n "$task_id" ]] && proof="${proof}; task_id=${task_id}"
  resume="Resume from ${plan_path}"
  [[ -n "$next_task" ]] && resume="${resume}; next: ${next_task}"

  local summary="Vidux checkpoint: ${project} — ${status}"
  [[ -n "$commit" ]] && summary="${summary} [${commit:0:7}]"

  local files='[]'
  local files_claimed='[]'
  local plan_json status_json handoff_json proof_json resume_json project_json commit_json task_json
  plan_json="$(_vidux_json_string "$plan_path")"
  status_json="$(_vidux_json_string "$status")"
  handoff_json="$(_vidux_json_string "$handoff")"
  proof_json="$(_vidux_json_string "$proof")"
  resume_json="$(_vidux_json_string "$resume")"
  project_json="$(_vidux_json_string "$project")"
  commit_json="$(_vidux_json_string "$commit")"
  task_json="$(_vidux_json_string "$task_id")"
  if [[ -n "$plan_path" ]]; then
    files="[${plan_json}]"
    files_claimed="[${plan_json}]"
  fi

  local extra="\"status\":${status_json},\"handoff_status\":${handoff_json},\"plan_path\":${plan_json},\"proof\":${proof_json},\"next_agent_resume\":${resume_json},\"files_claimed\":${files_claimed},\"lane\":\"vidux-checkpoint\",\"publish_kind\":\"checkpoint\""
  [[ -n "$commit" ]] && extra="${extra},\"commit\":${commit_json}"
  [[ -n "$project" ]] && extra="${extra},\"project\":${project_json}"
  [[ -n "$task_id" ]] && extra="${extra},\"task_id\":${task_json}"
  vidux_emit "vidux_checkpoint" "$summary" "$files" "$extra"
}

# Emitted when PLAN.md is modified (new task, status change, etc.)
# Args: PROJECT_NAME PLAN_PATH CHANGE_TYPE [DETAILS]
vidux_emit_plan_modified() {
  local project="${1:-unknown}" plan="${2:-}" change_type="${3:-update}" details="${4:-}"
  local summary="Vidux plan modified: ${project} — ${change_type}"
  [[ -n "$details" ]] && summary="${summary}: ${details}"
  local files='[]'
  [[ -n "$plan" ]] && files="[\"${plan}\"]"
  local extra="\"change_type\":\"${change_type}\""
  [[ -n "$project" ]] && extra="${extra},\"project\":\"${project}\""
  vidux_emit "vidux_plan_modified" "$summary" "$files" "$extra"
}

# Emitted by vidux-manager fleet-health
# Args: PROJECT_NAME BIMODAL_SCORE QUICK_COUNT DEEP_COUNT MID_COUNT
vidux_emit_fleet_health() {
  local project="${1:-unknown}" score="${2:-0}" quick="${3:-0}" deep="${4:-0}" mid="${5:-0}"
  local summary="Fleet health: ${project} — bimodal ${score}% (quick=${quick}, deep=${deep}, mid=${mid})"
  local extra="\"bimodal_score\":${score},\"quick\":${quick},\"deep\":${deep},\"mid\":${mid},\"project\":\"${project}\""
  vidux_emit "vidux_fleet_health" "$summary" '[]' "$extra"
}
