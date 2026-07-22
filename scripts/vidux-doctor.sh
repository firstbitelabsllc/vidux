#!/usr/bin/env bash
# vidux-doctor.sh — runtime health checks for the Vidux control plane
# Usage:  bash vidux-doctor.sh [--json] [--fix] [--repo PATH] [--automations-dir PATH] [--automation-db PATH] [--stale-days N]
#
# Checks cross-plan, cross-repo runtime state. Complements `vidux doctor`
# / scripts/vidux-doctor-cli.sh, which checks installation and local CLI
# readiness. This script is the JSON-friendly runtime doctor used by hooks and
# monitors; use --fix only for explicit operator-approved cleanup.
#
# Exit codes: 0 = pass/warn, 1 = block (merge conflicts), 2 = script error
set -euo pipefail

# --- defaults --------------------------------------------------------------- #
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
JSON_MODE=false; FIX_MODE=false; STALE_DAYS=3; MAX_WT=5; MAX_BROWSER_PROCS=7
MAX_BROWSER_SESSION_MINUTES=15
MAX_CODEX_ACTIVE_THREADS=400
MAX_CODEX_ACTIVE_AUTOMATION_THREADS=250
MAX_CODEX_AVG_TITLE_CHARS=2000
MIN_SYSTEM_MEMORY_FREE_PCT=15
AUTOMATIONS_DIR_OVERRIDE=""
AUTOMATION_DB_OVERRIDE=""

# --- parse args ------------------------------------------------------------- #
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)       JSON_MODE=true; shift ;;
    --fix)        FIX_MODE=true; shift ;;
    --repo)       REPO="$2"; shift 2 ;;
    --automations-dir) AUTOMATIONS_DIR_OVERRIDE="$2"; shift 2 ;;
    --automation-db) AUTOMATION_DB_OVERRIDE="$2"; shift 2 ;;
    --stale-days) STALE_DAYS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

# --- locate paths ----------------------------------------------------------- #
REPO="$(cd "$REPO" 2>/dev/null && pwd || echo "$REPO")"
VIDUX_ROOT="$REPO"
CONFIG="$VIDUX_ROOT/vidux.config.json"
PROJECTS_DIR="$VIDUX_ROOT/projects"
AUTOMATIONS_DIR="$VIDUX_ROOT/automations"

# Read config overrides
if [ -f "$CONFIG" ]; then
  # Single python3 call for all config values (was 8 separate calls — ~400-800ms savings)
  _cfg_vals=$(python3 -c "
import json,sys
c=json.load(open(sys.argv[1])).get('defaults',{})
print(c.get('max_worktrees',5))
print(c.get('stale_in_progress_days',3))
print(c.get('max_browser_processes',7))
print(c.get('max_browser_session_minutes',15))
print(c.get('max_codex_active_threads',400))
print(c.get('max_codex_active_automation_threads',250))
print(c.get('max_codex_avg_title_chars',2000))
print(c.get('min_system_memory_free_pct',15))
" "$CONFIG" 2>/dev/null) || true
  if [ -n "$_cfg_vals" ]; then
    MAX_WT=$(echo "$_cfg_vals" | sed -n '1p')
    STALE_DAYS_CFG=$(echo "$_cfg_vals" | sed -n '2p')
    MAX_BROWSER_PROCS=$(echo "$_cfg_vals" | sed -n '3p')
    MAX_BROWSER_SESSION_MINUTES=$(echo "$_cfg_vals" | sed -n '4p')
    MAX_CODEX_ACTIVE_THREADS=$(echo "$_cfg_vals" | sed -n '5p')
    MAX_CODEX_ACTIVE_AUTOMATION_THREADS=$(echo "$_cfg_vals" | sed -n '6p')
    MAX_CODEX_AVG_TITLE_CHARS=$(echo "$_cfg_vals" | sed -n '7p')
    MIN_SYSTEM_MEMORY_FREE_PCT=$(echo "$_cfg_vals" | sed -n '8p')
  fi
  # CLI arg overrides config
  [[ "$STALE_DAYS" -eq 3 ]] && STALE_DAYS="$STALE_DAYS_CFG"
fi

VERSION="$(head -1 "$(dirname "$0")/../VERSION" 2>/dev/null || echo "unknown")"
HOST="$(hostname -s 2>/dev/null || echo unknown)"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# --- output helpers --------------------------------------------------------- #
PASS_COUNT=0; TOTAL=0; BLOCK=false
CHECKS_FILE="$(mktemp)"
trap 'rm -f "$CHECKS_FILE"' EXIT

# Colors (disabled in JSON mode)
if [[ "$JSON_MODE" = false ]]; then
  BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"
else
  BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

_ok()   { if [[ "$JSON_MODE" = false ]]; then echo -e "  ${GREEN}ok${RESET} $1"; fi; }
_warn() { if [[ "$JSON_MODE" = false ]]; then echo -e "  ${YELLOW}!${RESET}  $1"; fi; }
_fail() { if [[ "$JSON_MODE" = false ]]; then echo -e "  ${RED}BLOCK${RESET} $1"; fi; }

# Append a check result (one JSON object per line) to temp file
_add_check() {
  echo "$1" >> "$CHECKS_FILE"
}

# Bash-native JSON string escape (mirrors vidux-loop.sh's json_escape). Was
# called but never defined here -- any warn path embedding a details string
# (e.g. _check_cadence_runtime, _check_schedulewakeup_doctrine_intact) has
# been silently emitting an empty details field via a swallowed "command not
# found" on json_escape since $(...) exit failures don't propagate through
# set -e when embedded in a larger string argument. Fixed by defining it here
# instead of relying on a sibling script's function.
json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\t'/\\t}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  printf '%s' "$s"
}

_pipe_list_json() {
  local entries="$1"
  local json="["
  local first=true
  while IFS='|' read -ra names; do
    for n in "${names[@]}"; do
      [[ -z "$n" ]] && continue
      local escaped="${n//\"/\\\"}"
      [[ "$first" = true ]] && first=false || json="$json,"
      json="$json\"$escaped\""
    done
  done <<< "$entries"
  echo "$json]"
}

_resolve_automations_dir() {
  if [[ -n "$AUTOMATIONS_DIR_OVERRIDE" ]]; then
    echo "$AUTOMATIONS_DIR_OVERRIDE"
    return
  fi
  if [[ -d "$AUTOMATIONS_DIR" ]]; then
    echo "$AUTOMATIONS_DIR"
    return
  fi
  if [[ -d "$HOME/.codex/automations" ]]; then
    echo "$HOME/.codex/automations"
    return
  fi
  echo "$AUTOMATIONS_DIR"
}

AUTOMATIONS_DIR="$(_resolve_automations_dir)"

_resolve_automation_db() {
  if [[ -n "$AUTOMATION_DB_OVERRIDE" ]]; then
    echo "$AUTOMATION_DB_OVERRIDE"
    return
  fi
  if [[ -f "$HOME/.codex/sqlite/codex-dev.db" ]]; then
    echo "$HOME/.codex/sqlite/codex-dev.db"
    return
  fi
  if [[ -f "$HOME/.Codex/sqlite/codex-dev.db" ]]; then
    echo "$HOME/.Codex/sqlite/codex-dev.db"
    return
  fi
  echo "$HOME/.codex/sqlite/codex-dev.db"
}

AUTOMATION_DB="$(_resolve_automation_db)"

