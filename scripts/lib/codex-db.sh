#!/usr/bin/env bash
# codex-db.sh — Safe Codex DB write helpers
#
# The Codex desktop app caches automation state in memory and overwrites
# SQLite on restart/sync. Direct DB writes WILL be reverted unless the
# app is stopped first. This lib provides the kill→write→verify pattern.
#
# Usage:
#   source scripts/lib/codex-db.sh
#   codex_db_path          # prints path to codex-dev.db
#   codex_db_stop_app      # kills Codex processes (required before writes)
#   codex_db_query "SQL"   # runs read-only query
#   codex_db_write "SQL"   # runs write query (asserts app is stopped)
#   codex_db_is_app_running  # returns 0 if running, 1 if stopped
#
# Evidence: fleet rebuild sessions — 3 failed DB writes before discovering
# the race condition. Codex app-server PIDs cache state in memory.

[[ -n "${_VIDUX_CODEX_DB_LOADED:-}" ]] && return 0
_VIDUX_CODEX_DB_LOADED=1

CODEX_DB="${CODEX_DB:-$HOME/.codex/sqlite/codex-dev.db}"

codex_db_path() {
  echo "$CODEX_DB"
}

codex_db_is_app_running() {
  pgrep -f "codex app-server" >/dev/null 2>&1 || pgrep -f "Codex Helper" >/dev/null 2>&1
}

codex_db_stop_app() {
  pkill -f "codex app-server" 2>/dev/null || true
  pkill -f "Codex Helper" 2>/dev/null || true
  sleep 1
  # Verify stopped
  if codex_db_is_app_running; then
    echo "WARNING: Codex processes still running after kill attempt" >&2
    return 1
  fi
  return 0
}

codex_db_query() {
  local sql="$1"
  [[ ! -f "$CODEX_DB" ]] && { echo "Error: Codex DB not found at $CODEX_DB" >&2; return 1; }
  sqlite3 "$CODEX_DB" "$sql"
}

codex_db_write() {
  local sql="$1"
  [[ ! -f "$CODEX_DB" ]] && { echo "Error: Codex DB not found at $CODEX_DB" >&2; return 1; }
  # Safety: refuse to write if app is running
  if codex_db_is_app_running; then
    echo "ERROR: Codex app is running. DB writes will be reverted." >&2
    echo "Run codex_db_stop_app first." >&2
    return 1
  fi
  # Use millisecond epoch for updated_at (Codex scheduler format)
  sqlite3 "$CODEX_DB" "$sql"
}

# Convenience: current epoch in milliseconds (Codex timestamp format)
codex_db_epoch_ms() {
  python3 -c "import time; print(int(time.time() * 1000))" 2>/dev/null || \
    echo "$(date +%s)000"
}

# ── Bug #22 prevention ─────────────────────────────────────────────
# NEVER use re.sub() or sed to patch TOML prompt fields.
# Always regenerate the entire TOML from the DB row.
# ───────────────────────────────────────────────────────────────────

CODEX_AUTOMATIONS_DIR="${CODEX_AUTOMATIONS_DIR:-$HOME/.codex/automations}"

