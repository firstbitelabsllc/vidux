# Platform Comparison: Claude Code vs Codex

Vidux is the discipline; Claude Code and Codex are two runtimes that run vidux cycles on a schedule. Cursor runs the same discipline interactively or as an editor-bound worker. Pick the platform per lane without changing the proof model.

For Codex, this page covers the native path that registers a repo-bound lane with the desktop app. The automation guide defaults Codex-created automations to `Chat`; `Local` and `Worktree` are explicit opt-ins for direct project-folder execution.

## At a Glance

| Feature | Claude Code | Codex |
|---|---|---|
| **Models** | Claude Opus / Sonnet / Haiku | GPT-5.x (gpt-5.4 default) |
| **Scheduling** | `CronCreate` — in-session, 5-field cron | TOML + rrule — survives app restart |
| **Auto-expire** | 7 days (session-bound) | None (until stopped or app closed) |
| **CLI automations** | Yes | **No** — Mac desktop app only |
| **Config location** | In-session (no config file) | `~/.codex/config.toml` |
| **Lane files** | Shared `{lane-dir}/{lane-id}/`: `prompt.md` instructions + `memory.md` lane-local log | Shared `{lane-dir}/{lane-id}/`: `prompt.md` instructions + `memory.md` lane-local log |
| **Registration** | Session-scoped `CronCreate` job | `automation.toml` + DB row |
| **Restart flow** | Re-schedule `CronCreate` on new session | Full-quit app → reopen (`osascript` + `open -a`) |
| **Sandbox** | N/A (local, full access) | `read-only` / `workspace-write` / `danger-full-access` |
| **Multi-agent** | Native subagents in-session | Native subagents in-session |
| **Session model** | Disposable sessions; lanes persist on disk | Desktop app process; automations in DB + TOML |
| **Session GC** | Required (`session-gc` lane + operator JSONL cleanup helper) | Not needed |
| **Max lanes** | 6 per session (worktree contention limit) | No repo-defined Codex cap |
| **Delegation** | Mode A / Mode B via native subagents | Mode A / Mode B via native subagents |

A Chat-mode Codex automation skips TOML + DB registration; it needs only the shared lane files and prompt discipline.

## Shared lifecycle contract

Scheduling and sandboxing differ; the runtime proof packet is the same:

- **Config:** `python3 scripts/vidux-config.py check --json` before trusting plan-store/adapter paths. `python3 scripts/vidux-config.py show --json` for a redacted human summary.
- **Pre-task hook:** `scripts/vidux-doctor.sh --json` for runtime health. Reserve `vidux doctor` for terminal install/readiness — it may run `npm test`.
- **Attribution:** set `VIDUX_RUNTIME=claude`, `VIDUX_RUNTIME=codex`, or `VIDUX_RUNTIME=cursor` for spawned workers when inherited env would misattribute.
- **Durable handoff:** update the owning `PLAN.md` and emit the matching publish ledger row with task id, proof, handoff status, files claimed, path-like claims, and next-agent resume before any branch/PR/release publish.

## Scheduling and persistence

Both platforms: **lanes persist on disk, sessions are disposable.** Full lifecycle in [claude-lifecycle.md](claude-lifecycle.md) / [codex-lifecycle.md](codex-lifecycle.md).

**Claude Code** — `CronCreate` (deferred tool, fetch via `ToolSearch`) is **session-scoped** and dies when the process exits (7-day auto-expire). Lanes survive across sessions because instructions and local cycle notes live under the shared lane directory, while shipped-work proof lives in the owning plan plus publish ledger rows. To restart a dead fleet, re-schedule each `CronCreate`; each lane reads its own `memory.md` for local cycle orientation, then resumes from the owning plan plus publish ledger proof. Session JSONLs (`~/.claude/projects/*/*.jsonl`) are hot storage pruned by the session-gc lane; lane files are cold storage, never auto-deleted.

**Codex** — **TOML files + DB rows** read by the Mac desktop app (the `codex` CLI runs only one-shot commands; no auto-expire). Each automation lives at `~/.codex/automations/{id}/automation.toml` with a row in `~/.codex/sqlite/codex-dev.db`. The actual lane instructions and local cycle notes live under a shared `{lane-dir}/{lane-id}/`. All four pieces matter: DB is the runtime source, TOML is the UI source, and the owning plan plus publish ledger rows carry shipped-work proof. To create/update: write the TOML, insert/update the DB row, then **full-quit and reopen** — `pkill app-server` alone is insufficient (Bug #15).

## When to Use Which

| Scenario | Platform | Why |
|---|---|---|
| 24/7 fleet across account rotation | Claude Code | Session cycling + lane-local memory notes plus plan/ledger handoff works across accounts |
| Sub-hour cadence (< 60 min) | Claude Code | CronCreate supports any cron expression |
| Persistent (weeks/months) | Codex | No 7-day auto-expire |
| Heavy code generation | Codex | Long-lived desktop automation + native worktree editing |
| Research / file reading > 3 KB | Codex | Mode A summaries keep parent context small |
| Local toolchain (Xcode, simulators) | Claude Code | Full local access; Codex sandbox restricts |
| Multi-account rotation | Claude Code | Codex is per-app-install |

## Known Bugs (Codex, as of Apr 2026)

| # | Bug | Impact |
|---|---|---|
| 14 | New automations invisible after DB insert | Must full-quit app, not just restart app-server |
| 15 | `pkill app-server` insufficient for new rows | Electron frontend caches automation list separately |
| 16 | TOML files required for UI visibility | DB-only inserts run but stay invisible |
| 18 | Missing `created_at`/`updated_at` | Automation fails silently |
| 22 | Raw newlines in prompt field | TOML parse failure; escape as `\n` |

Preflight with `codex_verify_tomls` (from `scripts/lib/codex-db.sh`) before reopen, or `codex_safe_restart` for the full quit → sync → reopen path.

## See Also

- [Claude Code Lifecycle](claude-lifecycle.md) — full lifecycle of a Claude lane
- [Codex Lifecycle](codex-lifecycle.md) — full lifecycle of a Codex automation
- [Codex Setup Guide](codex-setup.md) — step-by-step Mac app setup
