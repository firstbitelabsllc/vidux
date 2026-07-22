#!/usr/bin/env bash
# vidux-test-all.sh — comprehensive vidux self-test harness
# Runs all v2.3 contract tests, doctor checks, witness grading, and loop validation.
# Outputs a structured JSON report to stdout.
#
# Usage:  bash vidux-test-all.sh [--json] [--fix]
# Exit:   0 = all green, 1 = failures found, 2 = script error
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
JSON_MODE=false
FIX_MODE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON_MODE=true; shift ;;
    --fix)  FIX_MODE=true; shift ;;
    *)      echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# --- helpers ---------------------------------------------------------------- #
_json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"; s="${s//\"/\\\"}"; s="${s//$'\n'/\\n}"; s="${s//$'\r'/\\r}"; s="${s//$'\t'/\\t}"
  printf '%s' "$s"
}

TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
FAILURES=0
SECTIONS=""

# --- 1. Contract tests ------------------------------------------------------ #
export VIDUX_TEST_ALL_RUNNING=1
TEST_OUTPUT="$(python3 -m unittest discover -s tests 2>&1 || true)"
TEST_PASS="$(echo "$TEST_OUTPUT" | grep -oE 'Ran [0-9]+ tests?' | grep -oE '[0-9]+' || echo "0")"
TEST_FAIL="$(echo "$TEST_OUTPUT" | grep -oE 'failures?=[0-9]+' | grep -oE '[0-9]+' || echo "0")"
TEST_ERR="$(echo "$TEST_OUTPUT" | grep -oE 'errors?=[0-9]+' | grep -oE '[0-9]+' || echo "0")"
TEST_OK="$(echo "$TEST_OUTPUT" | grep -c '^OK' || true)"
TEST_STATUS="pass"
if [[ "$TEST_OK" -eq 0 ]]; then
  TEST_STATUS="fail"
  FAILURES=$((FAILURES + 1))
fi
TEST_SUMMARY="$(_json_escape "$(echo "$TEST_OUTPUT" | tail -5)")"

SECTIONS="${SECTIONS}{\"name\":\"contract_tests\",\"status\":\"$TEST_STATUS\",\"total\":$TEST_PASS,\"failures\":$TEST_FAIL,\"errors\":$TEST_ERR,\"summary\":\"$TEST_SUMMARY\"},"

# --- 2. Doctor checks ------------------------------------------------------- #
DOCTOR_ARGS=(--json --repo "$REPO")
[[ "$FIX_MODE" = true ]] && DOCTOR_ARGS+=(--fix)
DOCTOR_OUTPUT="$(bash "$SCRIPT_DIR/vidux-doctor.sh" "${DOCTOR_ARGS[@]}" 2>&1 || true)"
DOCTOR_PASS="$(echo "$DOCTOR_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('pass',0))" 2>/dev/null || echo "0")"
DOCTOR_TOTAL="$(echo "$DOCTOR_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total',0))" 2>/dev/null || echo "0")"
DOCTOR_STATUS="pass"
if [[ "$DOCTOR_PASS" -lt "$DOCTOR_TOTAL" ]]; then
  DOCTOR_STATUS="warn"
fi
DOCTOR_WARNS=$((DOCTOR_TOTAL - DOCTOR_PASS))

SECTIONS="${SECTIONS}{\"name\":\"doctor\",\"status\":\"$DOCTOR_STATUS\",\"pass\":$DOCTOR_PASS,\"total\":$DOCTOR_TOTAL,\"warns\":$DOCTOR_WARNS},"

# --- 3. Loop validation ----------------------------------------------------- #
LOOP_OUTPUT=""
LOOP_STATUS="skip"
PLAN_FILE="$REPO/PLAN.md"
if [[ -f "$PLAN_FILE" ]]; then
  LOOP_OUTPUT="$(bash "$SCRIPT_DIR/vidux-loop.sh" "$PLAN_FILE" 2>&1 || true)"
  LOOP_VALID="$(echo "$LOOP_OUTPUT" | python3 -c "import sys,json; json.load(sys.stdin); print('true')" 2>/dev/null || echo "false")"
  LOOP_MODE="$(echo "$LOOP_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mode','unknown'))" 2>/dev/null || echo "unknown")"
  LOOP_HOT="$(echo "$LOOP_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('hot_tasks',0))" 2>/dev/null || echo "0")"
  LOOP_COLD="$(echo "$LOOP_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('cold_tasks',0))" 2>/dev/null || echo "0")"
  LOOP_EC="$(echo "$LOOP_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d.get('exit_criteria_met','N/A')).lower())" 2>/dev/null || echo "N/A")"
  if [[ "$LOOP_VALID" = "true" ]]; then
    LOOP_STATUS="pass"
  else
    LOOP_STATUS="fail"
    FAILURES=$((FAILURES + 1))
  fi
  SECTIONS="${SECTIONS}{\"name\":\"loop_validation\",\"status\":\"$LOOP_STATUS\",\"valid_json\":$LOOP_VALID,\"mode\":\"$LOOP_MODE\",\"hot_tasks\":$LOOP_HOT,\"cold_tasks\":$LOOP_COLD,\"exit_criteria_met\":\"$LOOP_EC\"},"
