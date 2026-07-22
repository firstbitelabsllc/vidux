# Fleet Operations Reference

Operations manual for running a fleet of vidux automations. Loaded by `/codex` and `/claude` when managing fleets. Core SKILL.md covers doctrine and planning; this doc covers the multi-automation coordination layer.

---

## Cross-Lane Awareness

> An automation that doesn't know what its siblings are doing is a solo agent pretending to be part of a fleet.

Every automation MUST read sibling state during its READ step -- structural, not optional. Before acting:

1. **Sibling memory scan** -- Read the last note from every sibling automation's memory file (e.g., `~/.codex/automations/*/memory.md` for Codex, `~/.claude-automations/*/memory.md` for Claude). Know what shipped in the last hour and what surfaces are claimed.

2. **Hot-files check** -- Read `.agent-ledger/hot-files.md` in the target repo. If another lane is actively touching files you are about to touch, yield or coordinate. Two lanes editing the same file in one cycle produces merge conflicts that burn the next cycle.

3. **Fleet duplicate detection** -- If your planned work overlaps with what a sibling just shipped, skip it. Don't re-fix or re-scan. The dedup check is a single pass over sibling memory notes -- seconds spent, cycles saved.

**Where this goes in the harness prompt:** Immediately after the Authority/read-order block and before Execution -- gate, then authority, then siblings, then act. Ledger reads and hot-files checks are as mandatory as reading PLAN.md.

**Real failure:** Five Beacon radars polled the same empty queue without knowing each other existed. `acme-web` didn't know `acme-backend` just fixed the same surface; both shipped competing branches and the merge cost more than the original fix.

**Orchestrator role:** Detect fleet-level patterns (6 idle automations = dead fleet, 3 lanes touching same file = collision), not wordsmith individual prompts.

---

## Trunk Health

> A dirty or diverged canonical checkout is a fleet-level infrastructure failure, not a per-task blocker. Detect it in 10 seconds, not after 45 minutes of deep work.

Every automation works in a worktree and must leave a durable handoff packet before the local worktree is discarded: owning PLAN.md update plus publish ledger row first, then branch + PR as git transport and review handles. If the canonical checkout is dirty, diverged, or behind origin, that PR flow starts from a stale base and the lane burns time on avoidable conflict resolution.

Overnight this compounds: 10 automations x 8 hours = 80 cycles producing stale branches or PRs nobody can safely land. vidux-loop.sh counts these as "unproductive" because no PLAN.md task state changed, triggering auto-pause, which makes it worse.

### Trunk health check (first 10 seconds of every writer gate)

```bash
git -C <repo> status --short --branch
git -C <repo> rev-list --count HEAD..origin/main
git -C <repo> rev-list --count origin/main..HEAD
```

- If diverged >5 commits: escalate immediately ("trunk diverged, needs human reconciliation") instead of doing deep work on a stale base.
- If dirty: escalate ("trunk dirty, unsafe to merge").

### Plan file integrity

A "clean" trunk (no dirty files, no divergence) can still be broken if PLAN.md was clobbered by a stale worktree merge. A dirty trunk is visible; a clobbered plan is invisible -- tasks silently vanish, automations park on `auto_pause_recommended` because their tasks no longer exist, and the plan looks "complete" when it is destroyed. The trunk health check must verify task count stability, not just git status.

### Branch pushes are productive output

An automation that ships code to a branch, pushes it to origin, opens or updates the PR, and records the resume point is shipping. The unproductive streak counter must not penalize this -- the work exists, it just needs nursing or merge eligibility.

---

## PR Sweep

The lead writer or coordinator sweeps open automation PRs. `gh pr list` is the transport/review recovery index for branch-backed work; the owning PLAN.md plus matching publish ledger row remains the durable shipped-work recovery packet. A branch with no PR is drift. Without a sweep, lanes keep creating fresh work while already-shipped work rots in review or sits only on a branch.

### Protocol (run during the lead writer's READ step, before popping new tasks)

**a. Scan open automation PRs first:**
```bash
git fetch origin
gh pr list --state open --json number,title,headRefName,isDraft,reviewDecision,statusCheckRollup,url
```

