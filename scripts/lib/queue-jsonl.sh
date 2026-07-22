#!/usr/bin/env bash
# queue-jsonl.sh — JSONL task queue alongside PLAN.md (experimental)
#
# Machines read QUEUE.jsonl for unambiguous task state. Humans read PLAN.md.
# PLAN.md is the queue/planning authority; matching publish ledger rows carry shipped-cycle proof and resume metadata.
# QUEUE.jsonl is a derived index.
#
# Usage:
#   source scripts/lib/queue-jsonl.sh
#   queue_sync <plan-path>           # rebuild QUEUE.jsonl from PLAN.md
#   queue_next <plan-path>           # print next actionable task as JSON
#   queue_count <plan-path>          # print counts by status
#
# QUEUE.jsonl format (one JSON object per line):
#   {"id":"11.8","status":"pending","desc":"...","evidence":true,"depends":"11.1"}

[[ -n "${_VIDUX_QUEUE_LOADED:-}" ]] && return 0
_VIDUX_QUEUE_LOADED=1

_queue_path() {
  local plan_dir
  plan_dir="$(dirname "$1")"
  echo "${plan_dir}/QUEUE.jsonl"
}

# Rebuild QUEUE.jsonl from PLAN.md task lines
queue_sync() {
  local plan="$1"
  [[ ! -f "$plan" ]] && { echo '{"error":"plan not found"}'; return 1; }
  local queue_file
  queue_file="$(_queue_path "$plan")"

  # Parse task lines: - [status] description
  # Extract: status, task ID (if present), description, evidence flag, depends
  : > "$queue_file"  # truncate
  local line_num=0
  while IFS= read -r line; do
    line_num=$((line_num + 1))
    # Match v2 FSM states
    if [[ "$line" =~ ^[[:space:]]*-\ \[(pending|in_progress|completed|blocked)\]\ (.+)$ ]]; then
      local status="${BASH_REMATCH[1]}"
      local desc="${BASH_REMATCH[2]}"
    elif [[ "$line" =~ ^[[:space:]]*-\ \[\ \]\ (.+)$ ]]; then
      local status="pending"
      local desc="${BASH_REMATCH[1]}"
    elif [[ "$line" =~ ^[[:space:]]*-\ \[x\]\ (.+)$ ]]; then
      local status="completed"
      local desc="${BASH_REMATCH[1]}"
    else
      continue
    fi

    # Skip Exit Criteria tasks
    [[ "$desc" == *"Exit Criteria"* ]] && continue

    # Extract task ID (e.g., "Task 12.1:" or "**11.8")
    local task_id=""
    if [[ "$desc" =~ Task\ ([0-9]+\.[0-9]+) ]]; then
      task_id="${BASH_REMATCH[1]}"
    elif [[ "$desc" =~ \*\*([0-9]+\.[0-9]+) ]]; then
      task_id="${BASH_REMATCH[1]}"
    fi

    # Evidence flag
    local has_evidence="false"
    [[ "$desc" =~ \[Evidence: ]] && has_evidence="true"

    # Depends
    local depends=""
    if [[ "$desc" =~ \[Depends:\ ([^]]+)\] ]]; then
      depends="${BASH_REMATCH[1]}"
    fi

    # Escape desc for JSON
    desc="${desc//\\/\\\\}"
    desc="${desc//\"/\\\"}"
    desc="${desc//$'\t'/\\t}"

    printf '{"id":"%s","line":%d,"status":"%s","desc":"%s","evidence":%s,"depends":"%s"}\n' \
      "$task_id" "$line_num" "$status" "$desc" "$has_evidence" "$depends" >> "$queue_file"
  done < "$plan"

  local total
  total=$(wc -l < "$queue_file" | tr -d ' ')
  echo "{\"synced\":true,\"tasks\":$total,\"queue\":\"$queue_file\"}"
}

# Print next actionable task
queue_next() {
  local plan="$1"
  local queue_file
  queue_file="$(_queue_path "$plan")"
  [[ ! -f "$queue_file" ]] && queue_sync "$plan" >/dev/null

  # Priority: in_progress first, then pending
  local result
  result="$(grep '"status":"in_progress"' "$queue_file" 2>/dev/null | head -1)"
  if [[ -n "$result" ]]; then echo "$result"; return 0; fi
  result="$(grep '"status":"pending"' "$queue_file" 2>/dev/null | head -1)"
  if [[ -n "$result" ]]; then echo "$result"; return 0; fi
  echo '{"id":"","status":"done","desc":"no actionable tasks"}'
}

# Print status counts
queue_count() {
  local plan="$1"
  local queue_file
  queue_file="$(_queue_path "$plan")"
  [[ ! -f "$queue_file" ]] && queue_sync "$plan" >/dev/null

  local pending in_progress completed blocked
  pending=$(grep -c '"status":"pending"' "$queue_file" 2>/dev/null | tr -d '[:space:]' || echo 0)
  in_progress=$(grep -c '"status":"in_progress"' "$queue_file" 2>/dev/null | tr -d '[:space:]' || echo 0)
  completed=$(grep -c '"status":"completed"' "$queue_file" 2>/dev/null | tr -d '[:space:]' || echo 0)
  blocked=$(grep -c '"status":"blocked"' "$queue_file" 2>/dev/null | tr -d '[:space:]' || echo 0)

  printf '{"pending":%d,"in_progress":%d,"completed":%d,"blocked":%d}\n' \
    "$pending" "$in_progress" "$completed" "$blocked"
}