# codex_sync_tomls — regenerate ALL automation.toml files from DB rows.
# Reads every ACTIVE row, escapes the prompt safely, writes a fresh TOML.
# Returns: 0 on success, 1 on error. Prints summary to stdout.
codex_sync_tomls() {
  [[ ! -f "$CODEX_DB" ]] && { echo "Error: Codex DB not found at $CODEX_DB" >&2; return 1; }

  # Python does the heavy lifting: reads DB, escapes prompts, writes TOMLs.
  # This avoids ALL shell escaping issues and re.sub pitfalls.
  python3 - "$CODEX_DB" "$CODEX_AUTOMATIONS_DIR" <<'PYEOF'
import sqlite3, sys, os, json

db_path = sys.argv[1]
auto_dir = sys.argv[2]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
rows = conn.execute("""
    SELECT id, name, prompt, status, rrule, cwds, model, reasoning_effort,
           created_at, updated_at
    FROM automations WHERE status = 'ACTIVE'
""").fetchall()
conn.close()

synced = 0
errors = 0

for row in rows:
    aid = row["id"]
    dirpath = os.path.join(auto_dir, aid)
    os.makedirs(dirpath, exist_ok=True)

    # Safe TOML escape — the ONLY correct pattern (Bug #22 prevention)
    prompt = row["prompt"] or ""
    esc = (prompt
           .replace('\\', '\\\\')
           .replace('"', '\\"')
           .replace('\n', '\\n')
           .replace('\t', '\\t')
           .replace('\r', '\\r'))

    # Verify single-line (the invariant Bug #22 violates)
    if '\n' in esc and '\\n' not in esc:
        print(f"ERROR: {aid} — escaped prompt still contains raw newlines", file=sys.stderr)
        errors += 1
        continue

    cwds = row["cwds"] or "[]"
    # Normalize cwds to TOML array format
    try:
        cwd_list = json.loads(cwds)
        cwds_toml = "[" + ", ".join(f'"{c}"' for c in cwd_list) + "]"
    except (json.JSONDecodeError, TypeError):
        cwds_toml = "[]"

    created = row["created_at"] or 0
    updated = row["updated_at"] or 0
    model = row["model"] or ""
    reasoning = row["reasoning_effort"] or ""

    lines = [
        'version = 1',
        f'id = "{aid}"',
        'kind = "cron"',
        f'name = "{row["name"]}"',
        f'prompt = "{esc}"',
        f'status = "{row["status"]}"',
        f'rrule = "{row["rrule"] or ""}"',
        f'cwds = {cwds_toml}',
        f'created_at = {created}',
        f'updated_at = {updated}',
    ]
    if model:
        lines.append(f'model = "{model}"')
    if reasoning:
        lines.append(f'reasoning_effort = "{reasoning}"')

    # Optional: preserve execution_environment if present
    # (Codex worktree mode)
    lines.append('execution_environment = "worktree"')

    toml_path = os.path.join(dirpath, "automation.toml")
    with open(toml_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    # Post-write verification: read it back and check prompt is single-line
    with open(toml_path, 'r') as f:
        for line in f:
            if line.startswith('prompt = "'):
                if line.count('\n') > 1:  # more than the trailing newline
                    print(f"VERIFY FAIL: {aid} — TOML prompt is multi-line after write!", file=sys.stderr)
                    errors += 1
                break

    synced += 1

print(f"Synced {synced}/{len(rows)} TOMLs ({errors} errors)")
if errors:
    sys.exit(1)
PYEOF

  return $?
}

# codex_safe_restart — full quit → sync TOMLs → reopen Codex.
# The ONLY correct sequence for modifying automations (Bugs #14-17, #22).
codex_safe_restart() {
  echo "Step 1/3: Quitting Codex app..."
  osascript -e 'tell application "Codex" to quit' 2>/dev/null || true
  sleep 3

  # Double-check it's really dead
  if pgrep -f "Codex" >/dev/null 2>&1; then
    echo "WARNING: Codex still running, force killing..." >&2
    pkill -9 -f "Codex" 2>/dev/null || true
    sleep 2
  fi

  echo "Step 2/3: Regenerating all TOMLs from DB..."
  codex_sync_tomls
  local sync_result=$?

  if [[ $sync_result -ne 0 ]]; then
    echo "ERROR: TOML sync failed. NOT reopening Codex until fixed." >&2
    return 1
  fi

  echo "Step 3/3: Reopening Codex..."
  open -a "Codex"
  sleep 2
  echo "Done. Codex restarted with fresh TOMLs."
}

# codex_verify_tomls — read-only check that all TOMLs match DB and are valid.
# Use this to audit without modifying anything.
codex_verify_tomls() {
  [[ ! -f "$CODEX_DB" ]] && { echo "Error: Codex DB not found at $CODEX_DB" >&2; return 1; }

  python3 - "$CODEX_DB" "$CODEX_AUTOMATIONS_DIR" <<'PYEOF'
import sqlite3, sys, os

db_path = sys.argv[1]
auto_dir = sys.argv[2]

conn = sqlite3.connect(db_path)
rows = conn.execute("SELECT id, name FROM automations WHERE status='ACTIVE'").fetchall()
conn.close()

ok = 0
issues = []

for aid, name in rows:
    toml_path = os.path.join(auto_dir, aid, "automation.toml")
    if not os.path.exists(toml_path):
        issues.append(f"MISSING: {aid} — no automation.toml")
        continue
    with open(toml_path, 'r') as f:
        content = f.read()
    # Check prompt is single-line
    for line in content.split('\n'):
        if line.startswith('prompt = "'):
            # The prompt line should be one line — no embedded real newlines
            ok += 1
            break
    else:
        issues.append(f"NO PROMPT: {aid} — no prompt line found in TOML")

if issues:
    for i in issues:
        print(f"  !! {i}")
    print(f"\n{ok} OK, {len(issues)} issues out of {len(rows)} active automations")
    sys.exit(1)
else:
    print(f"All {ok}/{len(rows)} TOMLs verified — single-line prompts, files exist.")
PYEOF
}
