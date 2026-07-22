#!/usr/bin/env bash
# ledger-query.sh — Fleet analysis queries against the agent ledger
# Source this file; do not execute directly.
#
# Provides fleet-health analysis functions for vidux-manager:
#   ledger_bimodal_distribution()  — classify runs into quick/deep/mid buckets
#   ledger_automation_runs()       — per-automation run stats
#   ledger_handoff_gaps()          — detect radar findings not picked up by writers
#   ledger_fleet_health()          — aggregate fleet health report
#   ledger_recent_activity()       — recent activity summary for a repo/project
#   ledger_conflict_check()        — detect concurrent work on same files
#
# All functions output JSON. All are no-ops returning empty JSON if ledger unavailable.
# Requires jq for meaningful output.

# Source config if not already loaded
_QUERY_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./scripts/lib/ledger-config.sh
# shellcheck disable=SC1091
source "${_QUERY_SCRIPT_DIR}/ledger-config.sh"

# Guard against double-sourcing
[[ -n "${_VIDUX_LEDGER_QUERY_LOADED:-}" ]] && return 0
_VIDUX_LEDGER_QUERY_LOADED=1

# --- Bimodal Distribution ------------------------------------------------- #
# Classifies automation runs by duration into bimodal buckets.
# Quick (<2 min): healthy checkpoint-and-exit
# Deep (>15 min): healthy full e2e work
# Mid (3-8 min): stuck in the middle — investigate
# Normal (2-3 min or 8-15 min): acceptable but not ideal
#
# Uses ledger timestamps: consecutive stop events from the same automation_id
# are used to estimate run duration. Vidux loop events (vidux_loop_start/end)
# provide exact durations when available.
#
# Args: [REPO] [HOURS] (defaults: all repos, 24h)
# Output: JSON object with distribution counts and per-automation breakdown
ledger_bimodal_distribution() {
  local repo="${1:-}" hours="${2:-24}"
  ledger_available || { echo '{"error":"ledger_unavailable"}'; return; }
  command -v jq &>/dev/null || { echo '{"error":"jq_not_installed"}'; return; }

  jq -s -c --arg repo "$repo" --arg hours "$hours" '
    def hours_to_seconds:
      ($hours | tonumber? // 24) * 3600;

    def ts_epoch:
      (.ts // "" | fromdateiso8601?);

    # Filter by repo and event type first (no time-window yet).
    [.[] | select(
      ($repo == "" or .repo == $repo) and
      ((.automation_id // "") != "") and
      ((.event // "") == "stop" or (.event // "") == "live" or
       (.event // "") == "vidux_loop_start" or (.event // "") == "vidux_loop_end")
    )] as $base |

    # Anchor the time window to the newest ledger event so offline fixtures
    # and contract tests stay stable without relying on wall-clock time.
    ($base | map(ts_epoch) | map(select(. != null)) | max // null) as $max_epoch |
    ($max_epoch // 0) as $anchor_epoch |
    ($anchor_epoch - hours_to_seconds) as $cutoff_epoch |
    [$base[] | select((ts_epoch // 0) >= $cutoff_epoch)] |

    # Group by automation_id, then by agent_id to recover one run per automation invocation.
    group_by(.automation_id) |

    # For each automation, compute run durations from its per-agent event streams.
    map(
      (.[0].automation_name // .[0].automation_id // "unknown") as $name |
      (.[0].automation_id // "unknown") as $id |

      group_by(.agent_id // .eid // .ts) |
      map(
        sort_by(.ts) as $run |
        (($run | map(select((.event // "") == "vidux_loop_start")) | map(.ts) | first) // "") as $start_exact |
        (($run | map(select((.event // "") == "vidux_loop_end")) | map(.ts) | last) // "") as $end_exact |
        ($run[0].ts // "") as $start_fallback |
        ($run[-1].ts // "") as $end_fallback |
        (
          if ($start_exact != "" and $end_exact != "") then [$start_exact, $end_exact]
          elif ($run | length) >= 2 then [$start_fallback, $end_fallback]
          else empty
          end
        ) |
        .[0] as $start_ts |
        .[1] as $end_ts |
        (($end_ts | split("T")[1] | split("Z")[0] | split(":") |
          (.[0] | tonumber) * 60 + (.[1] | tonumber)) -
         ($start_ts | split("T")[1] | split("Z")[0] | split(":") |
          (.[0] | tonumber) * 60 + (.[1] | tonumber))) |
        if . < 0 then . + 1440 else . end
      ) as $durations |

      # Classify each duration
      ($durations | map(
        if . < 2 then "quick"
        elif . >= 2 and . < 3 then "normal"
        elif . >= 3 and . <= 8 then "mid"
        elif . > 8 and . < 15 then "normal"
        else "deep"
        end
      )) as $classes |

      # Count per bucket
      {
        automation: $name,
        automation_id: $id,
        total: ($classes | length),
        quick: ($classes | map(select(. == "quick")) | length),
        deep: ($classes | map(select(. == "deep")) | length),
        mid: ($classes | map(select(. == "mid")) | length),
        normal: ($classes | map(select(. == "normal")) | length)
      }
    ) |
    map(select(.total > 0)) |

    # Aggregate
    . as $per_auto |
    {
      per_automation: $per_auto,
      totals: {
        automations: ($per_auto | length),
        total_runs: ([.[].total] | add // 0),
        quick: ([.[].quick] | add // 0),
        deep: ([.[].deep] | add // 0),
        mid: ([.[].mid] | add // 0),
        normal: ([.[].normal] | add // 0)
      },
      bimodal_score: (
        (([.[].quick] | add // 0) + ([.[].deep] | add // 0)) as $good |
        ([.[].total] | add // 0) as $total |
        if $total == 0 then 100
        else (($good * 100) / $total | floor)
        end
      )
    }
  ' "$LEDGER_FILE" 2>/dev/null || echo '{"error":"query_failed"}'
}

# --- Per-Automation Run Stats --------------------------------------------- #
# Returns detailed stats for each automation: run count, last run, avg duration
#
# Args: [REPO] [HOURS]
# Output: JSON array of automation objects
ledger_automation_runs() {
  local repo="${1:-}" hours="${2:-24}"
  ledger_available || { echo '[]'; return; }
  command -v jq &>/dev/null || { echo '[]'; return; }

  local cutoff
  cutoff=$(date -u -v-"${hours}"H +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || \
           date -u -d "${hours} hours ago" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "")

  jq -s -c --arg repo "$repo" --arg cutoff "$cutoff" '
    [.[] | select(
      ($repo == "" or .repo == $repo) and
      ($cutoff == "" or (.ts // "") >= $cutoff) and
      (has("automation_id") and .automation_id != null and .automation_id != "")
    )] |
    group_by(.automation_id) |
    map(
      sort_by(.ts) |
      {
        automation_id: .[0].automation_id,
        automation_name: (.[0].automation_name // .[0].automation_id),
        repo: .[0].repo,
        run_count: length,
        last_run: .[-1].ts,
        last_summary: ((.[-1].summary // "")[:120]),
        events: ([.[] | .event] | unique),
        files_touched: ([.[].files? // [] | .[]?] | unique | length),
        has_worktree: ([.[] | select((.worktree // "") != "")] | length > 0)
      }
    ) |
    sort_by(.last_run) | reverse
  ' "$LEDGER_FILE" 2>/dev/null || echo '[]'
}

# --- Handoff Gap Detection ------------------------------------------------ #
# Detects cases where a radar automation found issues but no writer picked
# them up within N cycles. Uses automation naming conventions:
#   - Radars: automation_name contains "radar" (case-insensitive)
#   - Writers: automation_name contains "writer" or "shipper" or "nurse"
#
# Args: [REPO] [MAX_GAP_HOURS] (default: all repos, 4h)
# Output: JSON array of gap objects
ledger_handoff_gaps() {
  local repo="${1:-}" max_gap_hours="${2:-4}"
  ledger_available || { echo '[]'; return; }
  command -v jq &>/dev/null || { echo '[]'; return; }

  jq -s -c --arg repo "$repo" --argjson gap_hours "$max_gap_hours" '
    # Separate radars and writers
    [.[] | select($repo == "" or .repo == $repo)] |
    (
      [.[] | select(
        (.automation_name // "" | ascii_downcase | test("radar"))
        and (.summary // "") != ""
        and ((.summary // "") | test("nothing|no.?change|unchanged|same.?state|no.?new") | not)
      )] | sort_by(.ts)
    ) as $radar_findings |
    (
      [.[] | select(
        (.automation_name // "" | ascii_downcase | test("writer|shipper|nurse|train"))
      )] | sort_by(.ts)
    ) as $writer_actions |

    # For each radar finding with substance, check if a writer acted within gap window
    [$radar_findings[] |
      . as $finding |
      ($finding.ts) as $found_ts |
      ($finding.repo) as $found_repo |
      ([$writer_actions[] | select(
        .repo == $found_repo and
        .ts > $found_ts
      )] | first // null) as $first_writer |
      if $first_writer == null then
        {
          type: "unclaimed",
          radar: ($finding.automation_name // $finding.automation_id),
          repo: $found_repo,
          found_at: $found_ts,
          finding_summary: ($finding.summary // "")[0:100],
          writer_response: null,
          gap_hours: null
        }
      else
        # Rough hour diff (same-day only, good enough for gaps)
        (($first_writer.ts | split("T")[1] | split("Z")[0] | split(":") |
          (.[0] | tonumber) * 60 + (.[1] | tonumber)) -
         ($found_ts | split("T")[1] | split("Z")[0] | split(":") |
          (.[0] | tonumber) * 60 + (.[1] | tonumber))) as $diff_min |
        (if $diff_min < 0 then $diff_min + 1440 else $diff_min end) as $gap_min |
        if ($gap_min / 60) > $gap_hours then
          {
            type: "delayed",
            radar: ($finding.automation_name // $finding.automation_id),
            writer: ($first_writer.automation_name // $first_writer.automation_id),
            repo: $found_repo,
            found_at: $found_ts,
            picked_up_at: $first_writer.ts,
            gap_hours: (($gap_min / 60) * 10 | floor / 10),
            finding_summary: ($finding.summary // "")[0:100]
          }
        else empty end
      end
    ]
  ' "$LEDGER_FILE" 2>/dev/null || echo '[]'
}

# --- Fleet Health Report -------------------------------------------------- #
# Aggregate fleet health: bimodal score + automation stats + handoff gaps.
# This is the primary function called by vidux-manager fleet-health.
#
# Args: [REPO] [HOURS]
# Output: JSON object with complete fleet health
ledger_fleet_health() {
  local repo="${1:-}" hours="${2:-24}"
  ledger_available || { echo '{"error":"ledger_unavailable","available":false}'; return; }
  command -v jq &>/dev/null || { echo '{"error":"jq_not_installed"}'; return; }

  local bimodal automations gaps

  bimodal=$(ledger_bimodal_distribution "$repo" "$hours")
  automations=$(ledger_automation_runs "$repo" "$hours")
  gaps=$(ledger_handoff_gaps "$repo" 4)

  # Combine into a single report
  jq -n -c \
    --argjson bimodal "$bimodal" \
    --argjson automations "$automations" \
    --argjson gaps "$gaps" \
    --arg repo "$repo" \
    --arg hours "$hours" '
    {
      repo: (if $repo == "" then "all" else $repo end),
      window_hours: ($hours | tonumber),
      ledger_available: true,
      bimodal: $bimodal,
      automations: $automations,
      handoff_gaps: $gaps,
      summary: {
        automation_count: ($automations | length),
        bimodal_score: ($bimodal.bimodal_score // 0),
        bimodal_status: (
          if ($bimodal.totals.total_runs // 0) == 0 then "unknown"
          elif ($bimodal.bimodal_score // 0) > 85 then "healthy"
          elif ($bimodal.bimodal_score // 0) > 70 then "warning"
          else "critical"
          end
        ),
        total_runs: ($bimodal.totals.total_runs // 0),
        handoff_gap_count: ($gaps | length),
        mid_zone_automations: [($bimodal.per_automation // [])[] | select(.mid >= 3)] | length
      }
    }
  ' 2>/dev/null || echo '{"error":"aggregation_failed"}'
}

# --- Recent Activity ------------------------------------------------------ #
# Returns recent activity for a repo, formatted for dashboard consumption.
#
# Args: REPO [ENTRIES] (default: 10)
# Output: JSON array of activity entries
ledger_recent_activity() {
  local repo="${1:-}" entries="${2:-10}"
  ledger_available || { echo '[]'; return; }
  command -v jq &>/dev/null || { echo '[]'; return; }

  jq -s -c --arg repo "$repo" --argjson limit "$entries" '
    [.[] | select($repo == "" or .repo == $repo)] |
    sort_by(.ts) | reverse | .[:$limit] |
    [.[] | {
      ts: .ts,
      agent: (.agent_id // "unknown"),
      automation: (.automation_name // .automation_id // null),
      event: .event,
      summary: (.summary // "")[0:120],
      repo: .repo,
      files_count: ((.files // []) | length)
    }]
  ' "$LEDGER_FILE" 2>/dev/null || echo '[]'
}

# --- Conflict Detection --------------------------------------------------- #
# Detects concurrent work on the same files within a time window.
# Used by vidux-loop to check for conflicts before executing.
#
# Args: REPO FILE_LIST_JSON [HOURS] (default: 2h)
# Output: JSON array of conflict objects (empty = no conflicts)
ledger_conflict_check() {
  local repo="${1:-}" files="${2:-[]}" hours="${3:-2}"
  ledger_available || { echo '[]'; return; }
  command -v jq &>/dev/null || { echo '[]'; return; }

  local cutoff
  cutoff=$(date -u -v-"${hours}"H +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || \
           date -u -d "${hours} hours ago" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "")

  jq -s -c --arg repo "$repo" --arg cutoff "$cutoff" --argjson check_files "$files" '
    [.[] | select(
      .repo == $repo and
      ($cutoff == "" or (.ts // "") >= $cutoff) and
      (.files // []) as $entry_files |
      ($check_files | any(. as $f | $entry_files | any(. == $f)))
    )] |
    [.[] | {
      ts: .ts,
      agent: (.agent_id // "unknown"),
      automation: (.automation_name // null),
      event: .event,
      conflicting_files: (
        (.files // []) as $entry_files |
        [$check_files[] | select(. as $f | $entry_files | any(. == $f))]
      )
    }]
  ' "$LEDGER_FILE" 2>/dev/null || echo '[]'
}