**b. If an open automation PR exists:** nurse or merge it before creating fresh branch work. Follow the normal queue order: failing checks first, then eligible merges, then new tasks.

**c. If a branch exists without a PR:** create the PR or record the blocker immediately. Branch-only work is invisible recovery state and should be treated as drift.

**d. If merge is unsafe (conflicts, red CI, unresolved required findings):** do not force it. Record the conflicting PR or branch in the automation's memory note and skip it. A human or the owning automation resolves it.

**e. Why this is non-optional:** 80 cycles overnight, each pushing a branch or PR with nobody sweeping, makes the queue look "active" while trunk stops moving. The sweep keeps PR-backed work visible and prevents branch-only drift from compounding.

---

## Worktree Handoff Protocol

Cron agents are stateless but worktrees are not. When a session dies mid-task inside a worktree, the next cycle only has what was recorded in the PR, plan, or lane memory. Without this protocol, agents duplicate work or leave invisible local state behind.

### Rules

1. **Register on entry when local state will survive the cycle.** When a cron agent creates or keeps a worktree after the PR is open, it SHOULD add an `## Active Worktrees` section to PLAN.md (or append to an existing one) with:
   ```
   - branch: <branch-name> | path: <worktree-path> | task: <Task N description> | status: <in_progress|blocked>
   ```

2. **Read before starting.** If `## Active Worktrees` exists, every cron cycle reads it during the READ step (after Decision Log, before git log). If an entry exists for the current task, resume the worktree instead of creating a new one.

3. **Remove on completion.** When worktree work is merged, handed off fully via PR, or abandoned, delete the entry from `## Active Worktrees` and add a Decision Log line:
   ```
   - [WORKTREE] [date] Merged/abandoned <branch>. Reason: <why>.
   ```

4. **Stale detection.** If a worktree entry persists across 3 cron cycles with no progress (same status, no new commits on the branch), mark the associated task `[blocked]` with `[Blocker: stale worktree -- no progress in 3 cycles]` and note it in the next Progress entry.

5. **Plan file merge safety.** Any merge touching PLAN.md must verify the task count did not decrease unless tasks were explicitly marked `[completed]` and archived. PLAN.md is append-mostly: tasks are added or archived, never silently removed. Before completing such a merge, compare task counts:
   ```bash
   pre=$(git show origin/main:path/to/PLAN.md | grep -c '^\- \[')
   post=$(grep -c '^\- \[' path/to/PLAN.md)
   [ "$post" -lt "$pre" ] && echo "PLAN CLOBBER: task count dropped from $pre to $post"
   ```
   If the count drops, abort the merge and escalate. Worktree branches should minimize PLAN.md edits -- confine changes to their own task status updates.

6. **PR sweep role.** In a fleet, open PRs are the transport/review recovery index complementing the owning plan plus publish ledger packet. Branches without PRs are drift. The lead writer or coordinator owns the sweep -- see "PR Sweep" above.

### Worktree PR handoff rule (for prompts)

Every automation using `execution_environment = "worktree"` MUST hand off durable state before exiting: owning plan plus publish ledger packet first; branch + PR are the transport and review handles. Without this, the runtime creates a fresh worktree each cycle and the old one becomes invisible local state.

**The rule (add to block 7 -- Execution in the prompt):**
```
WORKTREE RULE: Before stopping, update the plan, emit publish ledger, push the branch, and open/update the PR.
- First update the owning PLAN.md Progress/Tasks/Drift Log with what changed, proof, `handoff_status`, files claimed, and the next-agent resume point.
- Then emit the ledger emitter's `--event publish` with non-empty `--summary`, `--task-id`, `--plan-path`, `--proof`, `--handoff-status`, `--resume`, changed-file `--file` entries, and path-like `--claim` entries for claimed files; keep the eid in `$LEDGER_EID`.
- If work is complete and tests pass: push branch, build the PR body with `scripts/vidux-pr-body.py` including `--summary`, `--plan-path`, `--proof`, `--handoff-status`, `--ledger "$LEDGER_EID"`, `--file-claimed`, `--resume`, and the three `--review-pass` self-scrutiny entries, open a ready PR, and record the resume point in the PR body.
- If work is incomplete or a gate is still missing: emit the publish row with `handoff_status=in_progress` or `needs_review`, push branch, open/update PR as draft, and record the exact next step.
- If work conflicts or is unsafe: record why in memory/PLAN.md and keep the branch name visible.
- NEVER push directly to the default branch from an automation worktree.
- NEVER exit with only local worktree commits unless the blocker is recorded.
```

