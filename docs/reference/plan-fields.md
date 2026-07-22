# PLAN.md Field Reference

Every section and annotation a vidux `PLAN.md` uses. For the discipline and cycle, see [Five Principles](/concepts/principles), [The Cycle](/concepts/cycle), and [PLAN.md Structure](/concepts/plan-structure).

## Section Order

Canonical order below. *Optional* sections may be omitted on small plans; NEVER re-order the required ones — tooling and agent muscle memory expect the sequence.

| # | Section | Required | Purpose |
|---|---|:---:|---|
| 1 | `# <Project Name>` | ✔ | Title — one H1, matches the project |
| 2 | `## Purpose` | ✔ | One paragraph. User-visible goal. |
| 3 | `## Evidence` | ✔ | Cited facts the plan is built on |
| 4 | `## Constraints` | ✔ | ALWAYS / NEVER rules |
| 5 | `## Tasks` | ✔ | Ordered task queue with status tags |
| 6 | `## Decision Log` | ✔ | Intentional choices future agents must not undo |
| 7 | `## Drift Log` |  | Optional structured planned-vs-actual deviation log, recorded manually before Progress |
| 8 | `## Progress` | ✔ | Living per-cycle log (unexpected findings + reorder notes live here) |

## Task Status FSM

```
  pending ─────▶ in_progress ─────▶ in_review (optional) ─────▶ completed
                      │
                      └── blocked (terminal)
```

| Status | Meaning | Who sets it |
|---|---|---|
| `[pending]` | Queued with evidence, not yet started | Writer during plan authoring |
| `[in_progress]` | Actively being worked (one cycle or across cycles) | Any agent picking up the task |
| `[in_review]` | Optional PR-backed state while CI or review gates are still pending | The agent that opened or is nursing the PR |
| `[completed]` | Verified done: build ran, tests passed, visual check done | The agent that finished it |
| `[blocked]` | Terminal — replaced by a new task with a Decision Log entry | Any agent that hits the block |

`[in_review]` is optional. Core shell helpers (`scripts/vidux-status.py`, `scripts/vidux-loop.sh`, `scripts/vidux-checkpoint.sh`) and the contract tests center the four-state subset: `pending`, `in_progress`, `completed`, `blocked`. Use `in_review` only when your repo has an explicit PR/review workflow; otherwise the four-state flow is the safest default.

**Rules:**

- A task is `[in_progress]` for at most one cycle at a time. If the session dies mid-task, the next agent resumes it.
- 3+ Progress entries while still `[in_progress]` → force a surface switch. Default reduce mode reports the next runnable candidate in JSON; auto-blocking and Decision Log writes require explicit opt-in.
- `[completed]` is earned by verification evidence (command, screenshot, build output), never assertion. Claiming complete without evidence is a lie (SKILL.md Principle 5).
- Status flows UP from sub-plans: an L1 task stays `[in_progress]` while its L2 investigation has any `(pending)` section.

## Task Annotations

Inline markers on a task line. Multiple can stack: `- [pending] Task 7: ship API docs [Depends: Task 3] [Evidence: Sentry def-123]`.

| Annotation | Purpose | Example |
|---|---|---|
| `[Evidence: ...]` | Cited source backing this task | `[Evidence: src/auth.ts:42 — no idempotency key]` |
| `[Depends: Task N]` | Blocks until task N is `[completed]` | `[Depends: Task 3]` |
| `[Investigation: path]` | Compound task — read sub-plan before coding | `[Investigation: investigations/payment-flow.md]` |
| `[Blocker: ...]` | What's blocking, on `[blocked]` tasks | `[Blocker: needs production analytics credentials]` |
| `[Drift: ...]` | Drift Log entry that explains why a stale task was blocked or replaced | `[Drift: D-20260522-01]` |
| `[Fix: file:line]` | Where the fix landed, on `[completed]` tasks | `[Fix: src/auth.ts:42]` |
| `[Shipped: <sha>]` | Commit sha the fix landed in | `[Shipped: a1b2c3d]` |

## Decision Log Entry Types

The Decision Log is the **lock file** that stops stateless agents from undoing prior choices. Every entry opens with a bracketed type tag and a bracketed date — `[TAG] [YYYY-MM-DD]` — matching the canonical form in `SKILL.md`'s `## Decision Log` section. `scripts/vidux-plan-guard.sh`'s `has_authorizing_deletion()` specifically requires the bracketed-date form on `[DELETION]` entries to authorize a task-count drop; an unbracketed date is not recognized and will not silence an integrity warning.

