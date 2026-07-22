# Codex Setup Guide

Create a native Codex automation on Mac: the TOML + DB + app-restart sequence for repo-bound `Local` or `Worktree` lanes. Codex-created automations default to `Chat`; use this flow only when the lane needs native project-folder execution.

> **⚠️ The Codex CLI cannot run automations.**
> The `codex` CLI runs one-shot tasks; recurring jobs require the **Codex Mac desktop app**. On Linux, a remote server, or CI this will not work — use Claude Code `CronCreate` ([claude-lifecycle.md](claude-lifecycle.md)).

## Prerequisites

- Codex Mac desktop app installed + signed in.
- `~/.codex/config.toml` with `model`, `sandbox_mode`, and trusted project paths.
- `sqlite3` CLI (preinstalled on macOS).
- Local vidux checkout — `source scripts/lib/codex-db.sh` for helpers (`codex_verify_tomls`, `codex_sync_tomls`, `codex_safe_restart`).

Verify your environment:

```bash
ls ~/.codex/sqlite/codex-dev.db         # runtime DB must exist
ls ~/.codex/automations/                # lane directory root
grep -E "^(model|sandbox_mode)" ~/.codex/config.toml
python3 scripts/vidux-config.py check --json
```

## The Five-Step Setup Flow

Every new automation follows this exact sequence. Skipping steps causes the [known bugs](codex-lifecycle.md#known-bugs--troubleshooting).

```
1. Write automation.toml      → disk (UI visibility source)
2. Insert DB row              → sqlite (runtime source)
3. Write prompt.md + memory.md → disk (lane instructions + lane-local cycle log)
4. Run codex_verify_tomls     → lightweight preflight before reopen
5. Full-quit + reopen the app → clears Electron cache (Bug #14/#15)
```

## Step 1 — Write `automation.toml`

Pick a unique `id` (UUID or slugified name) and create the lane directory:

```bash
LANE_ID="project-coordinator"   # or a UUID
mkdir -p "$HOME/.codex/automations/$LANE_ID"
```

```toml
version = 1
id = "project-coordinator"
kind = "cron"
name = "project coordinator"
prompt = "Read {lane-dir}/project-coordinator/prompt.md FIRST. Execute one vidux cycle: READ → ASSESS → ACT → VERIFY → CHECKPOINT.\nHonor all constraints in the prompt file.\nRecord the lane-local memory note, and for shipped work update the owning PLAN.md plus matching publish ledger row before any commit/push."
status = "ACTIVE"
rrule = "FREQ=MINUTELY;INTERVAL=30"
model = "gpt-5.4"
reasoning_effort = "medium"
execution_environment = "worktree"
cwds = ["/path/to/repo"]
created_at = 1744761600000
updated_at = 1744761600000
```

Field notes:

- `id` — matches the directory name and DB row `id` (all three agree).
- `prompt` — **single-line only**; escape newlines as `\n` (Bug #22).
- `rrule` — RFC 5545. 30 min: `FREQ=MINUTELY;INTERVAL=30`; hourly: `FREQ=HOURLY;INTERVAL=1;BYMINUTE=0`; daily 09:00: `FREQ=DAILY;BYHOUR=9;BYMINUTE=0`.
- `cwds` — JSON array of absolute paths; Codex runs in the first.
- `created_at`/`updated_at` — **required**, millisecond unix epoch (Bug #18). `codex_db_epoch_ms` (after sourcing `scripts/lib/codex-db.sh`) prints the format.
- `execution_environment` — `"worktree"` for recurring lanes. Sandbox access comes from `sandbox_mode` in `~/.codex/config.toml`.

## Step 2 — Insert the DB row

TOML is the UI source; the DB row is the runtime — both must exist.

```bash
NOW=$(python3 -c 'import time; print(int(time.time() * 1000))')
PROMPT_ESCAPED=$(grep '^prompt = ' "$HOME/.codex/automations/$LANE_ID/automation.toml" | sed 's/^prompt = "\(.*\)"$/\1/')

sqlite3 "$HOME/.codex/sqlite/codex-dev.db" <<EOF
INSERT INTO automations (
  id, name, prompt, status, rrule, cwds,
  model, reasoning_effort, created_at, updated_at
) VALUES (
  '$LANE_ID',
  'project coordinator',
  '$PROMPT_ESCAPED',
  'ACTIVE',
  'FREQ=MINUTELY;INTERVAL=30',
  '["/path/to/repo"]',
  'gpt-5.4',
  'medium',
  $NOW,
  $NOW
);
EOF
```

Confirm the row landed:

```bash
sqlite3 "$HOME/.codex/sqlite/codex-dev.db" \
  "SELECT id, name, status, rrule FROM automations WHERE id='$LANE_ID';"
```

Row missing = won't fire. TOML missing = won't show. **Both required** (Bug #16).

## Step 3 — Write lane instruction/log files

The TOML holds the schedule. Actual instructions and the lane-local cycle log live in separate files the prompt points at:

```bash
# Pick one shared lane root for your fleet (any automation root or a
# project-scoped directory works); keep prompt + memory together there.
LANE_DIR="$HOME/.vidux/lanes/$LANE_ID"
mkdir -p "$LANE_DIR"

$EDITOR "$LANE_DIR/prompt.md"   # 8-block structure

cat > "$LANE_DIR/memory.md" <<EOF
# $LANE_ID — memory
- [$(date -u +%Y-%m-%dT%H:%M:%SZ) codex setup] Lane created. First fire scheduled per rrule.
EOF
```

See [prompt-template.md](../reference/prompt-template.md) for the 8-block structure (Mission / Skills / Read / Gate / Assess / Act / Authority / Checkpoint).

## Step 4 — Verify

Run the verifier **before** reopening — the preflight confirms active DB rows have TOML files with prompt lines.

```bash
source scripts/lib/codex-db.sh
codex_verify_tomls   # success: "All 1/1 TOMLs verified — single-line prompts, files exist."
```

On failure, fix and re-run. **Do not reopen with broken TOMLs** — the app may silently skip or crash on them. `codex_safe_restart` is the full safe path instead of manual Step 5: it quits the app, regenerates TOMLs from DB rows via `codex_sync_tomls`, and reopens.

## Step 5 — Full-quit and reopen the app

The most-skipped step. A full quit clears the Electron frontend's in-memory automation cache.

```bash
osascript -e 'tell application "Codex" to quit'
sleep 3
open -a "Codex"
```

`pkill -f codex-app-server` leaves the Electron frontend running and your lane invisible (Bug #15). `sleep 3` lets the app flush DB writes and release locks. After reopen, the Automations panel shows the lane with a countdown to the next fire.

## Verification Checklist

Before the lane is "live," confirm all:

- [ ] `ls ~/.codex/automations/$LANE_ID/automation.toml` — TOML exists.
- [ ] `sqlite3 ~/.codex/sqlite/codex-dev.db "SELECT id FROM automations WHERE id='$LANE_ID';"` — DB row exists.
- [ ] `source scripts/lib/codex-db.sh && codex_verify_tomls` — exits 0.
- [ ] `python3 scripts/vidux-config.py check --json` — local config resolves or example fallback is explicit.
- [ ] Codex app shows the lane in the Automations UI.
- [ ] After the first fire, `tail -1 $LANE_DIR/memory.md` shows a lane-local cycle note; if work shipped, the owning `PLAN.md` plus publish ledger row carries the proof/resume packet.

If any check fails, re-read [codex-lifecycle.md § Known Bugs](codex-lifecycle.md#known-bugs--troubleshooting).

## Updating an Existing Automation

Edit the TOML and the DB row together (a desync makes the UI show one thing while the runtime fires another), `codex_verify_tomls`, then full-quit + reopen:

```bash
$EDITOR "$HOME/.codex/automations/$LANE_ID/automation.toml"
NOW=$(python3 -c 'import time; print(int(time.time() * 1000))')
sqlite3 "$HOME/.codex/sqlite/codex-dev.db" \
  "UPDATE automations SET prompt='{new prompt}', updated_at=$NOW WHERE id='$LANE_ID';"
source scripts/lib/codex-db.sh && codex_verify_tomls
osascript -e 'tell application "Codex" to quit' && sleep 3 && open -a "Codex"
```

## Stopping / Deleting an Automation

Set `status='PAUSED'` (pause) or `DELETE` the row (full delete), then full-quit + reopen. On delete, `rm -rf` the `~/.codex/automations/$LANE_ID` dir; the shared-lane prompt + lane-local cycle log are records — keep unless the lane is truly retired.

```bash
# pause:  UPDATE automations SET status='PAUSED' WHERE id='$LANE_ID';
# delete: DELETE FROM automations WHERE id='$LANE_ID';  then  rm -rf "$HOME/.codex/automations/$LANE_ID"
sqlite3 "$HOME/.codex/sqlite/codex-dev.db" "UPDATE automations SET status='PAUSED' WHERE id='$LANE_ID';"
osascript -e 'tell application "Codex" to quit' && sleep 3 && open -a "Codex"
```

## See Also

- [Codex Lifecycle](codex-lifecycle.md) — what happens each fire
- [Platform Comparison](platforms.md) — Codex vs Claude Code
- [Prompt Template](../reference/prompt-template.md) — the 8-block structure
- [Fleet Operations](operations.md) — dispatch + worktree discipline
- [Recipe Catalog](recipes.md) — reusable automation patterns