_stalled_automation_rows_json() {
  local db_path="$1"
  local automations_dir="$2"
  local grace_minutes=10

  python3 - "$db_path" "$automations_dir" "$grace_minutes" <<'PY'
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

db_path, automations_dir, grace_minutes_s = sys.argv[1:4]
grace_minutes = int(grace_minutes_s)
now_ms = int(time.time() * 1000)

if not os.path.isfile(db_path):
    print(json.dumps({
        "available": False,
        "db_path": db_path,
        "grace_minutes": grace_minutes,
        "rows": [],
    }))
    raise SystemExit

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
query = """
SELECT
  a.id,
  a.next_run_at,
  a.last_run_at,
  COALESCE(r.runs, 0) AS runs
FROM automations a
LEFT JOIN (
  SELECT automation_id, COUNT(*) AS runs
  FROM automation_runs
  GROUP BY automation_id
) r ON r.automation_id = a.id
WHERE a.status = 'ACTIVE'
  AND COALESCE(r.runs, 0) = 0
  AND a.last_run_at IS NULL
  AND (a.next_run_at IS NULL OR a.next_run_at <= ?)
ORDER BY a.next_run_at ASC, a.id ASC
"""

def iso_local(ms):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

rows = []
threshold_ms = now_ms - (grace_minutes * 60 * 1000)
for row in conn.execute(query, (threshold_ms,)):
    aid = row["id"]
    next_run_at = row["next_run_at"]
    repo_backed = False
    if automations_dir:
        repo_backed = os.path.isfile(os.path.join(automations_dir, aid, "automation.toml"))
    overdue_minutes = None
    if next_run_at is not None:
        overdue_minutes = max(0, int((now_ms - next_run_at) / 60000))
    rows.append({
        "id": aid,
        "repo_backed": repo_backed,
        "runs": int(row["runs"] or 0),
        "last_run_at": row["last_run_at"],
        "next_run_at": next_run_at,
        "next_run_local": iso_local(next_run_at),
        "overdue_minutes": overdue_minutes,
    })

print(json.dumps({
    "available": True,
    "db_path": db_path,
    "grace_minutes": grace_minutes,
    "rows": rows,
}))
PY
}

_reduce_harness_prompt_scan() {
  local toml="$1"
  python3 - "$toml" <<'PY'
import json
import sys

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

path = sys.argv[1]
with open(path, "rb") as fh:
    data = tomllib.load(fh)

prompt = (data.get("prompt") or "").lower()
automation_id = data.get("id") or ""
status = data.get("status") or ""
kind = data.get("kind") or ""

reduce_markers = [
    "reduce mode",
    "next_action",
    "fire dispatch",
    "stay under 2 minutes",
    "keep this run brief",
    "scheduled run should stay brief",
]
deep_markers = [
    "implement",
    "build new verification",
    "write new contract tests",
    "create new fake projects",
    "work the highest-value unblocked slice to a real boundary",
    "run the vidux contract suite",
    "do not skip straight from evidence to implementation",
]
section_markers = [
    "\nauthority and read order",
    "\nauthority chain",
    "\nauthority",
    "\nrole boundary",
    "\nrole",
    "\nper-run method",
    "\nexecution focus",
    "\nexecution rules",
    "\nexecution",
    "\nverification",
    "\ncheckpoint",
    "\noutput",
]

reduce_section = prompt
reduce_start = prompt.find("reduce gate")
if reduce_start != -1:
    end_candidates = []
    for marker in section_markers:
        idx = prompt.find(marker, reduce_start + len("reduce gate"))
        if idx != -1:
            end_candidates.append(idx)
    reduce_end = min(end_candidates) if end_candidates else len(prompt)
    reduce_section = prompt[reduce_start:reduce_end]

matched_reduce = [marker for marker in reduce_markers if marker in reduce_section]
matched_deep_reduce = [marker for marker in deep_markers if marker in reduce_section]
matched_deep_any = [marker for marker in deep_markers if marker in prompt]
issues = []
if matched_deep_any and not matched_reduce:
    issues.append("missing_reduce_contract")
if matched_deep_reduce and matched_reduce:
    issues.append("mixed_reduce_and_dispatch_scope")

payload = {
    "automation_id": automation_id,
    "status": status,
    "kind": kind,
    "matched_reduce_markers": matched_reduce,
    "matched_deep_markers": matched_deep_reduce or matched_deep_any,
    "issues": issues,
}
print(json.dumps(payload))
PY
}

_browser_snapshot_json() {
  local browser_regex='playwright_[^[:space:]]*_profile|lightpanda[^[:space:]]*profile|lightpanda'
  local controller_regex='cli-daemon/program\.js|run-cli-server|run-mcp-server|agent-browser'
  local stale_minutes="${MAX_BROWSER_SESSION_MINUTES}"

  BROWSER_REGEX="$browser_regex" CONTROLLER_REGEX="$controller_regex" STALE_MINUTES="$stale_minutes" python3 - <<'PY'
import json
import os
import re
import subprocess

browser_re = re.compile(os.environ["BROWSER_REGEX"].replace("[:space:]", r"\s"))
controller_re = re.compile(os.environ["CONTROLLER_REGEX"].replace("[:space:]", r"\s"))
stale_seconds = max(int(os.environ.get("STALE_MINUTES", "15")), 0) * 60
probe_pid = os.getpid()
probe_ppid = os.getppid()

result = subprocess.run(
    ["ps", "-axo", "pid=,ppid=,etime=,rss=,command="],
    capture_output=True,
    text=True,
    check=True,
)

processes = {}
for raw_line in result.stdout.splitlines():
    line = raw_line.strip()
    if not line:
        continue
    parts = line.split(None, 4)
    if len(parts) != 5:
        continue
    pid_s, ppid_s, etime_s, rss_s, command = parts
    try:
        pid = int(pid_s)
        ppid = int(ppid_s)
        rss = int(rss_s)
    except ValueError:
        continue
    if "-" in etime_s:
        day_part, time_part = etime_s.split("-", 1)
        day_count = int(day_part)
        time_parts = [int(part) for part in time_part.split(":")]
        while len(time_parts) < 3:
            time_parts.insert(0, 0)
        hours, minutes, seconds = time_parts[-3:]
        hours += day_count * 24
    else:
        time_parts = [int(part) for part in etime_s.split(":")]
        if len(time_parts) == 2:
            hours = 0
            minutes, seconds = time_parts
        else:
            while len(time_parts) < 3:
                time_parts.insert(0, 0)
            hours, minutes, seconds = time_parts[-3:]
    etimes = (hours * 3600) + (minutes * 60) + seconds
    if pid in (probe_pid, probe_ppid):
        continue
    processes[pid] = {"pid": pid, "ppid": ppid, "etimes": etimes, "rss": rss, "command": command}


def has_controller_ancestor(pid: int) -> bool:
    current = pid
    for _ in range(64):
        proc = processes.get(current)
        if not proc:
            return False
        if controller_re.search(proc["command"]):
            return True
        current = proc["ppid"]
        if current <= 1:
            return False
    return False


def descends_from(pid: int, ancestor: int) -> bool:
    current = pid
    for _ in range(64):
        if current == ancestor:
            return True
        proc = processes.get(current)
        if not proc:
            return False
        current = proc["ppid"]
        if current <= 1:
            return current == ancestor
    return False


browser_candidates = []
controller_procs = []
profiles = set()
for proc in processes.values():
    command = proc["command"]
    if controller_re.search(command):
        controller_procs.append(proc)
    if not browser_re.search(command):
        continue
    browser_candidates.append(proc)
    match = re.search(r"(playwright_[^\s]*_profile-[^\s]+|lightpanda[^\s]*profile[^\s]*)", command)
    if match:
        profiles.add(match.group(1))

orphan_candidates = [
    {"pid": proc["pid"], "rss_kb": proc["rss"], "command": proc["command"]}
    for proc in browser_candidates
    if not has_controller_ancestor(proc["pid"])
]

stale_controller_candidates = []
for proc in controller_procs:
    pid = proc["pid"]
    if proc["etimes"] < stale_seconds:
        continue
    if not any(descends_from(browser_proc["pid"], pid) for browser_proc in browser_candidates):
        continue
    stale_controller_candidates.append(
        {
            "pid": pid,
            "etimes_seconds": proc["etimes"],
            "age_minutes": round(proc["etimes"] / 60.0, 1),
            "command": proc["command"],
        }
    )

payload = {
    "browser_count": len(browser_candidates),
    "controller_count": len(controller_procs),
    "orphan_count": len(orphan_candidates),
    "rss_mb": round(sum(proc["rss"] for proc in browser_candidates) / 1024.0, 1),
    "profiles": sorted(profiles),
    "orphans": orphan_candidates,
    "stale_session_minutes": int(os.environ.get("STALE_MINUTES", "15")),
    "stale_controller_count": len(stale_controller_candidates),
    "stale_controllers": stale_controller_candidates,
}
print(json.dumps(payload))
PY
}

