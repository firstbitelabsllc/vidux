# PLAN.md Structure

Every project has exactly **one PLAN.md**. Course corrections — even dramatic pivots — update the existing plan's Decision Log; they NEVER spawn a sibling plan (see Course Correction).

## Full Template

```markdown
# [Project Name]

## Purpose
Why this exists. One paragraph. User-visible goal.

## Evidence
What we know, cited with sources.
- [Source: codebase grep] file:line pattern
- [Source: GitHub PR #1234] "feedback or constraint"
- [Source: design doc] "architectural decision"

## Constraints
- ALWAYS: [things that must be true]
- NEVER: [things that are forbidden]

## Tasks
Ordered, with status tags and evidence citations.
- [pending] Task 1: description [Evidence: ...]
- [in_progress] Task 2: description [Evidence: ...]
- [completed] Task 3: description [Evidence: ...]
- [blocked] Task 4: description [Blocker: ...]

## Decision Log
Intentional choices that future agents must not undo.
- [DELETION] [date] Removed X. Reason: Y. Do not re-add.
- [DIRECTION] [date] Chose X over Y. Reason: Z.

## Drift Log
Optional structured record of implementation-time deviations (see Drift Log section below), recorded manually.

## Progress
Living log updated each cycle. Unexpected findings, concerns, and reorder
notes all live here — no separate Surprises or Open Questions section. If a
finding needs a task, promote it to a task.
- [Date] What happened. Next: what's next. Blocker: if any.
```

## Required Sections

All six required. Missing sections produce known failure modes:

| Section | What happens without it |
|---|---|
| Purpose | Agents optimize for the wrong goal |
| Evidence | Tasks are guesses; wrong fixes get shipped |
| Constraints | Agents violate hard requirements they weren't told about |
| Tasks | No queue — agents improvise unpredictably |
| Decision Log | Agents re-add deleted code or undo deliberate pivots |
| Progress | No history — agents can't tell what actually happened |

## Task Status FSM

```
pending → in_progress → in_review (optional) → completed
              ↓
           blocked    (terminal)
```

Status rules:
- Every task starts `[pending]`
- Only one task per lane is `[in_progress]` at a time
- `[in_review]` is optional for PR-backed work; docs-only and local-only plans can stay in the four-state flow
- `[completed]` is permanent — never revert to `[pending]`
- `[blocked]` requires a Blocker note and Decision Log entry
- `[blocked]` is terminal — replace with a new task rather than reviving

The docs and adapter layer understand `in_review`, but the core shell helpers are four-state-first: `scripts/vidux-status.py`, `scripts/vidux-loop.sh`, `scripts/vidux-checkpoint.sh` model only `pending`, `in_progress`, `completed`, `blocked`. Treat `in_review` as opt-in PR-state metadata unless your lane/tooling handles it.

**Inside `## Tasks`, every line starting with `- ` MUST be a task with a status tag.** Use numbered lists (`1. 2. 3.`) or headers for non-task content like rollout strategies or phase preambles.

## Task Format

```markdown
- [pending] Task N: Short description [Evidence: source:line or PR #] [Depends: Task M]
```

- **Status tag** (required) — `[pending]`, `[in_progress]`, `[in_review]` (optional), `[completed]`, `[blocked]`
- **Task number** (required) — `Task N:` for cross-referencing
- **Description** — short, action-oriented
- **Evidence citation** (required for all pending tasks before coding)
- **Depends** (optional) — blocks until the dependency is `[completed]`

## The Decision Log

The most important section for preventing agent loops. Stateless agents have no memory of WHY a previous agent chose something — without it, an agent that finds "missing" code re-adds it, undoing a deliberate deletion.

```markdown
## Decision Log
- [DELETION] [2026-04-17] Removed observer lanes. Reason: they added drift without catching bugs the writer could not already see. Do not re-add.
- [DIRECTION] [2026-04-26] Open operational PRs ready-for-review by default. Reason: review bots and CI gates do not reliably run on drafts.
- [BLOCKED] [2026-04-12] Task 3 blocked on a missing deploy credential. Replace it with a new task once the credential exists.
```

Entry types:
- `[DELETION]` — removed intentionally; don't re-add
- `[DIRECTION]` — a deliberate architectural or approach choice
- `[BLOCKED]` — a task that can't proceed without human intervention
- `[PIVOT]` — major direction change; marks obsolete tasks

## Drift Log

Optional but first-class. For unavoidable implementation drift, not random notes. A good drift entry says:

- what the plan said would happen
- what actually changed
- why the deviation was necessary
- how the parent plan now adapts
- what prevention hint to cache for similar future tasks
- which subplans were mirrored

Record the same drift entry in the parent plan and any named subplans. When a task is now stale, flip it to `[blocked]` with a Decision Log entry; when the drift creates follow-up work, add new task rows.

## Course Correction

Evidence changes → the plan changes. The procedure:

1. **Update the plan FIRST** — what changed, why, the new direction
2. **Record drift when implementation diverged** — append a `## Drift Log` entry in the parent plan (and mirror it into named subplans)
3. **Add a Decision Log entry** — `[DIRECTION]` or `[PIVOT]` with the reason
4. **Mark obsolete tasks** — `[blocked]` with a pointer to the new direction
5. **Add new tasks** — fresh `[pending]` tasks in the queue
6. **Then update the code** — derived from the new plan state

**NEVER spawn a sibling plan.** Justifying a new PLAN.md with "clean slate" or "this rewrite deserves its own home" is fabricated reasoning — stop. Update the existing plan.

Exception: a new PLAN.md is correct for a genuinely new project (different codebase, product, problem surface). "Rewrite acme-web from scratch" is the same project — one plan. "Build a new iOS app for Acme 2.0" might be a different project.

## Compound Tasks and Sub-Plans

A task that needs investigation before code gets a sub-plan:

```markdown
- [pending] Task 3: Fix payment flow [Investigation: investigations/payment-flow.md]
```

The `[Investigation: ...]` marker tells the agent: read the sub-plan before coding. No Fix Spec yet → investigation only, no code.

Sub-plans follow the seven-section investigation template (below).

**Status propagation:** L2 investigation's Fix Spec coded, tested, gated → parent task in L1 PLAN.md moves to `[completed]`. L2 with no Fix Spec → parent stays `[in_progress]`.

## Investigation Template

For complex bugs or surfaces with 2+ tickets:

```markdown
# Investigation: [surface name]

## Reporter Says        — exact quote from feedback
## Evidence             — files, related tickets, recent commits, repro steps
## Root Cause           — the specific code path, not symptoms
## Impact Map           — other UI paths, other tickets, state flow
## Fix Spec             — file:line changes with evidence for why
## Tests                — assertions covering this ticket and related tickets
## Gate                 — build passes, tests pass, visual check (for UI)
```

**No Fix Spec = no code.** The investigation IS the work until Fix Spec is filled.

**Nesting depth:** Max two levels (L1 plan, L2 investigation). Deeper decomposition → split into separate L1 plans.

## Garbage Collection

Archive when the plan feels heavy — agent decides, no fixed threshold. Promoted or skipped INBOX entries are removed inline.

Add a GC task when the plan gets large:

```markdown
- [pending] Task GC: Archive completed tasks and prune PLAN.md
```

## INBOX.md

`INBOX.md` is where humans or external tools drop findings for agents to act on.

- Agents check INBOX.md during READ, before tasks
- Promote actionable findings to `[pending]` tasks in PLAN.md
- Annotate non-actionable ones with `[SKIP: reason]`
- Max 20 entries — if full, oldest are archived to `evidence/`
