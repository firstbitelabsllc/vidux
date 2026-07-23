# Automation Prompt Authoring

Reference for writing cron automation prompts (harnesses). Loaded by `/codex` and `/claude` when creating or updating automation prompts.

---

## Core Rule (Doctrine 8)

A cron prompt is a **stateless harness** -- it encodes the end goal and project-specific instructions the agent cannot infer. It never contains current state.

**The harness is the PROCESS.** The owning PLAN.md is the queue/planning authority, and matching publish ledger rows carry shipped-work proof/resume. Never mix current-state snapshots into the harness.

**IN the harness:** end goal, authority plan path, role boundary, design DNA, guardrails, skills to invoke.

**NEVER in the harness:** task numbers, cycle counts, progress summaries, branch names, file lists, implementation tasks, current blockers, or any snapshot of state.

One loop per project/mission. If a loop exists, refine it -- do not create a sibling.

---

## 8-Block Prompt Structure

Every harness follows these eight blocks, in this order. Rearranging or omitting blocks produces known failure modes.

```
1. MISSION        -- One line. User-visible goal. No implementation details.
2. SKILLS         -- Load skills: $vidux, $pilot, $picasso, etc.
3. GATE           -- Quick check or SCAN. Runs FIRST. Decides work/exit in <60 sec.
4. AUTHORITY      -- Read order for plan files. Primary state file is #1.
5. CROSS-LANE     -- Read sibling memory + hot-files. Dedup, yield, skip.
6. ROLE BOUNDARY  -- What this lane owns. What belongs to siblings.
7. EXECUTION      -- How to do the work. Mid-zone kill. Queue drain. PR-first worktree closeout.
8. CHECKPOINT     -- Memory format. Lead line. What to leave explicit. Worktree state.
```

**Why this order:** Gate runs before authority reads. An agent that reads 6 files before discovering it has nothing to do wastes 90 seconds. Cross-lane comes after authority but before execution so the agent never starts work without knowing fleet state.

---

## Writer, Radar, and Coordinator Roles

Fleet automations use one of three roles (see `/vidux` Part 2, `references/automation.md`, and `guides/fleet-ops.md`):

- **Writer** — ships code, executes plan tasks, merges. The default.
- **Radar** — read-only monitoring, evidence gathering, no code changes. Reports findings to INBOX.md for the writer to promote.
- **Coordinator** — fleet-level health: detects idle/stuck/colliding automations, adjusts focus.

**Gate pattern (writers):**
1. Trunk health check (dirty = escalate, diverged >5 = exit)
2. Read plan for [pending] tasks in this lane's scope
3. If tasks exist: execute them
4. If no tasks: scan owned surfaces for issues, fix what you find, add unfixable items as [pending] tasks
5. If all clean: exit with proof of what was scanned

Gate must complete in under 60 seconds. The full cycle (scan + fix) has no time limit — keep working until the queue is empty.

**Gate pattern (radars):** Use the SCAN gate (see `guides/fleet-ops.md`). Radars check git history and codebase state, not plan state. A radar on a writer's quick check gate is permanently dead.

**Key principle (docs/doctrine/DOCTRINE.md):** "Every agent finds work AND does work." Even radars are doers — they produce evidence, not empty reports. A radar that scans and finds nothing ships a checkpoint proving what was scanned.

---

## Size Guidance

**Target: 2000-3000 characters.**

| Range | Signal |
|---|---|
| < 1500 chars | Missing a block. Check: gate? cross-lane? role boundary? |
| 1500-3000 chars | Healthy. Each block is present and concise. |
| 3000-4000 chars | Audit for doctrine restatement or verbose gate logic. |
| 4000+ chars | Almost certainly restating things skill files already provide. |

**Where bloat hides:** doctrine restatement (the agent loads it via `$vidux`), verbose execution philosophy, authority listing files already loaded via skill tokens, inline explanations of why gate steps matter.

**The test:** Can you delete a sentence without changing the agent's behavior? If yes, delete it.

---

## Common Mistakes

1. **Gating on the wrong file.** Three of six automations gated on a meta-plan marked "done." The agent saw "complete" and exited before loading a single skill.
2. **Scanner with a writer gate.** Checks plan state, finds no tasks, exits. Never scans.
3. **Restating doctrine.** 500-1000 chars of "plan is truth" prose the agent already knows from `$vidux`. Delete it.
4. **Vague authority.** "Read the bug tracker" forces a search. Give absolute paths.
5. **Missing mid-zone kill.** Without "if 3+ min pass with no file write, exit," agents drift into plan-reading loops.
6. **Missing role boundary.** Agent drifts into sibling work, creates merge conflicts.
7. **Missing cross-lane.** Agent duplicates work a sibling just shipped.
8. **Empty queue = exit.** Wrong. `guides/fleet-ops.md`'s five-point idle scan is required before any "nothing to do" exit. Cite what was scanned.

---

## Prompt Amplification (Amp Flow)

When `/vidux` is invoked interactively, amplify the request before executing.

```
RAW INPUT -> GATHER -> AMPLIFY -> PRESENT -> [STEER...] -> FIRE -> EXECUTE
```

**GATHER** (10 sec max): git status/log, glob/grep keywords, check existing plans/automations, active tasks, recent evidence.

**AMPLIFY** -- detect mode from input:

| Signal | Mode |
|---|---|
| cron, automation, schedule, loop, recurring | **HARNESS** -- produce evergreen cron prompt per Doctrine 8 (every automation is a doer) |
| plan, project, investigate, research | **PLAN** -- produce mission description, no code |
| Everything else | **EXECUTE** -- produce specific, evidence-cited, actionable prompt |

**PRESENT**: Show amplified prompt in a box. End with "steer me or say fire."

**STEER**: "fire"/"go" = proceed. "closer" = minor tweak. "no" = major redirect. "add/drop X" = scope change. Max 5 rounds.

**FIRE**: Strip scaffolding, execute the amplified prompt as the task spec.

**Rules:** Real context only. Never hallucinate sources. If GATHER finds 3+ unrelated candidates, disambiguate. For HARNESS mode, never include task numbers, cycle counts, or progress -- state orientation lives in the owning PLAN.md plus matching publish ledger rows, not in the harness prompt.

**Skip amplification when:** cron automation running, `[in_progress]` task exists, user says "fire"/"go"/"continue".