After a branch is pushed and the resume point recorded, the worktree is disposable. If a lane keeps it for PR nursing, keep its `## Active Worktrees` entry current; otherwise remove the entry and rely on the plan/ledger packet plus `gh pr list` for transport recovery.

**Detecting and classifying local worktrees:**
```bash
python3 scripts/vidux-worktree-gc.py --base origin/main
python3 scripts/vidux-worktree-gc.py --json --base origin/main
python3 scripts/vidux-worktree-gc.py --owner-review-markdown --base origin/main
```

The classifier separates worktrees into `open_pr`, `merged_clean`, `dirty`, `closed_unmerged`, `unmerged_no_pr`, and `primary`. JSON and text output include a top-level `cleanup_decision` stating whether owner approval is required before guarded apply, or whether owner review is still required for non-removable rows. The decision's JSON carries `guarded_removal_available`, `owner_approval_required_before_apply`, and `cleanup_approval_status`, plus `owner_review_items` with `commits_not_in_base`, `last_commit_subject`, `last_commit_date`, `last_commit_age_days`, and safe `review_command` inspection commands. `safe_cleanup_items` lists the exact `merged_clean` rows eligible for guarded cleanup after approval; the decision and safe rows carry `cleanup_approval_status=required_before_apply` when any `merged_clean` row exists. `--owner-review-markdown` prints non-removable and safe cleanup rows as a compact packet with commit evidence, last-activity evidence, and an approval-required column. Only `merged_clean` worktrees are removable, and only after owner approval.

**Cleanup:**
1. Run `git fetch --prune origin` so `origin/main` and PR refs are fresh.
2. Run `python3 scripts/vidux-worktree-gc.py --base origin/main`.
3. Inspect any `dirty`, `closed_unmerged`, or `unmerged_no_pr` rows, using `--owner-review-markdown` when a handoff packet is useful. These require a human or lane-owner decision. If the packet includes safe cleanup rows, review those concrete paths and record owner approval before running the guarded apply command.
4. After owner approval for the concrete safe rows, remove safe local-only worktrees explicitly: `python3 scripts/vidux-worktree-gc.py --base origin/main --apply --yes`.
5. Run `git worktree prune` afterward to remove stale metadata entries.

---

## Writer vs Scanner Gate Patterns

Every vidux automation is either a **writer** or a **scanner**. The distinction is structural -- it determines which gate pattern the harness uses, how the agent decides "nothing to do," and what the quick check exit looks like.

| | **Writer** | **Scanner** |
|---|---|---|
| **Purpose** | Execute tasks from a PLAN.md queue | Inspect codebase/product for issues |
| **Examples** | acme-backend, release-train, beacon-builder | localization radar, UX radar, flow radar, content radar, quality audit |
| **State source** | PLAN.md task queue (pending/in_progress/completed) | The codebase itself (files, git history, runtime output) |
| **"Nothing to do" means** | All tasks completed/blocked, no pending work | No files changed since last scan AND last N scans found no issues |
| **Gate** | Quick check gate: runs `vidux-loop.sh`, checks plan state | SCAN gate: checks git changes + last scan results |
| **Deep work** | Pop next task, execute, verify, checkpoint | Full scan of watched paths, report findings, checkpoint |

**Why this matters:** A scanner on a quick check gate checks if "all tasks are done" in PLAN.md and exits -- without ever looking at the codebase it is supposed to scan. Scanners do not pop tasks; they look at reality.

### Gate selection guide

