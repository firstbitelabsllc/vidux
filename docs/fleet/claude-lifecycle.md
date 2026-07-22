# Claude Code Lane Lifecycle

A Claude Code lane is a recurring vidux cycle scheduled via `CronCreate` inside a live session. Lifecycle: creation → cycle → session death → recovery.

## Prerequisites

- Claude Code CLI or desktop app running.
- `CronCreate` available (deferred — fetch via `ToolSearch("select:CronCreate")`).

## Lane Files

Two files per lane on disk:

```
{lane-dir}/{lane-name}/
├── prompt.md      ← lane instructions (read every cycle)
└── memory.md      ← lane-local cycle log
```

- **prompt.md** — full instruction set ([8-block structure](../reference/prompt-template.md)): mission, read list, gate, assess, act, authority, checkpoint.
- **memory.md** — lane-local cycle log, one line per cycle. A new session reads it for local orientation, then resumes shipped work from the owning `PLAN.md` plus matching publish ledger row carrying the durable proof/resume packet.

## Creation

```
CronCreate(
  cron: "8,38 * * * *",   // fires at :08 and :38
  prompt: "**Claude cron: {name} (every 30 min)**\n\nInstructions live at {lane-dir}/{name}/prompt.md. Read that file FIRST..."
)
```

The cron prompt is a thin wrapper: it points to `prompt.md` and lists constraints to honor even if `prompt.md` is missing. Heavy logic lives on disk. Returns a job ID (e.g. `ee960240`) for `CronDelete`.

## Cycle Execution

Each fire injects the prompt into the live session; the agent runs one vidux cycle:

```
0. CONFIG   `python3 scripts/vidux-config.py check --json`; keep local config separate from checked-in example fallback.
1. READ     prompt.md -> memory.md (last 3) -> git fetch + status -> PLAN.md -> INBOX.md
2. PRE-HOOK Run `scripts/vidux-doctor.sh --json`.
3. GATE     Dirty tree not mine? -> [QC] exit. 3x stuck? -> [blocked]. Main CI red? -> fix.
4. ASSESS   Priority: CI red -> PR fix -> PR merge -> resume in_progress -> next pending -> filler audit
5. ACT      Worktree per code change. Set `VIDUX_RUNTIME=claude` for Claude workers, `VIDUX_RUNTIME=cursor` for Cursor-attributed workers.
6. VERIFY   Build + tests pass; visual check for UI.
7. CHECKPOINT  Update the owning PLAN.md status/Progress and emit the matching publish ledger row with task id, proof, handoff status, files claimed, and next-agent resume. Append the lane-local memory line; commit/push only after the plan/ledger packet exists.
```

### Post-push defer

After pushing a PR, the lane MUST NOT merge in the same cycle. Merge eligibility: CI green + ≥1h since last fix-push + no unresolved required findings.

## Session Cycling

Sessions are disposable (death causes: multi-account rotation, laptop sleep, compaction pressure, manual `/resume`, crash). When a session dies, the cron dies with it; lane files (`prompt.md` + `memory.md`) survive as instructions plus lane-local cycle log. Shipped-cycle state lives in the owning `PLAN.md` plus matching publish ledger rows. On a new session:

1. Re-schedule `CronCreate` with the same prompt pointing to the same `prompt.md`.
2. First cycle reads `memory.md` for lane-local orientation.
3. Lane resumes from disk using lane files plus repo plan/ledger proof packets.

Core invariant: **lanes persist, sessions cycle.**

## Session GC

Without GC, session JSONLs grow unbounded and `/resume` slows. A mandatory `session-gc` lane runs hourly (or every 30 min) to:

1. Delete main session JSONLs older than 3 days.
2. Delete subagent JSONLs older than 1 day.
3. Measure current session size + growth rate.
4. Emit a `[CYCLE SIGNAL]` when the session exceeds 40 MB.

The GC lane uses an operator-provided JSONL cleanup helper and NEVER touches lane files, ledger, or git repos. This repo documents the pattern; it does not ship the pruning script. The 40 MB `[CYCLE SIGNAL]` is a recommendation to `/resume` fresh, not an automatic action — the operator decides when to cycle.

Growth (measured): checkpoint-only ~0-1 MB; filler audit ~1-2 MB; ship cycle (worktree + build + PR) ~16 MB.

## Lane Count

Hard cap: **6 lanes per session.** Evidence: more causes worktree contention + JSONL bloat (measured). Default fleet per repo:

| Lane | Role | Cadence |
|---|---|---|
| `<repo>-coordinator` | Ship + fix CI + merge PRs + archive PLAN.md | ~30 min |
| `session-gc` | Delete old JSONLs, measure growth | 30-60 min |

Add burst lanes only when drift is measured ([platforms.md](platforms.md) for the decision tree).

## Auto-Expire

All `CronCreate` jobs auto-expire after **7 days**. To run longer, re-schedule the crons in a new session.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Cron not firing | Session died or auto-expired | Re-schedule `CronCreate` |
| Lane stuck on same task | 3x stuck rule not triggered | Check memory.md for 3+ consecutive same-task entries |
| Dirty tree blocking ops | Another session's uncommitted work | `[QC] concurrent-cycle` exit; wait |
| JSONL growing fast | Ship cycles or ScheduleWakeup bloat | Prefer `CronCreate` over `ScheduleWakeup` for 10+ fires |
| Branch hijack after commit | `lint-staged` stash interference | Verify `git branch --show-current` after commit |

## See Also

- [Platform Comparison](platforms.md) — Claude Code vs Codex
- [Codex Lifecycle](codex-lifecycle.md) — the Codex equivalent
- [Prompt Template](../reference/prompt-template.md) — the 8-block structure
