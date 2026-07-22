---
name: vidux
description: "Thin plan, proof, and resume discipline for work that must survive sessions, agents, and tools."
---

# Vidux

> Thin plan/proof control plane — not a model router. Repo-local authority only (never legacy `projects/*` routing).

Vidux is a thin durability layer, not a model router. The owning plan records queue, decisions, constraints, progress; matching ledger rows carry shipped-cycle proof.

**Publish packet:** one append-only ledger row containing `summary`, task id, plan path, proof, `handoff_status`, files claimed, path-like claims, and next-agent resume. Plan = planning authority; publish packet = shipped-cycle proof; git = transport.

Vidux owns plan/proof/resume semantics. The coding host or supervisor owns runner selection, leader/follower roles, worker foldback, and evaluation. Use direct native work when a durable plan adds no value.

## First-Time Setup

Read `AGENTS.md`/`CLAUDE.md`, then run `python3 scripts/vidux-config.py check --json` before
selecting a plan store. Treat the checked-in example as shape guidance, not a
live config. Read plan, git, and the smallest proof; reuse authority before
siblings. First-read Operator Brief / Outcome Scorecard / Current State / Open
work. No unauthorized push/merge/daemon/spend/live mutate.

## Activation & Triage

### Fast exit

Vidux does not activate for a factual answer, clear sub-30-minute repair, or tiny single-file edit with no durable handoff need.

### When Vidux activates

User names Vidux / plan-first / multi-session goal; a canonical `PLAN.md` already governs; work crosses agents/worktrees/releases/interruptions; or ≥5 files / unclear root cause / multi-stage sequencing.

### When Vidux does NOT activate

Copy/naming/lookup; bounded fix with obvious cause/owner/proof/exit; or a plan that would only narrate work.

## Five Principles

### 1. Plan first, code second

`PLAN.md` is the planning authority for queue, decisions, constraints, Progress/Drift record. Update plan before compound code. When work ships, update authority and emit the publish packet. Plan prose is not proof.

### 2. Design for interruption

Context is lost. Durable recovery lives in repo files + append-only ledger rows as structured plan/ledger packets. After interruption, re-read PLAN.md and relevant `evidence/`, then latest matching ledger row. Never trust summaries or memory for mutable state.

### 3. Investigate before fixing

Unclear root cause → one `investigations/<slug>.md` (reporter, root cause, impact, fix, gate). Ships with the fix.

### 4. Self-extend with a brake

Add adjacent work when evidence shows a real gap. Stop polishing when acceptance and proof are green.

### 5. Prove it mechanically

Cheapest real gate. Merge ≠ deploy. Weakest truthful claim if live proof blocked. Every failure → code fix + process fix.

## Worktree Lifecycle Contract

Start concurrent writers from current `origin/<trunk>` in contained worktrees.
Before create and closeout, run `scripts/vidux-worktree-gc.py` or the configured
Ledger guard. Classes are `merged_clean`, `open_pr`, `dirty`, `closed_unmerged`,
and `unmerged_no_pr`; classification is non-destructive. Land or preserve every
tree in the same cycle, never discard unknown work, and owner-gate cleanup.
Ledger owns the safe GC/guard mechanism; Vidux records lane and resume state;
the coding host or supervisor decides worker admission.

## The Cycle

```text
READ       -> instructions, canonical plan, ledger, git state, proof surface
ASSESS     -> resume in_progress; else highest-impact reachable row
ACT        -> smallest reviewable vertical slice; host runtime chooses workers
VERIFY     -> declared acceptance on the real surface; weakest truthful claim
CHECKPOINT -> Update the plan/queue note, emit the publish packet, then
              commit/push only after those breadcrumbs exist; reconcile
              planned vs actual and record any divergence in Progress
```

### Read the Room

Read: repo instructions; plan/queue; claims + `~/.agent-ledger/activity.jsonl`; git/worktree; runtime; only the reference this row needs. Repo-local `.agent-ledger/` is optional companion state only when documented.

Ad hoc scratch files are helpers, never authority. Do not read another repo's queue to choose this repo's work. Never commit, overwrite, or discard unknown WIP; preserve it first and record its recovery path in the owning plan plus a ledger handoff before commit, cleanup, or overwrite.

**Push authorization:** Operational PR-branch pushes are safe without asking only after the owning PLAN.md row/Progress/Drift Log is updated and a `--event publish` packet is recorded via an external ledger emitter, when one is configured. Open PRs ready-for-review by default; draft means a real missing gate. Direct-to-main requires explicit authorization + the same publish propagation. A normal publish-propagated PR-branch push is not direct-to-main authority.

### Trunk-First Rule

Start from current `origin/<trunk>`. Isolate writers. Publish only owned files. Before calling a slice landed, require publish propagation recorded in the owning plan row + publish packet, final proof, and release gates. If they publish externally, record the plan + ledger propagation first.

**Worktree lifecycle:** `merged_clean` may be proposed for guarded cleanup; `open_pr`, `dirty`, `closed_unmerged`, and `unmerged_no_pr` require nursing, recovery, or an explicit abandoned record.

### Queue order

Resume `[in_progress]`; then deps; then highest-impact reachable; park hard-blocked with proof and resume.

## Goal Navigation Plans