| Type | When to use | Template |
|---|---|---|
| `[DELETION]` | Removed something deliberately — future agents must not re-add it | `[DELETION] [2026-04-16] Removed X-endpoint. Reason: deprecated by Y. Do not re-add.` |
| `[DIRECTION]` | Chose approach X over Y for a stated reason | `[DIRECTION] [2026-04-16] Chose idempotency key over distributed lock. Reason: lock adds 80ms p99.` |
| `[SCOPE]` | Cut scope — what's in, what's explicitly out | `[SCOPE] [2026-04-16] Email notifications deferred to v2. Reason: requires SES provisioning.` |
| `[PIVOT]` | Course correction — old direction obsolete, new direction active | `[PIVOT] [2026-04-16] Was targeting Postgres; now targeting Cloudflare D1. Reason: edge-compatible.` |
| `[CONSTRAINT]` | Discovered a hard constraint (infra limit, compliance, budget) | `[CONSTRAINT] [2026-04-16] Function timeout 300s. Reason: Vercel Fluid Compute ceiling.` |
| `[REVERSAL]` | Undoing a prior Decision Log entry — reference the old one | `[REVERSAL] [2026-04-16] Revert [DIRECTION 2026-03-12]. Reason: benchmarks showed 3x regression.` |

Agents grep the log by tag: forbidden (`[DELETION]`), architectural choices (`[DIRECTION]`), recent changes (`[PIVOT]` / `[REVERSAL]`).

## Progress Entry Format

One line per meaningful cycle. The Progress line orients future agents to the owning plan state; the matching publish ledger row carries shipped-cycle proof, handoff status, claimed files, and next-agent resume. Git diff/log evidence supports but does not replace the plan plus ledger packet.

```
- [YYYY-MM-DD HH:MM] What happened. Next: what's next. Blocker: if any.
```

**Do:**
- Open with a verb (shipped, investigated, blocked, promoted, archived)
- Reference task numbers: `shipped Task 7`
- Cite files when the reader needs them: `see fix at src/auth.ts:42`

**Don't:**
- Treat the diff or git log as the whole handoff — cite the task, proof, resume point
- Write "everything fine" lines — nothing to report, no entry
- Paraphrase the plan — reference it by task number

## Drift Entry Format

When implementation diverged from the plan, add a `## Drift Log` section (if
needed) and append an entry in this shape:

```
- [YYYY-MM-DD] D-YYYYMMDD-NN — Task N
  - Planned: ...
  - Actual: ...
  - Why: ...
  - Cause: wrong_surface
  - Impact: material
  - Plan update: ...
  - Next: ...
  - Prevention: ...
  - Subplans: ...
```

Drift invalidates a task → `--block-task` (`[blocked] ... [Drift: D-...]`). Drift
creates work → `--add-task`. Named `--subplan` paths get a mirrored entry with
the same id. With `--cache`, JSONL rows include `schema_version`, `drift_id`,
`date`, `plan_path`, `task`, `planned`, `actual`, `why`, `cause`, `impact`,
`plan_update`, `next`, `prevention_hints`, `subplans`, `added_tasks`,
`blocked_task`.

## Evidence Source Tags

Every item in the Evidence section cites a source. Standard tags:

| Tag | Points to |
|---|---|
| `[Source: codebase grep]` | A grep hit in the repo, format `file:line pattern` |
| `[Source: GitHub PR #N]` | A comment, review, or decision on a PR |
| `[Source: GitHub issue #N]` | An issue report or discussion |
| `[Source: observed]` | A directly observed runtime behavior or repro |
| `[Source: Sentry <id>]` | A Sentry issue with occurrences + user impact |
| `[Source: design doc]` | An architecture or product doc (inline quote preferred) |
| `[Source: team chat]` | A Slack / email / issue-tracker decision (screenshot or quote) |
| `[Source: measurement]` | A benchmark, perf measurement, or experiment result |

**Rule:** a plan entry without a source is a guess. Guesses cause rework (SKILL.md Principle 1).

## Constraints Block Format

Two subsections — what must be true, what is forbidden.

```markdown
## Constraints
- ALWAYS: integration tests hit the real database (no mocks)
- ALWAYS: run lint + build before commit
- NEVER: edit content/posts/**/*.mdx body text
- NEVER: skip pre-commit hooks
```

**Rule of thumb:** constraints survive the project. A rule that applies to one task goes on the task line, not in Constraints.

## Compound Task Sub-Plan Structure

A task with `[Investigation: investigations/<slug>.md]` has a sub-plan in this structure:

```markdown
# Investigation: <surface name>

## Reporter Says
<exact quote from feedback / ticket>

## Evidence
<files, related tickets, recent commits, repro steps>

## Root Cause
<the specific code path — not symptoms>

## Impact Map
<other UI paths / tickets / state flows affected>

## Fix Spec
<file:line changes with evidence for why>

## Tests
<assertions covering this ticket AND related tickets>

## Gate
<build passes, tests pass, visual check (for UI)>
```

Sections fill in as the investigation progresses. **No `## Fix Spec` → no PR** — notes stay local until the fix ships alongside them in one code PR.

## See Also

- [Five Principles](/concepts/principles) — the doctrine behind the queue
- [The Cycle](/concepts/cycle) — how a plan gets executed each run
- [PLAN.md Structure](/concepts/plan-structure) — template shape and section order
- [Prompt Template](prompt-template.md) — the 8-block prompt shape for a vidux worker
- [Fleet / Claude Lifecycle](../fleet/claude-lifecycle.md) — how a cycle actually fires