_codex_thread_snapshot_json() {
  local state_db="${CODEX_STATE_DB:-$HOME/.codex/state_5.sqlite}"

  CODEX_STATE_DB="$state_db" python3 - <<'PY'
import json
import os
import sqlite3

state_db = os.environ["CODEX_STATE_DB"]
payload = {
    "available": False,
    "state_db": state_db,
    "active_threads": 0,
    "active_automation_threads": 0,
    "avg_active_title_len": 0,
    "avg_active_automation_title_len": 0,
    "max_active_title_len": 0,
}

if not os.path.exists(state_db):
    print(json.dumps(payload))
    raise SystemExit(0)

try:
    conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
          SUM(CASE WHEN archived = 0 THEN 1 ELSE 0 END) AS active_threads,
          SUM(CASE WHEN archived = 0 AND title LIKE 'Automation:%' THEN 1 ELSE 0 END) AS active_automation_threads,
          AVG(CASE WHEN archived = 0 THEN LENGTH(title) END) AS avg_active_title_len,
          AVG(CASE WHEN archived = 0 AND title LIKE 'Automation:%' THEN LENGTH(title) END) AS avg_active_automation_title_len,
          MAX(CASE WHEN archived = 0 THEN LENGTH(title) END) AS max_active_title_len
        FROM threads
        """
    )
    row = cur.fetchone() or (0, 0, 0, 0, 0)
    payload.update(
        {
            "available": True,
            "active_threads": int(row[0] or 0),
            "active_automation_threads": int(row[1] or 0),
            "avg_active_title_len": round(float(row[2] or 0), 1),
            "avg_active_automation_title_len": round(float(row[3] or 0), 1),
            "max_active_title_len": int(row[4] or 0),
        }
    )
except sqlite3.Error as exc:
    payload["error"] = str(exc)
finally:
    try:
        conn.close()
    except Exception:
        pass

print(json.dumps(payload))
PY
}

_memory_pressure_snapshot_json() {
  python3 - <<'PY'
import json
import re
import shutil
import subprocess

payload = {
    "available": False,
    "memory_pressure_free_pct": None,
    "memory_free_pct": None,
    "total_bytes": None,
    "vm_free_mb": None,
    "vm_speculative_mb": None,
    "free_mb": None,
    "speculative_mb": None,
    "memory_pct_source": None,
    "vm_pages_source": None,
}

mem_cmd = shutil.which("memory_pressure")
vm_stat_cmd = shutil.which("vm_stat")

if not mem_cmd or not vm_stat_cmd:
    print(json.dumps(payload))
    raise SystemExit(0)

try:
    mem_out = subprocess.run([mem_cmd, "-Q"], capture_output=True, text=True, check=True).stdout
    vm_out = subprocess.run([vm_stat_cmd], capture_output=True, text=True, check=True).stdout
except subprocess.CalledProcessError as exc:
    payload["error"] = str(exc)
    print(json.dumps(payload))
    raise SystemExit(0)

payload["available"] = True

total_match = re.search(r"The system has (\d+) \(", mem_out)
free_match = re.search(r"System-wide memory free percentage:\s*(\d+)%", mem_out)
page_match = re.search(r"page size of (\d+) bytes", vm_out)
free_pages_match = re.search(r"Pages free:\s+(\d+)\.", vm_out)
spec_pages_match = re.search(r"Pages speculative:\s+(\d+)\.", vm_out)

if total_match:
    payload["total_bytes"] = int(total_match.group(1))
if free_match:
    free_pct = int(free_match.group(1))
    payload["memory_pressure_free_pct"] = free_pct
    payload["memory_free_pct"] = free_pct
    payload["memory_pct_source"] = "memory_pressure -Q"
if page_match:
    page_size = int(page_match.group(1))
    free_pages = int(free_pages_match.group(1)) if free_pages_match else 0
    spec_pages = int(spec_pages_match.group(1)) if spec_pages_match else 0
    free_mb = round((free_pages * page_size) / (1024 * 1024), 1)
    spec_mb = round((spec_pages * page_size) / (1024 * 1024), 1)
    payload["vm_free_mb"] = free_mb
    payload["vm_speculative_mb"] = spec_mb
    payload["free_mb"] = free_mb
    payload["speculative_mb"] = spec_mb
    payload["vm_pages_source"] = "vm_stat"

print(json.dumps(payload))
PY
}

# ============================================================================ #
# CHECK 1: Detached Same-HEAD Worktrees
# ============================================================================ #
_check_detached_same_head() {
  TOTAL=$((TOTAL + 1))
  local main_head detached_wts count
  main_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo none)"
  detached_wts=""

  if [[ "$main_head" != "none" ]]; then
    local wt="" head=""
    while IFS= read -r line; do
      case "$line" in
        "worktree "*)  wt="${line#worktree }" ;;
        "HEAD "*)      head="${line#HEAD }" ;;
        "detached")
          if [[ "$head" == "$main_head" ]]; then
            detached_wts="${detached_wts:+$detached_wts|}$wt"
          fi
          ;;
      esac
    done < <(git -C "$REPO" worktree list --porcelain 2>/dev/null || true)
  fi

  count=0
  if [[ -n "$detached_wts" ]]; then
    count=$(echo "$detached_wts" | tr '|' '\n' | grep -c '.' || true)
  fi

  if [[ "$count" -gt 0 ]]; then
    local details_json="["
    local first=true
    while IFS='|' read -ra paths; do
      for p in "${paths[@]}"; do
        [[ -z "$p" ]] && continue
        [[ "$first" = true ]] && first=false || details_json="$details_json,"
        details_json="$details_json\"$p\""
        if [[ "$FIX_MODE" = true ]]; then
          git -C "$REPO" worktree remove "$p" --force 2>/dev/null || true
        fi
      done
    done <<< "$detached_wts"
    details_json="$details_json]"

    if [[ "$FIX_MODE" = true ]]; then
      _ok "$count detached same-HEAD worktrees (pruned)"
      PASS_COUNT=$((PASS_COUNT + 1))
      _add_check "{\"id\":\"detached_same_head\",\"category\":\"worktrees\",\"status\":\"pass\",\"count\":$count,\"details\":$details_json,\"fix_available\":true,\"fixed\":true}"
    else
      _warn "$count detached same-HEAD worktrees (run with --fix to prune)"
      _add_check "{\"id\":\"detached_same_head\",\"category\":\"worktrees\",\"status\":\"warn\",\"count\":$count,\"details\":$details_json,\"fix_available\":true}"
    fi
  else
    _ok "No detached same-HEAD worktrees"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"detached_same_head\",\"category\":\"worktrees\",\"status\":\"pass\",\"count\":0}"
  fi
}

# ============================================================================ #
# CHECK 2: Worktree Count Threshold
# ============================================================================ #
_check_worktree_count() {
  TOTAL=$((TOTAL + 1))
  local wt_count
  wt_count="$( (git -C "$REPO" worktree list 2>/dev/null || true) | wc -l | tr -d ' ' )"

  if [[ "$wt_count" -gt "$MAX_WT" ]]; then
    _warn "Worktree count: $wt_count (max: $MAX_WT)"
    _add_check "{\"id\":\"worktree_count\",\"category\":\"worktrees\",\"status\":\"warn\",\"count\":$wt_count,\"max\":$MAX_WT}"
  else
    _ok "Worktree count: $wt_count (max: $MAX_WT)"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"worktree_count\",\"category\":\"worktrees\",\"status\":\"pass\",\"count\":$wt_count,\"max\":$MAX_WT}"
  fi
}

# ============================================================================ #
# CHECK 3: Multiple Active Automations on One Authority Plan
# ============================================================================ #
_check_dual_active_automations() {
  TOTAL=$((TOTAL + 1))
  local conflicts="" plan_map=""

  if [[ -d "$AUTOMATIONS_DIR" ]]; then
    for toml in "$AUTOMATIONS_DIR"/*/automation.toml; do
      [[ -f "$toml" ]] || continue
      local st name plan_ref
      st="$(grep -o 'status = "[^"]*"' "$toml" 2>/dev/null | grep -o '"[^"]*"' | tr -d '"' || true)"
      [[ "$st" != "ACTIVE" ]] && continue
      name="$(basename "$(dirname "$toml")")"
      plan_ref="$(grep -oE '(projects/[^/]+/PLAN\.md|\.vidux/projects/[^/]+/PLAN\.md|[^[:space:]]*/PLAN\.md)' "$toml" 2>/dev/null | head -1 || true)"
      [[ -z "$plan_ref" ]] && continue
      plan_map="${plan_map}${name}|${plan_ref}\n"
    done

    if [[ -n "$plan_map" ]]; then
      conflicts="$(printf '%b' "$plan_map" | sort -t'|' -k2 | awk -F'|' '
        prev_plan!=$2 { prev_plan=$2; prev_name=$1; next }
        { print prev_name "|" $1 "|" $2; prev_name=$1 }
      ')"
    fi
  fi

  if [[ -n "$conflicts" ]]; then
    local details=""
    while IFS='|' read -r name1 name2 plan; do
      details="${details:+$details; }$name1 + $name2 -> $plan"
    done <<< "$conflicts"
    _warn "Conflicting active automations: $details"
    local escaped_details="${details//\"/\\\"}"
    _add_check "{\"id\":\"dual_active_automations\",\"category\":\"automations\",\"status\":\"warn\",\"details\":\"$escaped_details\"}"
  else
    _ok "No conflicting active automations"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"dual_active_automations\",\"category\":\"automations\",\"status\":\"pass\"}"
  fi
}

# ============================================================================ #
# CHECK 4: Orphan Automation Directories
# ============================================================================ #
_check_orphan_automations() {
  TOTAL=$((TOTAL + 1))
  local orphans="" count=0
  local removed="" removed_count=0
  local retained="" retained_count=0

  if [[ -d "$AUTOMATIONS_DIR" ]]; then
    for d in "$AUTOMATIONS_DIR"/*/; do
      [[ -d "$d" ]] || continue
      if [[ -f "$d/memory.md" ]] && [[ ! -f "$d/automation.toml" ]]; then
        local name
        name="$(basename "$d")"
        orphans="${orphans:+$orphans|}$name"
        count=$((count + 1))
        if [[ "$FIX_MODE" = true ]]; then
          local lines
          lines="$(wc -l < "$d/memory.md" | tr -d ' ')"
          if [[ "$lines" -le 5 ]]; then
            rm -rf "$d"
            removed="${removed:+$removed|}$name"
            removed_count=$((removed_count + 1))
          else
            retained="${retained:+$retained|}$name"
            retained_count=$((retained_count + 1))
          fi
        fi
      fi
    done
  fi

  if [[ "$count" -gt 0 ]]; then
    if [[ "$FIX_MODE" = true ]]; then
      local removed_json retained_json
      removed_json="$(_pipe_list_json "$removed")"
      retained_json="$(_pipe_list_json "$retained")"
      if [[ "$retained_count" -gt 0 ]]; then
        _warn "$retained_count orphan automation directories retained after --fix: $(echo "$retained" | tr '|' ', ')"
        _add_check "{\"id\":\"orphan_automations\",\"category\":\"automations\",\"status\":\"warn\",\"count\":$retained_count,\"details\":$retained_json,\"fix_available\":true,\"fixed\":false,\"fixed_count\":$removed_count,\"retained_count\":$retained_count,\"removed\":$removed_json}"
      else
        _ok "$count orphan automation directories (cleaned)"
        PASS_COUNT=$((PASS_COUNT + 1))
        _add_check "{\"id\":\"orphan_automations\",\"category\":\"automations\",\"status\":\"pass\",\"count\":0,\"details\":[],\"fix_available\":true,\"fixed\":true,\"fixed_count\":$removed_count,\"retained_count\":0,\"removed\":$removed_json}"
      fi
    else
      local details_json
      details_json="$(_pipe_list_json "$orphans")"
      _warn "$count orphan automation directories: $(echo "$orphans" | tr '|' ', ')"
      _add_check "{\"id\":\"orphan_automations\",\"category\":\"automations\",\"status\":\"warn\",\"count\":$count,\"details\":$details_json,\"fix_available\":true}"
    fi
  else
    _ok "No orphan automation directories"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"orphan_automations\",\"category\":\"automations\",\"status\":\"pass\",\"count\":0}"
  fi
}

# ============================================================================ #
# CHECK 4b: Reduce Harness Scope Drift
# ============================================================================ #
_check_reduce_harness_scope() {
  TOTAL=$((TOTAL + 1))
  local count=0 details_json="["
  local first=true

  if [[ ! -d "$AUTOMATIONS_DIR" ]]; then
    _ok "No automations directory available for reduce-harness audit"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"reduce_harness_scope\",\"category\":\"automations\",\"status\":\"pass\",\"count\":0}"
    return
  fi

  for toml in "$AUTOMATIONS_DIR"/*/automation.toml; do
    [[ -f "$toml" ]] || continue
    local scan_json status kind issue_count
    scan_json="$(_reduce_harness_prompt_scan "$toml" 2>/dev/null || echo '{}')"
    status="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' <<< "$scan_json" 2>/dev/null || true)"
    kind="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("kind",""))' <<< "$scan_json" 2>/dev/null || true)"
    [[ "$status" != "ACTIVE" ]] && continue
    [[ "$kind" != "cron" ]] && continue
    issue_count="$(python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("issues",[])))' <<< "$scan_json" 2>/dev/null || echo 0)"
    [[ "$issue_count" -eq 0 ]] && continue

    count=$((count + 1))
    [[ "$first" = true ]] && first=false || details_json="$details_json,"
    details_json="$details_json$scan_json"
  done
  details_json="$details_json]"

  if [[ "$count" -gt 0 ]]; then
    local summary
    summary="$(python3 - <<'PY' "$details_json"
import json
import sys

details = json.loads(sys.argv[1])
bits = []
for item in details:
    aid = item.get("automation_id") or "unknown"
    deep = ", ".join(item.get("matched_deep_markers") or [])
    issues = ", ".join(item.get("issues") or [])
    bits.append(f"{aid} ({issues}; deep={deep})")
print("; ".join(bits))
PY
)"
    _warn "Reduce harness scope drift: $summary"
    _add_check "{\"id\":\"reduce_harness_scope\",\"category\":\"automations\",\"status\":\"warn\",\"count\":$count,\"details\":$details_json}"
  else
    _ok "No reduce harness prompts mixing scheduled checks with dispatch work"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"reduce_harness_scope\",\"category\":\"automations\",\"status\":\"pass\",\"count\":0}"
  fi
}

# ============================================================================ #
# CHECK 4c: Stalled Active Automation Rows
# ============================================================================ #
_check_stalled_active_automation_rows() {
  TOTAL=$((TOTAL + 1))
  local snapshot available count grace_minutes db_path details_json summary
  snapshot="$(_stalled_automation_rows_json "$AUTOMATION_DB" "$AUTOMATIONS_DIR")"
  available="$(python3 -c "import json,sys; print('1' if json.load(sys.stdin).get('available') else '0')" <<< "$snapshot")"

  if [[ "$available" != "1" ]]; then
    db_path="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('db_path',''))" <<< "$snapshot")"
    _ok "Automation DB unavailable for stalled-row audit ($db_path)"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"stalled_active_automation_rows\",\"category\":\"automations\",\"status\":\"pass\",\"available\":false,\"db_path\":\"$db_path\",\"count\":0}"
    return
  fi

  count="$(python3 -c "import json,sys; print(len(json.load(sys.stdin).get('rows', [])))" <<< "$snapshot")"
  grace_minutes="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('grace_minutes', 10))" <<< "$snapshot")"
  db_path="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('db_path',''))" <<< "$snapshot")"
  details_json="$(python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin).get('rows', [])))" <<< "$snapshot")"

  if [[ "$count" -gt 0 ]]; then
    summary="$(python3 - <<'PY' "$details_json"
import json
import sys

details = json.loads(sys.argv[1])
bits = []
for item in details:
    mode = "repo" if item.get("repo_backed") else "db-only"
    overdue = item.get("overdue_minutes")
    overdue_txt = "no next_run_at" if overdue is None else f"{overdue}m overdue"
    bits.append(f"{item.get('id')} ({mode}, {overdue_txt})")
print("; ".join(bits))
PY
)"
    _warn "Active scheduler rows with zero runs: $summary"
    _add_check "{\"id\":\"stalled_active_automation_rows\",\"category\":\"automations\",\"status\":\"warn\",\"available\":true,\"db_path\":\"$db_path\",\"grace_minutes\":$grace_minutes,\"count\":$count,\"details\":$details_json}"
  else
    _ok "No active scheduler rows are overdue with zero runs"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"stalled_active_automation_rows\",\"category\":\"automations\",\"status\":\"pass\",\"available\":true,\"db_path\":\"$db_path\",\"grace_minutes\":$grace_minutes,\"count\":0,\"details\":[]}"
  fi
}

# ============================================================================ #
# CHECK 5: Browser Process Pressure / Zombie Candidates
# ============================================================================ #
_check_browser_process_pressure() {
  TOTAL=$((TOTAL + 1))
  local snapshot browser_count controller_count orphan_count rss_mb profile_count stale_controller_count status stale_minutes
  snapshot="$(_browser_snapshot_json)"
  browser_count="$(python3 -c "import json,sys; print(json.load(sys.stdin)['browser_count'])" <<< "$snapshot")"
  controller_count="$(python3 -c "import json,sys; print(json.load(sys.stdin)['controller_count'])" <<< "$snapshot")"
  orphan_count="$(python3 -c "import json,sys; print(json.load(sys.stdin)['orphan_count'])" <<< "$snapshot")"
  rss_mb="$(python3 -c "import json,sys; print(json.load(sys.stdin)['rss_mb'])" <<< "$snapshot")"
  profile_count="$(python3 -c "import json,sys; print(len(json.load(sys.stdin)['profiles']))" <<< "$snapshot")"
  stale_controller_count="$(python3 -c "import json,sys; print(json.load(sys.stdin)['stale_controller_count'])" <<< "$snapshot")"
  stale_minutes="$(python3 -c "import json,sys; print(json.load(sys.stdin)['stale_session_minutes'])" <<< "$snapshot")"
  status="pass"

  if [[ "$orphan_count" -gt 0 ]] || [[ "$browser_count" -gt "$MAX_BROWSER_PROCS" ]] || [[ "$stale_controller_count" -gt 0 ]]; then
    status="warn"
  fi

  if [[ "$status" = "warn" ]]; then
    local summary="browser candidates: $browser_count (max: $MAX_BROWSER_PROCS), controllers: $controller_count, orphan candidates: $orphan_count, rss: ${rss_mb} MB"
    if [[ "$profile_count" -gt 0 ]]; then
      summary="$summary, profiles: $profile_count"
    fi
    if [[ "$stale_controller_count" -gt 0 ]]; then
      summary="$summary, stale controller sessions: $stale_controller_count (>${stale_minutes}m)"
    fi
    _warn "$summary"
    _add_check "{\"id\":\"browser_process_pressure\",\"category\":\"browsers\",\"status\":\"warn\",\"count\":$browser_count,\"max\":$MAX_BROWSER_PROCS,\"controller_count\":$controller_count,\"orphan_count\":$orphan_count,\"rss_mb\":$rss_mb,\"profile_count\":$profile_count,\"profiles\":$(python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['profiles']))" <<< "$snapshot"),\"stale_session_minutes\":$stale_minutes,\"stale_controller_count\":$stale_controller_count,\"stale_controllers\":$(python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['stale_controllers']))" <<< "$snapshot"),\"orphans\":$(python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['orphans']))" <<< "$snapshot")}"
  else
    _ok "Browser candidates: $browser_count (max: $MAX_BROWSER_PROCS), orphan candidates: 0"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"browser_process_pressure\",\"category\":\"browsers\",\"status\":\"pass\",\"count\":$browser_count,\"max\":$MAX_BROWSER_PROCS,\"controller_count\":$controller_count,\"orphan_count\":0,\"rss_mb\":$rss_mb,\"profile_count\":$profile_count,\"profiles\":$(python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['profiles']))" <<< "$snapshot"),\"stale_session_minutes\":$stale_minutes,\"stale_controller_count\":0,\"stale_controllers\":[],\"orphans\":[]}"
  fi
}

# ============================================================================ #
# CHECK 6: Codex Thread Pressure
# ============================================================================ #
_check_codex_thread_pressure() {
  TOTAL=$((TOTAL + 1))
  local snapshot available active_threads active_automation_threads avg_title avg_auto_title max_title status state_db
  snapshot="$(_codex_thread_snapshot_json)"
  available="$(python3 -c "import json,sys; print('1' if json.load(sys.stdin).get('available') else '0')" <<< "$snapshot")"
  state_db="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('state_db',''))" <<< "$snapshot")"

  if [[ "$available" != "1" ]]; then
    _ok "Codex thread state unavailable (no state db at $state_db)"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"codex_thread_pressure\",\"category\":\"codex\",\"status\":\"pass\",\"available\":false,\"state_db\":\"$state_db\"}"
    return
  fi

  active_threads="$(python3 -c "import json,sys; print(json.load(sys.stdin)['active_threads'])" <<< "$snapshot")"
  active_automation_threads="$(python3 -c "import json,sys; print(json.load(sys.stdin)['active_automation_threads'])" <<< "$snapshot")"
  avg_title="$(python3 -c "import json,sys; print(json.load(sys.stdin)['avg_active_title_len'])" <<< "$snapshot")"
  avg_auto_title="$(python3 -c "import json,sys; print(json.load(sys.stdin)['avg_active_automation_title_len'])" <<< "$snapshot")"
  max_title="$(python3 -c "import json,sys; print(json.load(sys.stdin)['max_active_title_len'])" <<< "$snapshot")"
  status="pass"

  if [[ "$active_threads" -gt "$MAX_CODEX_ACTIVE_THREADS" ]] || \
     [[ "$active_automation_threads" -gt "$MAX_CODEX_ACTIVE_AUTOMATION_THREADS" ]] || \
     python3 -c "import sys; raise SystemExit(0 if float(sys.argv[1]) > float(sys.argv[2]) else 1)" "$avg_auto_title" "$MAX_CODEX_AVG_TITLE_CHARS"
  then
    status="warn"
  fi

  if [[ "$status" = "warn" ]]; then
    _warn "Codex active threads: $active_threads (max: $MAX_CODEX_ACTIVE_THREADS), automation threads: $active_automation_threads (max: $MAX_CODEX_ACTIVE_AUTOMATION_THREADS), avg automation title: ${avg_auto_title} chars"
    _add_check "{\"id\":\"codex_thread_pressure\",\"category\":\"codex\",\"status\":\"warn\",\"available\":true,\"state_db\":\"$state_db\",\"active_threads\":$active_threads,\"max_active_threads\":$MAX_CODEX_ACTIVE_THREADS,\"active_automation_threads\":$active_automation_threads,\"max_active_automation_threads\":$MAX_CODEX_ACTIVE_AUTOMATION_THREADS,\"avg_active_title_len\":$avg_title,\"avg_active_automation_title_len\":$avg_auto_title,\"max_avg_title_chars\":$MAX_CODEX_AVG_TITLE_CHARS,\"max_active_title_len\":$max_title}"
  else
    _ok "Codex active threads: $active_threads (max: $MAX_CODEX_ACTIVE_THREADS), automation threads: $active_automation_threads"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"codex_thread_pressure\",\"category\":\"codex\",\"status\":\"pass\",\"available\":true,\"state_db\":\"$state_db\",\"active_threads\":$active_threads,\"max_active_threads\":$MAX_CODEX_ACTIVE_THREADS,\"active_automation_threads\":$active_automation_threads,\"max_active_automation_threads\":$MAX_CODEX_ACTIVE_AUTOMATION_THREADS,\"avg_active_title_len\":$avg_title,\"avg_active_automation_title_len\":$avg_auto_title,\"max_avg_title_chars\":$MAX_CODEX_AVG_TITLE_CHARS,\"max_active_title_len\":$max_title}"
  fi
}

# ============================================================================ #
# CHECK 7: System Memory Pressure
# ============================================================================ #
_check_system_memory_pressure() {
  TOTAL=$((TOTAL + 1))
  local snapshot available free_pct free_mb spec_mb total_bytes status
  snapshot="$(_memory_pressure_snapshot_json)"
  available="$(python3 -c "import json,sys; print('1' if json.load(sys.stdin).get('available') else '0')" <<< "$snapshot")"

  if [[ "$available" != "1" ]]; then
    _ok "System memory pressure unavailable on this host"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"system_memory_pressure\",\"category\":\"system\",\"status\":\"pass\",\"available\":false}"
    return
  fi

  free_pct="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('memory_pressure_free_pct', 0))" <<< "$snapshot")"
  free_mb="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('vm_free_mb', 0))" <<< "$snapshot")"
  spec_mb="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('vm_speculative_mb', 0))" <<< "$snapshot")"
  total_bytes="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('total_bytes', 0))" <<< "$snapshot")"
  status="pass"

  if [[ "$free_pct" -lt "$MIN_SYSTEM_MEMORY_FREE_PCT" ]]; then
    status="warn"
  fi

  if [[ "$status" = "warn" ]]; then
    _warn "System memory_pressure free: ${free_pct}% (min: ${MIN_SYSTEM_MEMORY_FREE_PCT}%), vm_stat free: ${free_mb} MB, speculative: ${spec_mb} MB"
    _add_check "{\"id\":\"system_memory_pressure\",\"category\":\"system\",\"status\":\"warn\",\"available\":true,\"memory_pressure_free_pct\":$free_pct,\"memory_free_pct\":$free_pct,\"min_memory_free_pct\":$MIN_SYSTEM_MEMORY_FREE_PCT,\"memory_pct_source\":\"memory_pressure -Q\",\"vm_free_mb\":$free_mb,\"vm_speculative_mb\":$spec_mb,\"free_mb\":$free_mb,\"speculative_mb\":$spec_mb,\"vm_pages_source\":\"vm_stat\",\"total_bytes\":$total_bytes}"
  else
    _ok "System memory_pressure free: ${free_pct}% (min: ${MIN_SYSTEM_MEMORY_FREE_PCT}%)"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"system_memory_pressure\",\"category\":\"system\",\"status\":\"pass\",\"available\":true,\"memory_pressure_free_pct\":$free_pct,\"memory_free_pct\":$free_pct,\"min_memory_free_pct\":$MIN_SYSTEM_MEMORY_FREE_PCT,\"memory_pct_source\":\"memory_pressure -Q\",\"vm_free_mb\":$free_mb,\"vm_speculative_mb\":$spec_mb,\"free_mb\":$free_mb,\"speculative_mb\":$spec_mb,\"vm_pages_source\":\"vm_stat\",\"total_bytes\":$total_bytes}"
  fi
}

# ============================================================================ #
# CHECK 8: Stale [in_progress] Tasks Across Projects
# ============================================================================ #
_check_stale_in_progress() {
  TOTAL=$((TOTAL + 1))
  local stale="" count=0

  # Calculate threshold date (macOS vs GNU date)
  local threshold_date
  threshold_date="$(date -v-"${STALE_DAYS}"d +%Y-%m-%d 2>/dev/null || date -d "${STALE_DAYS} days ago" +%Y-%m-%d 2>/dev/null || echo 2000-01-01)"

  if [[ -d "$PROJECTS_DIR" ]]; then
    for plan in "$PROJECTS_DIR"/*/PLAN.md; do
      [[ -f "$plan" ]] || continue
      local has_ip
      has_ip="$(grep -cE '^\- \[in_progress\]' "$plan" 2>/dev/null || true)"
      [[ "$has_ip" -eq 0 ]] && continue

      local last_date
      last_date="$(awk '/^## Progress/{found=1; next} found && /^## /{found=0} found{print}' "$plan" \
        | grep -oE '\[20[0-9]{2}-[0-9]{2}-[0-9]{2}\]' | sort -r | head -1 | tr -d '[]' || true)"

      if [[ -z "$last_date" ]] || [[ "$last_date" < "$threshold_date" ]]; then
        local project
        project="$(basename "$(dirname "$plan")")"
        stale="${stale:+$stale|}${project}:${has_ip}:${last_date:-never}"
        count=$((count + 1))
      fi
    done
  fi

  if [[ "$count" -gt 0 ]]; then
    local summary=""
    local details_json="["
    local first=true
    while IFS='|' read -ra entries; do
      for entry in "${entries[@]}"; do
        [[ -z "$entry" ]] && continue
        IFS=':' read -r proj ip_count last <<< "$entry"
        summary="${summary:+$summary, }$proj (last: $last)"
        [[ "$first" = true ]] && first=false || details_json="$details_json,"
        local last_json; [[ "$last" = "never" ]] && last_json="null" || last_json="\"$last\""
        details_json="$details_json{\"project\":\"$proj\",\"in_progress_count\":$ip_count,\"last_progress\":$last_json}"
      done
    done <<< "$stale"
    details_json="$details_json]"

    _warn "$count stale [in_progress] projects: $summary"
    _add_check "{\"id\":\"stale_in_progress\",\"category\":\"plans\",\"status\":\"warn\",\"count\":$count,\"details\":$details_json}"
  else
    _ok "No stale [in_progress] tasks"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"stale_in_progress\",\"category\":\"plans\",\"status\":\"pass\",\"count\":0}"
  fi
}

# ============================================================================ #
# CHECK 9: Missing ## Active Worktrees in Plans with Worktree Automations
# ============================================================================ #
_check_missing_active_worktrees() {
  TOTAL=$((TOTAL + 1))
  local missing="" count=0

  if [[ -d "$AUTOMATIONS_DIR" ]]; then
    for toml in "$AUTOMATIONS_DIR"/*/automation.toml; do
      [[ -f "$toml" ]] || continue
      local exec_env st plan_ref plan_path
      exec_env="$(grep -o 'execution_environment = "[^"]*"' "$toml" 2>/dev/null | grep -o '"[^"]*"' | tr -d '"' || true)"
      [[ "$exec_env" != "worktree" ]] && continue
      st="$(grep -o 'status = "[^"]*"' "$toml" 2>/dev/null | grep -o '"[^"]*"' | tr -d '"' || true)"
      [[ "$st" != "ACTIVE" ]] && continue
      plan_ref="$(grep -oE '(projects/[^/]+/PLAN\.md|\.vidux/projects/[^/]+/PLAN\.md|[^[:space:]]*/PLAN\.md)' "$toml" 2>/dev/null | head -1 || true)"
      [[ -z "$plan_ref" ]] && continue
      # Resolve plan path: absolute paths stay, relative paths resolve from REPO
      if [[ "$plan_ref" == /* ]]; then
        plan_path="$plan_ref"
      elif [[ "$plan_ref" == *".vidux/projects/"* ]]; then
        plan_path="$HOME/${plan_ref#*/}"
      else
        plan_path="$REPO/$plan_ref"
      fi
      [[ ! -f "$plan_path" ]] && continue
      if ! grep -q '^## Active Worktrees' "$plan_path" 2>/dev/null; then
        local auto_name
        auto_name="$(basename "$(dirname "$toml")")"
        missing="${missing:+$missing|}$auto_name -> $plan_ref"
        count=$((count + 1))
      fi
    done
  fi

  if [[ "$count" -gt 0 ]]; then
    _warn "$count plans missing ## Active Worktrees section"
    _add_check "{\"id\":\"missing_active_worktrees\",\"category\":\"plans\",\"status\":\"warn\",\"count\":$count}"
  else
    _ok "No missing Active Worktrees sections"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"missing_active_worktrees\",\"category\":\"plans\",\"status\":\"pass\"}"
  fi
}

# ============================================================================ #
# CHECK 10: Plan Merge Conflict Markers
# ============================================================================ #
_check_plan_merge_conflicts() {
  TOTAL=$((TOTAL + 1))
  local conflicts=""

  if [[ -d "$PROJECTS_DIR" ]]; then
    conflicts="$(grep -rlE '^(<{7}|>{7}|={7})' "$PROJECTS_DIR"/*/PLAN.md 2>/dev/null || true)"
  fi

  if [[ -n "$conflicts" ]]; then
    local details_json="["
    local first=true
    while IFS= read -r f; do
      [[ -z "$f" ]] && continue
      [[ "$first" = true ]] && first=false || details_json="$details_json,"
      details_json="$details_json\"$f\""
    done <<< "$conflicts"
    details_json="$details_json]"

    BLOCK=true
    _fail "Merge conflicts in project plans: $conflicts"
    _add_check "{\"id\":\"plan_merge_conflicts\",\"category\":\"plans\",\"status\":\"block\",\"details\":$details_json}"
  else
    _ok "No merge conflicts in project plans"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"plan_merge_conflicts\",\"category\":\"plans\",\"status\":\"pass\"}"
  fi
}

# ============================================================================ #
# CHECK 11: Bimodal Runtime Quality (automation cycles)
# ============================================================================ #
_check_bimodal_runtime() {
  TOTAL=$((TOTAL + 1))
  local dead_zone="" count=0

  # Parse Progress entries across all project PLANs for cycle timestamps.
  # Good automations: <2 min (quick check) or >15 min (deep run).
  # Dead zone: 3-8 min = "stick-rubbing" (no meaningful work).
  if [[ -d "$PROJECTS_DIR" ]]; then
    for plan in "$PROJECTS_DIR"/*/PLAN.md; do
      [[ -f "$plan" ]] || continue
      local project
      project="$(basename "$(dirname "$plan")")"

      # Extract timestamps from Progress section and compute durations
      # Format: - [YYYY-MM-DD] Cycle N: ... or - [YYYY-MM-DD HH:MM] Cycle N: ...
      local timestamps durations dead_count total_cycles median_min
      timestamps="$(awk '/^## Progress/{found=1; next} found && /^## /{found=0} found{print}' "$plan" \
        | grep -oE '\[20[0-9]{2}-[0-9]{2}-[0-9]{2}( [0-9]{2}:[0-9]{2})?\]' | tr -d '[]' | sort || true)"

      [[ -z "$timestamps" ]] && continue

      # Use git log on the plan file for more accurate per-cycle commit timestamps
      durations="$(git -C "$REPO" log --format='%at' -- "$plan" 2>/dev/null | sort -n | awk '
        NR > 1 {
          delta = $1 - prev
          if (delta > 30 && delta < 7200) print int(delta / 60)
        }
        { prev = $1 }
      ' || true)"

      [[ -z "$durations" ]] && continue

      total_cycles="$(printf '%s\n' "$durations" | wc -l | tr -d ' ')"
      [[ "$total_cycles" -lt 2 ]] && continue

      # Count runs in dead zone (3-8 minutes)
      dead_count="$(printf '%s\n' "$durations" | awk '$1 >= 3 && $1 <= 8' | wc -l | tr -d ' ')"

      # Calculate median
      median_min="$(printf '%s\n' "$durations" | sort -n | awk -v n="$total_cycles" '
        NR == int((n+1)/2) { print $1 }
      ')"

      local dead_pct=0
      [[ "$total_cycles" -gt 0 ]] && dead_pct=$((dead_count * 100 / total_cycles))

      # Flag if >30% of runs are in dead zone
      if [[ "$dead_pct" -gt 30 ]]; then
        dead_zone="${dead_zone:+$dead_zone|}${project}:${dead_count}/${total_cycles}:${dead_pct}%:median=${median_min}m"
        count=$((count + 1))
      fi
    done
  fi

  if [[ "$count" -gt 0 ]]; then
    local summary=""
    local details_json="["
    local first=true
    while IFS='|' read -ra entries; do
      for entry in "${entries[@]}"; do
        [[ -z "$entry" ]] && continue
        IFS=':' read -r proj ratio pct med <<< "$entry"
        summary="${summary:+$summary, }$proj ($ratio dead-zone runs, $pct, $med)"
        [[ "$first" = true ]] && first=false || details_json="$details_json,"
        details_json="$details_json{\"project\":\"$proj\",\"dead_zone_ratio\":\"$ratio\",\"dead_zone_pct\":\"$pct\",\"median\":\"$med\"}"
      done
    done <<< "$dead_zone"
    details_json="$details_json]"

    _warn "Bimodal dead zone: $summary"
    _add_check "{\"id\":\"bimodal_runtime\",\"category\":\"quality\",\"status\":\"warn\",\"count\":$count,\"details\":$details_json}"
  else
    _ok "No automation runs stuck in 3-8 min dead zone"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"bimodal_runtime\",\"category\":\"quality\",\"status\":\"pass\",\"count\":0}"
  fi
}

# CHECK 12: Cadence-Runtime Mismatch
# ============================================================================ #
_check_cadence_runtime() {
  TOTAL=$((TOTAL + 1))
  local mismatches="" count=0

  # Read active automations from Codex DB
  local CODEX_DB="$HOME/.codex/sqlite/codex-dev.db"
  if [[ -f "$CODEX_DB" ]]; then
    local rows
    rows="$(sqlite3 "$CODEX_DB" "SELECT id, rrule FROM automations WHERE status='ACTIVE'" 2>/dev/null || true)"
    [[ -z "$rows" ]] && { _ok "No active automations to check cadence"; PASS_COUNT=$((PASS_COUNT + 1)); _add_check "{\"id\":\"cadence_runtime\",\"category\":\"quality\",\"status\":\"pass\",\"count\":0}"; return; }

    while IFS='|' read -r aid rrule; do
      [[ -z "$aid" ]] && continue
      # Extract BYMINUTE count to determine fires-per-hour
      local bymin_count=1
      if [[ "$rrule" =~ BYMINUTE=([0-9,]+) ]]; then
        bymin_count="$(echo "${BASH_REMATCH[1]}" | tr ',' '\n' | wc -l | tr -d ' ')"
      fi
      # Check memory files for runtime clues
      local runtime_min=0
      local mem="$HOME/.codex/automations/$aid/memory.md"
      if [[ -f "$mem" ]]; then
        # Extract runtime from patterns like "Runtime: ~40m" or "Run time: ~63m"
        local found_rt
        found_rt="$(grep -oiE '(run ?time|runtime):? ~?([0-9]+)m' "$mem" 2>/dev/null | grep -oE '[0-9]+' | tail -1 || true)"
        [[ -n "$found_rt" && "$found_rt" -gt "$runtime_min" ]] && runtime_min="$found_rt"
      fi
      # Flag if fires-per-hour > 1 and runtime > cadence interval
      local cadence_min=$((60 / bymin_count))
      if [[ "$bymin_count" -gt 1 && "$runtime_min" -gt "$cadence_min" ]]; then
        mismatches="${mismatches:+$mismatches, }$aid (${runtime_min}m runtime, ${cadence_min}m cadence, ${bymin_count}x/hr)"
        count=$((count + 1))
      fi
    done <<< "$rows"
  fi

  if [[ "$count" -gt 0 ]]; then
    _warn "Cadence-runtime mismatch: $mismatches"
    _add_check "{\"id\":\"cadence_runtime\",\"category\":\"quality\",\"status\":\"warn\",\"count\":$count,\"details\":\"$(json_escape "$mismatches")\"}"
  else
    _ok "All automation cadences match observed runtimes"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"cadence_runtime\",\"category\":\"quality\",\"status\":\"pass\",\"count\":0}"
  fi
}

# ScheduleWakeup-vs-CronCreate doctrine drift check.
#
# Honesty note: vidux cannot observe a live session's ScheduleWakeup tool
# calls -- that state lives entirely inside a running Claude Code session and
# is never persisted anywhere this repo can read. A "doctor check that flags
# ScheduleWakeup misuse" would be a fake gate pretending to see something it
# can't. What IS mechanizable, and what this checks: the two places the
# CronCreate-over-ScheduleWakeup-for-10+-fires rule is documented
# (guides/automation.md and docs/fleet/claude-lifecycle.md's troubleshooting
# table) still state it. This catches silent doctrine drift/deletion, not a
# live violation -- see guides/recipes.md Recipe 12 note and CHANGELOG for the
# fuller reasoning.
_check_schedulewakeup_doctrine_intact() {
  TOTAL=$((TOTAL + 1))
  local missing=""
  local automation_doc="$VIDUX_ROOT/guides/automation.md"
  local lifecycle_doc="$VIDUX_ROOT/docs/fleet/claude-lifecycle.md"

  # A deleted/renamed doc must flag too -- `-f` short-circuiting the check
  # means a whole-file deletion silently read as "doctrine intact" (adversarial
  # review, 2026-07-08), the same fail-open class as the plan-guard corrupt-
  # sidecar bug this facelift already closed.
  if [[ ! -f "$automation_doc" ]] || ! grep -qE 'CronCreate.{0,10}over.{0,10}ScheduleWakeup' "$automation_doc"; then
    missing="${missing:+$missing, }guides/automation.md"
  fi
  if [[ ! -f "$lifecycle_doc" ]] || ! grep -qE 'CronCreate.{0,10}over.{0,10}ScheduleWakeup' "$lifecycle_doc"; then
    missing="${missing:+$missing, }docs/fleet/claude-lifecycle.md"
  fi

  if [[ -n "$missing" ]]; then
    _warn "ScheduleWakeup-vs-CronCreate doctrine missing/reworded in: $missing"
    _add_check "{\"id\":\"schedulewakeup_doctrine_intact\",\"category\":\"quality\",\"status\":\"warn\",\"details\":\"$(json_escape "$missing")\"}"
  else
    _ok "ScheduleWakeup-vs-CronCreate doctrine intact in both canonical locations"
    PASS_COUNT=$((PASS_COUNT + 1))
    _add_check "{\"id\":\"schedulewakeup_doctrine_intact\",\"category\":\"quality\",\"status\":\"pass\"}"
  fi
}

# ============================================================================ #
# MAIN
# ============================================================================ #
if [[ "$JSON_MODE" = false ]]; then
  echo -e "\n${BOLD}  Vidux Doctor (Runtime)${RESET}"
  echo "  Version: $VERSION"
  echo -e "  Host:    $HOST\n"
  echo -e "${BOLD}== Worktrees ==${RESET}"
fi

_check_detached_same_head
_check_worktree_count

if [[ "$JSON_MODE" = false ]]; then
  echo -e "\n${BOLD}== Automations ==${RESET}"
fi

_check_dual_active_automations
_check_orphan_automations
_check_reduce_harness_scope
_check_stalled_active_automation_rows
_check_browser_process_pressure

if [[ "$JSON_MODE" = false ]]; then
  echo -e "\n${BOLD}== Codex ==${RESET}"
fi

_check_codex_thread_pressure

if [[ "$JSON_MODE" = false ]]; then
  echo -e "\n${BOLD}== System ==${RESET}"
fi

_check_system_memory_pressure

if [[ "$JSON_MODE" = false ]]; then
  echo -e "\n${BOLD}== Plans ==${RESET}"
fi

_check_stale_in_progress
_check_missing_active_worktrees
_check_plan_merge_conflicts

if [[ "$JSON_MODE" = false ]]; then
  echo -e "\n${BOLD}== Quality ==${RESET}"
fi

_check_bimodal_runtime
_check_cadence_runtime
_check_schedulewakeup_doctrine_intact

# --- summary ---------------------------------------------------------------- #
WARN_COUNT=$((TOTAL - PASS_COUNT))

if [[ "$JSON_MODE" = true ]]; then
  python3 -c "
import json, sys
checks = []
for line in open('$CHECKS_FILE'):
    line = line.strip()
    if line:
        checks.append(json.loads(line))
out = {
    'version': '$VERSION',
    'host': '$HOST',
    'timestamp': '$TIMESTAMP',
    'pass': $PASS_COUNT,
    'total': $TOTAL,
    'checks': checks
}
json.dump(out, sys.stdout, indent=2)
print()
"
else
  echo ""
  if [[ "$BLOCK" = true ]]; then
    echo -e "  ${RED}BLOCK${RESET} $PASS_COUNT/$TOTAL checks pass (merge conflicts found)"
  elif [[ "$WARN_COUNT" -gt 0 ]]; then
    echo -e "  ${YELLOW}WARN${RESET}  $PASS_COUNT/$TOTAL checks pass ($WARN_COUNT warnings)"
  else
    echo -e "  ${GREEN}PASS${RESET}  $TOTAL/$TOTAL checks pass"
  fi
  echo ""
fi

# Exit code: 1 for blocks, 0 otherwise
[[ "$BLOCK" = true ]] && exit 1
exit 0