```
What does the automation DO?
     |
     +--> Executes plan tasks, has vidux-loop.sh --> Quick check (With-Vidux)
     |         e.g., acme-web, beacon-release-train
     |
     +--> Executes tasks, no vidux-loop.sh      --> Quick check (Standalone)
     |         e.g., acme-asc (reads repo plan), acme-launch-loop (reads git state)
     |
     +--> Inspects codebase or product           --> SCAN
     |         e.g., acme-localization-pro, ux-radar, security-scanner
     |
     +--> Not sure                               --> Default to Quick check (Standalone)
              Writer that finds nothing just exits. Scanner on Quick check gate
              is permanently dead.
```

**The critical asymmetry:** A writer on the wrong plan file exits cleanly and wastes one cycle. A scanner on a quick check gate checks plan state instead of codebase state, finds "nothing to do," and is permanently dead -- it never runs. That asymmetry is why the default is writer, not scanner.

---

## Quick Check Gate (Detailed Spec)

### With-Vidux variant (~850 chars)

Use when the automation loads `$vidux` and has access to `vidux-loop.sh`. Standard variant for fleet automations.

```
Quick check gate (run FIRST, before any other work):
1. Run: bash scripts/vidux-loop.sh <plan-path>
2. Read the JSON output. If ANY of these are true, checkpoint and exit immediately:
   - action is "blocked" or "auto_blocked" or "stuck" or "escalate"
   - type is "all_blocked" (all remaining tasks are blocked — escalate to human)
   - action is "complete" AND type is "done" AND queue_starved is false
   - type is "empty" (no tasks in plan)
   - auto_pause_recommended is true
   - blocker_dedup is true (same blocker reported 3+ times -- stop wasting cycles)
   - bimodal_gate is "blocked"
   Write a 1-line memory note: "[QC] <date> <reason>. No deep work."
   Do NOT read authority files, load skills, or do any other work. Exit now.
3. Read the last 3 memory notes. If the top note is a [QC] exit with the
   same reason as this run's JSON, exit with: "[QC] <date> unchanged. No deep work."
4. WORKTREE CHECK: Before creating a new worktree, check if a previous
   worktree for this lane has unmerged commits:
   git worktree list | grep "<this-lane-id>"
   If found with unmerged commits: resume it (cd into it), do not create new.
   If found but work is stale/superseded: remove it first, log in Decision Log.
5. If actionable work exists: proceed to full execution below.
Budget: steps 1-4 must complete in under 60 seconds.
```

### Standalone variant (~800 chars)

Use when the automation does not have `vidux-loop.sh` or operates outside the vidux plan model.

```
Quick check gate (run FIRST, before any other work):
1. Read the last 3 notes from this automation's memory file.
2. If the most recent note says any of: "blocked", "nothing to do", "unchanged",
   "no pending", "waiting on human", "same blocker" -- and it was written less
   than 2 hours ago -- exit immediately with a 1-line note:
   "[QC] <date> Same state as last run (<quote reason>). No deep work."
   Do NOT read authority files, load skills, or gather evidence. Exit now.
3. Read the single primary state file (plan, queue, or tracker). Count actionable
   items. If zero actionable items and no new items since the last note, exit with:
   "[QC] <date> No new work. No deep work."
3.5. If zero items in the primary file, run the five-point idle scan:
   INBOX.md -> sibling memory -> git log on owned paths -> blocked task recheck ->
   codebase TODO/FIXME scan.
   If any scan finds work: add to plan, proceed to execution.
   If all scans clean: exit with "[QC] <date> Five-point scan clean. No deep work."
4. WORKTREE CHECK: Before creating a new worktree, check if a previous
   worktree for this lane has unmerged commits. If found: resume, merge, or abandon.
5. If actionable work exists: proceed to full execution below.
Budget: steps 1-3 must complete in under 60 seconds.
```

---

## SCAN Gate (Detailed Spec)

Use for scanner and radar automations -- agents whose job is to observe, detect, and report, not to execute plan tasks. The SCAN gate checks reality (git history, file state, live surfaces) instead of plan state.