else
  SECTIONS="${SECTIONS}{\"name\":\"loop_validation\",\"status\":\"skip\",\"reason\":\"no PLAN.md\"},"
fi

# --- 5. Script syntax check ------------------------------------------------- #
SYNTAX_FAILS=0
SYNTAX_DETAILS=""
for script in "$SCRIPT_DIR"/vidux-*.sh; do
  [[ -f "$script" ]] || continue
  name="$(basename "$script")"
  if ! bash -n "$script" 2>/dev/null; then
    SYNTAX_FAILS=$((SYNTAX_FAILS + 1))
    SYNTAX_DETAILS="${SYNTAX_DETAILS}\"$name\","
  fi
done
SYNTAX_STATUS="pass"
[[ "$SYNTAX_FAILS" -gt 0 ]] && { SYNTAX_STATUS="fail"; FAILURES=$((FAILURES + 1)); }
SYNTAX_DETAILS="${SYNTAX_DETAILS%,}"

SECTIONS="${SECTIONS}{\"name\":\"script_syntax\",\"status\":\"$SYNTAX_STATUS\",\"failures\":$SYNTAX_FAILS,\"failed_scripts\":[$SYNTAX_DETAILS]},"

# --- 6. Dispatch script dry-run --------------------------------------------- #
DISPATCH_STATUS="skip"
DISPATCH_REC="skip"
if [[ -f "$SCRIPT_DIR/vidux-dispatch.sh" && -f "$PLAN_FILE" ]]; then
  DISPATCH_OUTPUT="$(bash "$SCRIPT_DIR/vidux-dispatch.sh" "$PLAN_FILE" --dry-run 2>&1 || true)"
  DISPATCH_VALID="$(echo "$DISPATCH_OUTPUT" | python3 -c "import sys,json; json.load(sys.stdin); print('true')" 2>/dev/null || echo "false")"
  DISPATCH_REC="$(echo "$DISPATCH_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('recommendation','unknown'))" 2>/dev/null || echo "unknown")"
  if [[ "$DISPATCH_VALID" = "true" ]]; then
    DISPATCH_STATUS="pass"
  else
    DISPATCH_STATUS="fail"
    FAILURES=$((FAILURES + 1))
  fi
  SECTIONS="${SECTIONS}{\"name\":\"dispatch_dry_run\",\"status\":\"$DISPATCH_STATUS\",\"valid_json\":$DISPATCH_VALID,\"recommendation\":\"$DISPATCH_REC\"},"
fi

# --- final report ----------------------------------------------------------- #
SECTIONS="${SECTIONS%,}"
OVERALL="pass"
[[ "$FAILURES" -gt 0 ]] && OVERALL="fail"

REPORT="{\"timestamp\":\"$TIMESTAMP\",\"overall\":\"$OVERALL\",\"failures\":$FAILURES,\"sections\":[$SECTIONS]}"

if [[ "$JSON_MODE" = true ]]; then
  echo "$REPORT"
else
  # Human-readable summary
  echo "=== Vidux Self-Test Report ==="
  echo "Timestamp: $TIMESTAMP"
  echo ""
  echo "1. Contract Tests:  $TEST_STATUS ($TEST_PASS tests, $TEST_FAIL failures, $TEST_ERR errors)"
  echo "2. Doctor:          $DOCTOR_STATUS ($DOCTOR_PASS/$DOCTOR_TOTAL pass, $DOCTOR_WARNS warns)"
  echo "3. Fleet Quality:   $FLEET_STATUS (verdict=$FLEET_VERDICT, $FLEET_DEEP deep, $FLEET_QUICK quick, $FLEET_MID mid-zone)"
  echo "4. Loop Validation: $LOOP_STATUS (hot=$LOOP_HOT, cold=$LOOP_COLD, exit_criteria=$LOOP_EC)"
  echo "5. Script Syntax:   $SYNTAX_STATUS ($SYNTAX_FAILS failures)"
  echo "6. Dispatch Dry-Run: $DISPATCH_STATUS (rec=$DISPATCH_REC)"
  echo ""
  echo "Overall: $OVERALL ($FAILURES sections with issues)"
fi

if [[ "$OVERALL" = "pass" ]]; then
  exit 0
fi
exit 1
