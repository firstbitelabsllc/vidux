# The Store

The persistence layer. Every fact needed to survive an interrupted session lives in repo files — `PLAN.md`, `evidence/`, `investigations/`, git history — plus the append-only publish ledger rows that prove shipped cycles. `INBOX.md` is the intake queue. No databases. No daemons. No in-memory state.

**publish packet** = ledger row carrying task id, proof, handoff status, claimed files, resume point (defined in [The Cycle](/concepts/cycle)).

## Why Files?

AI agents are stateless. Auth expires. Sessions crash. State that survives a dead session is the repo plan/evidence tree plus the publish packet for shipped work.

One constraint: **any agent, resuming cold, must reach full context within 90 seconds of reading the Store.**

## The Durable Locations

```
vidux-project/
├── PLAN.md                    ← queue/planning authority
├── INBOX.md                   ← unprocessed findings
├── evidence/
│   └── YYYY-MM-DD-slug.md     ← research snapshots
└── investigations/
    └── slug.md                ← root cause analysis + fix specs
```

`INBOX.md` is part of the on-disk workflow, but the durable repo state stores are `PLAN.md`, `evidence/`, `investigations/`, git history. Publish ledger rows live outside the repo in the append-only ledger.

### PLAN.md

One per project. Planning authority for queue, decisions, constraints, Progress/Drift record. For a publish cycle, the publish packet is the proof of what shipped and how the next agent resumes.

Six required sections — missing any produces known failure modes:

| Section | What happens without it |
|---|---|
| Purpose | Agents optimize for the wrong goal |
| Evidence | Tasks are guesses; wrong fixes get shipped |
| Constraints | Agents violate hard requirements |
| Tasks | No queue — agents improvise unpredictably |
| Decision Log | Agents re-add deleted code or undo deliberate pivots |
| Progress | No history — agents can't tell what actually happened |

Unknowns and unexpected findings don't need their own sections. Promote a question to a `[pending]` research task (or note `[Blocker: need X]`); note a surprise in the Progress entry.

See [PLAN.md Structure](/concepts/plan-structure) for the full template.

### evidence/

Snapshots that back PLAN.md decisions. Named `YYYY-MM-DD-<slug>.md` so they stay sorted and interpretable over time.

Write an evidence snapshot when:
- A grep or audit produces findings that inform a task
- An external API response, PR comment, or design doc needs citing
- A Decision Log entry references a data point that might disappear

Evidence files are **append-only**. Update by adding a new dated file, never by editing an old one. The old file records what was believed at a point in time.

### investigations/

Sub-plans for complex bugs or surfaces needing root cause analysis before code. Every investigation follows the seven-section template:

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

Investigations are **durable**. They stay in `investigations/` after the parent task completes. Future agents who touch the same surface read them first.

### Git History

The transport timeline. When code changed, a commit records the local diff and why it moved, in a format any agent can parse:

```
vidux: add rate limiting to login endpoint
```

Cycle truth lives in the owning `PLAN.md` Progress, Tasks, or Drift Log entry plus the publish packet. Git history is evidence that transport happened; it does not outrank a missing or stale plan/ledger packet.

## INBOX.md

`INBOX.md` is the drop zone for unprocessed findings from humans, external tools, or scanners.

Rules:
- Agents check `INBOX.md` during READ, before tasks
- Promote actionable findings to `[pending]` tasks in PLAN.md
- Annotate non-actionable ones with `[SKIP: reason]`
- Max 20 entries — if full, archive oldest to `evidence/`

## The Invariant

> **State lives in files, never in memory.**

If it's not in the Store, it doesn't exist. Summaries in chat history, notes in agent memory, to-do lists in scratch pads — all die when the session ends. Only the Store survives.