```
SCAN gate (run FIRST, before any other work):
1. Read last 3 memory notes from this automation's memory file.
   If the same "no issues found" verdict appears 3 consecutive times with no
   codebase changes between them, exit with:
   "[SCAN] <date> unchanged, no new issues. No deep work."
   Do NOT read authority files, load skills, or do any other work. Exit now.
2. Check for changes: git log --since="<timestamp of last scan>" -- <watched_paths>
3. If no changes since last scan AND last scan found no issues -> exit with:
   "[SCAN] <date> no changes to <watched_paths> since last scan. No deep work."
4. Otherwise -> proceed to full scan below.
Budget: steps 1-3 must complete in under 60 seconds.
```

**Key differences from quick check:**
- No `vidux-loop.sh` call. Scanners do not read plan state.
- The staleness check is git-based (`git log --since`), not plan-based (`next_action`).
- The "3 consecutive identical verdicts" rule prevents a radar from endlessly re-scanning unchanged code.
- `<watched_paths>` scopes the change detection to the paths the radar actually cares about (e.g., `src/` for a code scanner, `assets/locales/` for a localization radar).

**Exits when:** the radar found nothing new and the watched paths have not changed. **Proceeds when:** watched paths got new commits since the last scan, or the last scan found issues needing re-verification.

---

## Fleet Health Orchestrator Pattern

An orchestrator managing multiple automations must operate at fleet level, not prompt level. Tightening one radar prompt while 6/11 automations are idle is mid-zone work.

### When to use a coordinator

Any fleet with 5+ automations, or any fleet where 3+ automations share the same plan or target repo. Below that threshold, individual gate logic (quick check/SCAN) is sufficient.

### The 5-step fleet scan

1. **Read ALL automation memories in one pass** -- scan every sibling memory file (e.g., `~/.codex/automations/*/memory.md` or `~/.claude-automations/*/memory.md`) before any action. Never inspect one at a time.

2. **Classify each automation:**
   - SHIPPING -- actively producing commits
   - IDLE -- gate-exiting with no work
   - BLOCKED -- same blocker 2+ cycles
   - CRASHED -- auth failure, MCP disconnect
   - MID-ZONE -- 3-8 min sessions with no output

3. **Detect fleet-level patterns:**
   - N idle automations on the same plan = queue starvation (the plan has no work, not the automations)
   - Same blocker across N automations = escalation needed (human or infra fix, not retry)
   - N automations touching the same files = collision (coordinate or yield)
   - Scanner using a quick check gate = wrong gate type (scanners use SCAN)

4. **Take fleet-level action:**
   - Pause idle clusters instead of retrying them individually
   - Create escalation tasks instead of re-reporting the same blocker
   - Fix gate mismatches (scanner -> SCAN, writer -> quick check)
   - Redistribute work when queues are imbalanced across lanes

5. **Report a fleet scorecard** every cycle: N shipping / N idle / N blocked / N crashed / N mid-zone. The scorecard is the orchestrator's primary output -- not prompt edits.

6. **Detect trunk health** -- Before any fleet-level action, check that canonical checkouts in target repos are clean, current, and not diverged. If dirty/diverged, escalate as an infrastructure blocker affecting all dependent lanes. Cluster it as one root cause -- do not report the same trunk blocker N times per N automations.

### Anti-patterns

- Editing individual prompts while the fleet is dead (mid-zone work at orchestrator level)
- Retrying the same blocker across 3+ cycles without escalating
- Spinning up new automations without checking the existing fleet
- Treating all idle automations identically -- idle-because-queue-empty is different from idle-because-gate-misconfigured

---

## Circuit Breakers, Auto-Pause, and Bimodal Enforcement

### Bimodal gate (Doctrine 10)

> Healthy runs are bimodal: <2 min (nothing to do, checkpoint and exit) or 15+ min (real work, full e2e cycle). Mid-zone runs (3-8 min) are the disease.

Every harness must say "if you checkpoint in under 5 minutes and pending work remains, you stopped too early -- pick up the next task." Never write "do one task and exit"; always say "keep working until the queue is empty or a hard external blocker stops you." Quick exits are healthy when nothing is pending; mid-zone exits are stuck agents masquerading as polite ones.

Fleet data (2026-04-07): 32% of automation sessions land in the 3-8 min mid-zone. Target: <15%.

### Deep-work mid-zone kill

