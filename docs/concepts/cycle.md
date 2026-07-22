# The Cycle

Every agent session — human-triggered or cron — runs five steps in order. No step is skippable.

```
READ → ASSESS → ACT → VERIFY → CHECKPOINT → (next session) → READ → ...
```

**publish packet** = ledger row carrying task id, plan path, proof, handoff status, files claimed, path-like claims, next-agent resume. Emitted via the configured ledger emitter's `--event publish` for any branch/PR/release cycle, before the work leaves the machine.

## Step 1: READ

Read:
- `PLAN.md` — queue/planning authority: tasks, decisions, constraints, progress
- `INBOX.md` — unprocessed findings from humans or external tools
- Latest publish ledger rows — shipped-cycle proof and resume metadata
- `git log --oneline -10` — recent history
- `git diff` — uncommitted work from a crashed session

**Crash recovery:** `git diff` shows uncommitted work from a dead session → inspect it, resume the owning plan row, checkpoint through the plan. Commit only when code changed.

**Time budget:** 60-90s. Longer = plan too large; add a GC task.

## Step 2: ASSESS

```
IF plan has [in_progress] task:
  → Resume it (prior session died mid-task)
  → Verify, then set [completed] or [blocked]

ELIF plan has [pending] tasks WITH evidence:
  → Set first [pending] to [in_progress], execute, verify, checkpoint

ELIF plan has [pending] tasks WITHOUT evidence:
  → Gather evidence locally, update plan in place

ELIF plan is empty or missing:
  → Research locally, draft initial PLAN.md

ELIF all tasks [completed]:
  → Verify final state. Mark mission complete.
```
(Plan/evidence/research updates stay local — no commit until code ships.)

**Readiness score (7/10 threshold).** Before coding:
- Root cause identified? (+2)
- Impact map complete? (+2)
- Fix spec has file:line locations? (+2)
- Test cases defined? (+2)
- Known unknowns documented? (+2)

≥ 7 → code. < 7 → gather more evidence.

## Step 3: ACT

Execute until the queue empties, a blocker hits, or context runs out.

**Queue order:**
1. `[in_progress]` resumes first — a prior session died mid-task
2. Dependencies before dependents — `[Depends: Task N]` blocks until N is `[completed]`
3. Pick highest-impact unblocked task. Re-sort when new observed evidence arrives; note the reorder in the next Progress entry.

**Mid-zone kill:** 3+ minutes, no file write → exit. Catches plan-reading loops.

**Every agent is a worker.** Queue empty? Don't exit — scan:
1. INBOX.md for unprocessed findings
2. Owned paths for issues
3. git log for recent changes needing follow-up
4. Blocked tasks for resolved blockers

Scan finds work → add as `[pending]`, execute. All scans clean → checkpoint and exit with proof of what was scanned.

## Step 4: VERIFY

Never assert "it works." Prove it.

**All work:**
- Build passes
- Tests pass
- No regressions in related areas

**UI work:**
- Screenshot of the feature working
- Screenshot of the before state (if available)
- Simulator or browser proof — "the build passes" is NOT sufficient

**Compound-task gate.** Before marking an investigation `[completed]`:
- Fix Spec filled (not `(pending)`)
- All seven investigation sections complete
- Parent task in PLAN.md can flip to `[completed]`

## Step 5: CHECKPOINT

Every cycle ends with a plan/progress checkpoint. Publishable branch, PR, or release work also emits the publish packet.

**Commit format (code changed):**
```
vidux: [what you did]
```

Examples:
```
vidux: add rate limiting to login endpoint
vidux: investigation — root cause for checkout double-charge
vidux: recover uncommitted work from crashed session
```

**Progress entry:**
```
- [DATE] What happened. Next: what's next. Blocker: if any.
```

**Reconcile planned vs actual:** Compare what the plan SAID with what `git diff` SHOWS. Diverge → update plan, note the divergence in the Progress entry.

## Stuck Detection

Same task in 3+ Progress entries while still `[in_progress]` → force a surface switch. In default read mode `vidux-loop.sh` reports `action: "stuck"` and a `surface_switch` candidate when another runnable task exists; auto-blocking and Decision Log mutation require `VIDUX_LOOP_AUTO_BLOCK=1`. Next cycle finds new evidence or the task stays blocked.

```markdown
## Decision Log
- [BLOCKED] [2026-04-15] Task 3 stuck 3 cycles. Tried: X, Y. Moving on.
```

## Push Authorization

Operational PR branch pushes are safe without asking only after the owning `PLAN.md` Progress/Tasks/Drift Log is updated AND the publish packet is recorded. Open PRs ready-for-review by default so configured review bots can run; use draft only for true WIP with a missing gate. Direct-to-main and destructive operations (force push, branch delete, `git reset --hard`) require explicit authorization plus the same publish propagation before transport.

## Escalation Statuses

A cycle exits with one of four statuses:

| Status | Meaning |
|---|---|
| `DONE` | All tasks complete, build passes, tests pass, plan/proof checkpoint recorded |
| `DONE_WITH_CONCERNS` | Work complete but something smells wrong — flagged for human review |
| `NEEDS_CONTEXT` | Blocked by missing information only a human can provide |
| `BLOCKED` | Hard blocker — same task failed 3 times or external dependency missing |
