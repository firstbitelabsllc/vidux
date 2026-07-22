# Codex Automation Lifecycle

A native Codex lane is a recurring vidux cycle scheduled via a **TOML file + DB row** read by the Codex Mac desktop app. This page covers creation → fire → troubleshooting, including the app-restart discipline unique to Codex.

The automation guide defaults Codex-created automations to `Chat`. Use this lifecycle only for a repo-bound native lane in `Local` or `Worktree`.

## Prerequisites

- Codex Mac desktop app (the `codex` CLI alone **cannot run automations**).
- `~/.codex/config.toml` with `sandbox_mode` + `model`.
- `sqlite3` CLI.
- Local vidux checkout — `source scripts/lib/codex-db.sh` for helpers (`codex_verify_tomls`, `codex_sync_tomls`, `codex_safe_restart`).

## Lane Files

Four pieces that must stay in sync:

```
~/.codex/automations/{id}/automation.toml  ← schedule + static shim prompt (UI source)
~/.codex/sqlite/codex-dev.db               ← runtime source (one row per lane)
{lane-dir}/{lane-id}/prompt.md             ← real instructions, hot-editable
{lane-dir}/{lane-id}/memory.md             ← lane-local cycle log
```

TOML + DB row register the automation. `prompt.md` holds instructions; `memory.md` holds the lane-local cycle log. Shipped-cycle state lives in the owning `PLAN.md` plus matching publish ledger rows. DB-only inserts run but stay UI-invisible (Bug #16); TOML-only files show but never fire. The shared lane directory lets the next fire pick up prompt edits and cycle history without re-registering.

## Creation

### 1. Write the TOML

```toml
version = 1
id = "project-coordinator"
kind = "cron"
name = "project coordinator"
prompt = "Read {lane-dir}/project-coordinator/prompt.md FIRST...\nThen execute one vidux cycle."
status = "ACTIVE"
rrule = "FREQ=MINUTELY;INTERVAL=30"
model = "gpt-5.4"
reasoning_effort = "medium"
execution_environment = "worktree"
cwds = ["/path/to/repo"]
created_at = 1744761600000
updated_at = 1744761600000
```

Required fields (public examples + `codex_sync_tomls` output): `version`, `id`, `kind`, `name`, `prompt`, `status`, `rrule`, `model`, `reasoning_effort`, `execution_environment`, `cwds`, `created_at`, `updated_at`. Missing `created_at`/`updated_at` = silent failure (Bug #18); use **millisecond** epoch integers. Sandbox access comes from `sandbox_mode` in `~/.codex/config.toml`. Prompt field is single-line — escape newlines as `\n` (Bug #22).

### 2-4. Insert DB row, verify, restart

Insert a matching `automations` row, run `codex_verify_tomls` (exit 0 = safe; the lightweight preflight confirms active DB rows have TOML files with prompt lines), then full-quit + reopen the app — `pkill app-server` is insufficient for new automations (Bug #15: the Electron frontend caches the list separately). `codex_safe_restart` does the full quit → sync → reopen. Step-by-step SQL/verify/restart commands: [codex-setup.md](codex-setup.md).

## Cycle Execution

Each rrule fire launches a fresh agent in the configured `cwds` and runs one vidux cycle:

```
0. CONFIG   `python3 scripts/vidux-config.py check --json`; keep local config separate from checked-in example fallback.
1. READ     prompt.md -> memory.md (last 3) -> PLAN.md -> INBOX.md
2. PRE-HOOK Run `scripts/vidux-doctor.sh --json`.
3. GATE     Dirty tree not mine? -> [QC] exit. 3x stuck? -> [blocked]. Main CI red? -> fix.
4. ASSESS   Priority: CI red -> PR fix -> PR merge -> resume in_progress -> next pending -> filler audit
5. ACT      Worktree per code change. Research dispatch (read-only) / implementation dispatch (workspace-write) per task. Set `VIDUX_RUNTIME=codex` for Codex workers or `VIDUX_RUNTIME=cursor` for Cursor-attributed workers.
6. VERIFY   Build + tests pass; visual check for UI.
7. CHECKPOINT  Update the owning PLAN.md status/Progress and emit the matching publish ledger row with task id, proof, handoff status, files claimed, and next-agent resume. Append the lane-local memory line; commit/push only after the plan/ledger packet exists.
```

### Sandbox modes

Set per-task or per-session in `config.toml`:

| Mode | Reads | Writes | Use |
|---|---|---|---|
| `read-only` | Yes | No | Research dispatch — compressed summaries |
| `workspace-write` | Yes | Working tree only | Implementation dispatch — code edits |
| `danger-full-access` | Yes | Anywhere | Trusted automations only |

Research dispatch keeps parent context small; implementation dispatch hands a bounded write task to a secondary Codex agent. See [Fleet Operations](/fleet/operations) for the delegation model.

### Post-push defer

Same as Claude lanes: no merge in the push cycle. Merge eligibility: CI green + ≥1h since last fix-push + no unresolved required findings.

## Persistence Model

- **TOML + DB row** live on disk; survive app quit, reboot, account changes.
- **`prompt.md` + `memory.md`** live in the shared lane directory as instructions plus lane-local cycle log; durable shipped work lives in the owning `PLAN.md` plus matching publish ledger rows.
- **Agent sessions** live in the desktop app process; die on quit.
- **No session GC** — the Codex app manages its own memory (no growing JSONL files).

On reopen, the app reads the DB, resumes all `ACTIVE` automations, and fires per rrule. Each fire reads the shared `prompt.md`/`memory.md` for lane-local continuity, then uses the owning plan plus publish ledger packet for shipped-cycle proof and resume metadata.

**No auto-expire** — automations run until manually stopped (`status = 'PAUSED'` or DB delete) or the app closes permanently.

## Known Bugs + Troubleshooting

Preflight with `codex_verify_tomls`; full quit → sync → reopen with `codex_safe_restart`.

| Bug # | Symptom | Cause | Fix |
|---|---|---|---|
| 14 | Automation invisible after DB insert | App caches list | Full-quit (`osascript 'quit'`), not restart app-server |
| 15 | `pkill app-server` misses new rows | Electron frontend caches separately | Full quit required |
| 16 | Invisible in UI | TOML missing / DB-only | Write both, full-quit + reopen |
| 18 | Silent failure on fire | Missing `created_at`/`updated_at` | Set both to millisecond epoch; run verify |
| 22 | Prompt truncated / parse failure | Raw newline in TOML | Escape as `\n`; re-verify |
| — | Not firing | App quit or rrule typo | Reopen; check `rrule` (RFC 5545) |
| — | Lane can't write files | Sandbox = `read-only` | Switch to `workspace-write` |
| — | Can't run from CLI | Expected — CLI has no automations | Use Mac desktop app |

## See Also

- [Platform Comparison](platforms.md) — Claude Code vs Codex
- [Claude Code Lifecycle](claude-lifecycle.md) — the Claude equivalent
- [Codex Setup Guide](codex-setup.md) — step-by-step Mac app setup (Task 5)
- [Fleet Operations](/fleet/operations) — dispatch + worktree discipline
- [Recipe Catalog](/fleet/recipes) — reusable automation patterns