The quick check gate prevents mid-zone on the way in. This rule prevents it during deep work:

> If 3+ minutes pass in deep work mode with no file write and no active research query, checkpoint what you have and exit.

Do not re-read the plan, re-assess state, or "think about what to do next" -- that is quick check work inside a deep run. Either write a file or exit. `vidux-loop.sh`'s circuit breaker enforces this from outside (blocks deep work after N idle cycles), but the agent should self-enforce too.

### Circuit breaker and auto_pause deadlocks

Safety mechanisms can become traps. The circuit breaker opens after N idle cycles and blocks execution -- but if execution is blocked the automation stays idle, so CB stays open. Same loop with auto_pause.

**Fix:** Ensure the Progress section carries shipping signal keywords when work actually shipped (`shipped`, `commit`, `fixed`, `merged`, `created`, `built`, `added`, `wrote`, `pushed`). Stale Progress entries make the safety mechanisms fire on ghosts.

### Stuck-loop mechanical enforcement

`vidux-loop.sh` enforces stuck detection without relying on LLM judgment:

1. A task appearing in 3+ Progress entries while still `[in_progress]` is stuck.
2. Default read mode reports `action: "stuck"` and, when another runnable row exists, `next_action: "surface_switch"` with a `surface_switch` candidate.
3. If `VIDUX_LOOP_AUTO_BLOCK=1`, the script flips the task from `[in_progress]` to `[blocked]` in PLAN.md.
4. With auto-blocking enabled, a `[STUCK]` entry is appended to the Decision Log with the date and last progress note.
5. The harness forces a surface switch — no human gate. If auto-blocking was enabled, the blocked task is terminal; if new evidence surfaces (observed signal, PR comment, queue re-sort), add a replacement task with a Decision Log entry rather than reviving the blocked one.

If PLAN.md format is unexpected (missing sections, unusual markup), the enforcement degrades gracefully: stuck detection still reports `stuck: true` in JSON, but the auto-block write is skipped unless explicitly enabled and mechanically safe. No data is lost.

---

## INBOX.md Protocol (Radar -> Writer Inbox)

Scanners find issues, writers fix them, the inbox bridges the two. Without it, radars observe problems that never reach the writer's queue while writers check an empty PLAN.md.

### How it works

1. `INBOX.md` lives alongside `PLAN.md` in the project directory.

2. Scanners append findings as timestamped entries (append-only for scanners):
   ```
   - [YYYY-MM-DD] [scanner-id] Finding: <description> [Evidence: <file:line or proof path>]
   ```

3. Writers check `INBOX.md` during their READ step, **before** looking at PLAN.md tasks.

4. If an inbox entry is actionable, the writer promotes it to a `[pending]` task in PLAN.md and deletes the inbox entry.

5. If not actionable, the writer annotates it with `[SKIP: reason]` and leaves it.

6. `INBOX.md` is append-only for scanners, read-write for writers. Scanners never edit or delete entries.

7. Maximum 20 entries. If full, archive the oldest non-skipped entries to `evidence/` before appending. A full inbox means the writer is not keeping up -- a fleet health signal, not a formatting problem.

### INBOX.md template

```markdown
# Inbox -- [Project Name]

Scanner findings awaiting writer promotion.

- [YYYY-MM-DD] [scanner-id] Finding: <description> [Evidence: <path>]
- [YYYY-MM-DD] [scanner-id] Finding: <description> [Evidence: <file:line>]
- [YYYY-MM-DD] [scanner-id] Finding: <description> [SKIP: reason]
```

### Why not write directly to PLAN.md?