`references/goal-navigation-control-plane.md` is the packaged navigation contract, not a frozen task list. The prompt file is a pointer/control contract, not the goal: the exact selected planning authority owns the actual goal, real work rows, exit criteria, and next action. It records how to rank work when state changes. `/goal` and `/loop` keep appending and executing real work rows until that authority says the goal is complete. Multiple agents share one plan with disjoint claims; the coding host or supervisor chooses runners and folds receipts back into that authority.

### Optional steering and claims

The authority may be a root `PLAN.md` or a repo-native named plan. Resolve and carry its exact path; never silently redirect a steer or claim to another plan. When the local steering inbox is installed, lease at most one exact-plan intent at a safe cycle boundary. Current plan truth wins conflicts, lasting effects go into the plan, and the host acknowledges the intent only after the matching user-facing response. Usage or transport failure stays visible and retryable.

Coordination claims contain bounded ownership, heartbeat, checkpoint, expiry, and handoff metadata—not hidden prompts, provider transport, or another authority store. Claim disjoint work, release on exhaustion, and make expired work takeover-eligible without erasing its resume packet. The host still owns dispatch and replies.

## PLAN.md Contract

Scannable plan. Details in `evidence/` and `investigations/`; link them.

Required sections (what `vidux init` scaffolds): Purpose, Evidence, Constraints, Operator Brief, Outcome Scorecard, Tasks, Decision Log, Progress. Optional: Drift Log, Current State, Open work. States: `pending -> in_progress -> completed`; `blocked` terminal until replaced. Optional `verify`/`in_review`/`merged` fold into `in_progress`.

### Two nesting modes

A compound task may nest exactly one level:

1. **Investigation** — Reporter Says, Root Cause, Impact Map, Fix Spec, Gate.
2. **Sub-plan** — roll one result + proof into parent.

## Investigation Template

```markdown
# Investigation: [surface]
## Reporter Says
## Evidence
## Root Cause
## Impact Map
## Fix Spec
## Tests
## Gate
```

## Course Correction

Evidence → update plan → re-rank → code.

### Placeholder draft PRs over blocked exits

A placeholder draft PR is still a publish action. Record assumptions in the owning PLAN.md Progress/Tasks or Drift Log, then publish via the ledger emitter's `--event publish` with `handoff_status=needs_review` (`--summary`, `--task-id`, `--plan-path`, `--proof`, `--handoff-status needs_review`, `--resume`, `--file`, `--claim`); carry that ledger eid into the PR body via `gh pr create --draft`.

## Persistent Loop Mode

Loop body:

1. Re-read plan, claims, git/runtime state, latest proof.
2. Drive highest-impact reachable row through proof.
3. Drain connected reachable work; do not stop at the first checkbox.
4. Checkpoint: update the owning plan/queue note, emit the publish packet, then commit + push the owned branch/PR path.
5. Repeat until exit criteria pass or remaining rows have named hard blockers + resume proof.

Persistent loop mode is lane-persistent, not narration-persistent. Three iterations without shipped code → surface change or concise blocker.

**Compaction survival:** Before each checkpoint, update durable repo files, emit the publish packet when work shipped, and use repo-local `.agent-ledger/` only for configured companion state. Repo files + append-only ledger rows survive compaction. After compaction, re-read the plan and latest matching ledger entry.

### Cron + interactive interleave

Interactive redirect edits owning prompt/queue in place — do not duplicate automation.

## Nursing Mode

Read plan/queue/ledger on cadence. Intervene for drift/conflict/unblock/unowned work; else only material change.

**Repo-level state rule:** nursing uses the centralized `~/.agent-ledger/activity.jsonl` stream and repo-local `.agent-ledger/` only when documented. Durable handled state belongs beside the repo queue.

For any timed or repeated supervision, use a concrete repo-owned runner and record its authority plan, cadence, proof command, and stop condition. Do not fake a timer with an idle chat loop.

## Coordination Boundary

Vidux may record claims and disjoint slices, but it does not select models. The coding host or supervisor plans, assigns, and folds worker output back. Prefer one lead and the fewest workers. Provider unavailability never waives proof.

## Browser

Read-mostly projection. Markdown remains queue/planning authority; the publish packet remains the shipped-cycle proof. Use `vidux-browse`; load `docs/reference/browser.md` only when operating routes/storage.

Security invariants: artifact HTML uses a network-isolated, sandboxed iframe; artifact code never receives `allow-scripts` or `allow-popups`; sensitive text redacted. Never claim no XSS risk.

### Ad-hoc artifacts

Optional visual receipts, not plan state — load browser reference before writes/LAN exposure.

## Checkpoint Breadcrumbs

1. **Plan / queue** — current row, decision, drift, resume, carrying the publish packet fields.
2. **Ledger** — the ledger emitter's `--event publish`; keep eid with the branch/PR handoff.
3. **Git** — transport only owned work after the plan + ledger breadcrumbs exist.

## Replaces /superpowers

Use five principles, cycle, investigation, proof, worktree contract. `/auto` deleted 2026-06-26 — do not restore.

## Voice & Tone

What changed, what passed, what remains, exact resume. Do not blend source/merge/deploy/live truth.

## Reference Files

JIT only: `README.md`, `DOCTRINE.md`, `docs/reference/plan-fields.md`, `docs/reference/browser.md`, `guides/thin-token.md`, `guides/investigation.md`, `guides/fleet-ops.md`, `guides/automation.md`, `guides/recipes/`. Budget ≤12 KB / ≤200 lines / ≤3000 est. tokens.