Scanners are read-only scouts (Doctrine: role boundary). Letting them mutate the task queue breaks the scanning/execution separation. The inbox is a buffer that preserves that boundary while closing the feedback loop. (This is the radar pattern -- distinct from the deprecated observer pattern, which audited a writer's own state: scanners feed the queue, observers reported on drift.)

---

## Merge Conflict Protocol

> When two worktrees reconcile onto the same trunk, both sides' work must survive. A conflict resolved by deleting one side is not a resolution -- it's data loss.

1. **Try additive merge first.** If both sides added different things (new tests, new tasks, new functions), keep both. Most conflicts are additive, not contradictory.
2. **If genuine conflict (same line, different intent):** Check commit timestamps. The more recent change is likely more correct -- it was written with knowledge of the earlier state.
3. **If tie (same timestamp, both valid):** Read both versions. Pick the one that better serves the mission. Never coin-flip.
4. **LOG every resolution.** Add a Decision Log entry: `[MERGE] <date> Conflict on <file>. Kept <branch>'s version because <reason>. Dropped: <summary>.`
5. **Never silently resolve.** A merge that touches 10 files and resolves 3 conflicts without a single log entry is suspicious. The log IS the proof that no work was lost.
6. **PLAN.md special rule:** Task count must not decrease (worktree handoff rule 5). A merge that reduces the task count without `[completed]` entries is a plan clobber, not a resolution.

### Known failure: Plan clobber via stale worktree merge

**The pattern:** A worktree branch carries a PLAN.md edit (e.g., a single task status). While it lives, origin/main advances -- 20+ new tasks added. When the branch merges, the PLAN.md conflict resolves in favor of the branch version, silently deleting every task added since the branch diverged.

**Why it's dangerous:** The plan looks "complete" -- no pending tasks, no errors, clean git status -- but it is clobbered. Automations whose tasks vanished enter `auto_pause_recommended` because their task IDs no longer exist, and park silently for hours. No alarm fires because from the plan's perspective there is nothing to do.

**Mitigation:**
- PLAN.md is append-mostly. Worktree branches should confine PLAN.md edits to their own task's status line, never rewrite the file.
- Pre-merge task count validation (see Worktree Handoff Protocol, rule 5).
- If a worktree branch is long-lived (>1 week), rebase it against origin/main before merging to pick up new tasks.
- Any merge that decreases the task count without corresponding `[completed]` entries is suspect and must be manually reviewed.

---

## Prompt Structure for Fleet Automations

Every automation harness prompt follows this eight-block structure, in order:

```
1. MISSION        -- One line. User-visible goal. No implementation details.
2. SKILLS         -- Load skills: $vidux, $pilot, $picasso, etc.
3. GATE           -- Quick check or SCAN. Runs FIRST. Decides work/exit in <60 sec.
4. AUTHORITY      -- Read order for plan files. Primary state file is #1.
5. CROSS-LANE     -- Read sibling memory notes + hot-files. Dedup, yield, skip.
6. ROLE BOUNDARY  -- What this lane owns. What belongs to siblings.
7. EXECUTION      -- How to do the work. Mid-zone kill rule. Queue drain rule.
                     PR-first worktree closeout rule.
8. CHECKPOINT     -- Memory format. Lead line. What to leave explicit. Worktree state.
```

**Why this order matters:** The gate must run before authority reads -- an agent that reads 6 authority files before discovering it has nothing to do wasted 90 seconds. Cross-lane comes after authority but before execution, so the agent never starts work without knowing fleet state.

### Size guidance

**Target: 2000-3000 characters.**

| Range | Signal |
|-------|--------|
| < 1500 chars | Missing a block. Check: gate? cross-lane? role boundary? |
| 1500-3000 chars | Healthy. Each block is present and concise. |
| 3000-4000 chars | Audit for doctrine restatement or verbose gate logic. |
| 4000+ chars | Almost certainly restating things the skill files already provide. |

### Common prompt mistakes

1. **Gating on the wrong plan file.** The gate reads the file where actionable work items actually live.
2. **Scanner using a quick check gate.** Permanently dead automation. Use SCAN gate.
3. **Circuit breaker / auto_pause deadlocks.** Ensure Progress has shipping signal keywords.
4. **Restating doctrine in the prompt.** Agent loads doctrine via `$vidux`. Don't repeat it.
5. **Vague authority references.** Every authority file gets an absolute path and a role label.
6. **Missing mid-zone kill.** One line that saves entire cycles.
7. **Missing role boundary.** Causes drift into adjacent work and merge conflicts.
8. **Exiting on empty queue without scanning.** The five-point idle scan above is required before any "nothing to do" exit.
