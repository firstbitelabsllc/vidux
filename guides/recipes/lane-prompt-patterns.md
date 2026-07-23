# Recipe: Lane Prompt Patterns

> The 8-block structure plus common patterns for writing automation lane prompts (`prompt.md` files that drive cron lanes).

## When to use

- Creating a new automation lane (writer, radar, or coordinator)
- Auditing an existing `prompt.md` that's drifting, stalling, or duplicating work
- Migrating a legacy cron prompt to the vidux 2.10.0 single-tool model

## The 8-block structure

Every lane prompt has these eight blocks, in this order. Rearranging or omitting blocks produces known failure modes.

```
1. Mission      — why this lane exists; retirement condition. One paragraph.
2. Skills       — skill tokens to activate each cycle (/vidux first).
3. Read         — explicit file-read order every cycle.
4. Gate         — pre-flight checks that can abort the cycle cheaply.
5. Assess       — priority rule for picking the ONE thing to do this cycle.
6. Act          — how to do the work (worktree, verify, commit, merge).
7. Authority    — paths owned vs paths forbidden (+ push tier).
8. Checkpoint   — lane-local memory format plus plan/ledger publish packet for shipped work.
```

Full reference: `docs/reference/prompt-template.md`. Size target: 2000-3000 chars total.

## Block-by-block guide

### 1. Mission
One paragraph. Present-tense and concrete. Name the PLAN.md the lane drives. **Name the retirement condition.** A lane without an exit is a zombie.

> Ship and maintain example.com. Every cycle moves PLAN.md forward, fixes CI, merges eligible PRs, or rotates a filler audit. Retires when Phase 9 launch ships.

### 2. Skills
Skill tokens to load each cycle. `/vidux` first — it loads cycle + FSM + checkpoint format before anything else.

> `/vidux` `/brand-<project>` `/frontend-design`

### 3. Read
Literal shell commands and absolute file paths. Start with own `memory.md` (self-awareness), end with cross-lane reads (concurrent-cycle detection).

> 1. `memory.md` (last 3 entries)
> 2. `~/Development/<project>/vidux/PLAN.md`
> 3. `git fetch && git status --short && git log --oneline -10`
> 4. `gh pr list --json number,title,mergeable,statusCheckRollup`
> 5. (cross-lane) `<lane-dir>/session-gc/memory.md` last 1 entry

### 4. Gate
Binary pre-flight aborts. Trigger → exit cheaply with `[QC] <reason>`. Don't "maybe work around it." Keep the list short; too many gates and cycles never fire.

Typical gates: dirty tree not mine → `[QC] concurrent-cycle`; same task `[in_progress]` 3+ cycles → set `[blocked]` + exit; main CI red → fix-first mode; post-push defer (see below).

### 5. Assess
One deterministic priority order. "First match wins" so two agents running the same lane pick the same task. Drain connected reachable work — never stop at the first checkbox.

> Priority: CI red > failing PR fix > eligible PR merge > resume `[in_progress]` > first `[pending]` with evidence > promote INBOX > rotate filler audit > `[IDLE]`.

### 6. Act
Worktree discipline + verification commands + commit/push/merge procedure. Every command literal — don't paraphrase.

Mandatory: fresh worktree per code change; `npm run lint` + `npm run build` must pass; never `git add -A`; UI change needs a screenshot, not a green test. Before pushing a branch, update the owning PLAN.md and emit the ledger emitter's `--event publish` with `--summary`, `--task-id`, `--plan-path`, `--proof`, `--handoff-status`, `--resume`, `--file`, and `--claim`; keep the eid in `$LEDGER_EID`. Before `gh pr create`, build the body with `scripts/vidux-pr-body.py --summary "<summary>" --ledger "$LEDGER_EID"` plus the three `--review-pass` entries so every PR carries `Lane:`, `Plan task:`, `Summary:`, `Plan path:`, `Proof:`, `Ledger:`, `Handoff status:`, `Files claimed:`, `Self-Scrutiny`, and `Resume point:`.

### 7. Authority
Explicit owned paths + explicit forbidden paths with reasons. The authority block is the lane's immune system. **Mandatory push-tier line** for any code-writing lane.

> Owns: `app/**`, `next.config.ts`, `vidux/PLAN.md`, `vidux/INBOX.md`.
> Never: `content/posts/**/*.mdx` body (the user's historical prose), `.env*`, other lanes' `memory.md`.
> Push tier: operational PRs only; open ready-for-review by default with the canonical vidux PR body. No direct-to-main, no destructive ops.

### 8. Checkpoint
One-line lane-local `memory.md` append, always tagged. Future agents scan the last 3 entries for cycle orientation. When the cycle ships work, the owning PLAN.md update plus a matching ledger emitter `--event publish` row carries the durable proof, handoff status, files claimed, and next-agent resume.

> `- [YYYY-MM-DDThh:mm:ssZ claude coord] [SHIP] <what>. <next-cycle hint>.`
> Tags: `SHIP` / `MERGED` / `FIX` / `PROMOTE` / `DEFER` / `IDLE` / `QC` / `AUDIT-N` / `MILESTONE`.
> No "everything fine" entries.

## Common patterns

**Post-push defer.** The cycle that pushes a PR must NOT also merge it. Gate: "if last cycle pushed, this cycle may only review CI — no merge until 1h since last fix-push AND all checks green." Prevents auto-merging a failing build.

**QC exit.** Cheap exits for concurrent-cycle, stuck tasks, red CI. Always tagged `[QC] <reason>`. A `[QC]` exit is not a failure — it's the correct move when preconditions aren't met.

**Signal-only lane note vs full publish checkpoint.** Default: signal-only `memory.md` note (one line, tag + summary). Only expand the lane note to multi-line when crossing a plan-phase boundary (`[MILESTONE]`). Reading memory.md's last 3 entries should take 5 seconds; shipped work still needs the owning PLAN.md plus publish ledger packet.

**Worktree-per-change.** Every code edit happens in a fresh worktree from `origin/main`. Never edit on the main worktree. Merge back to trunk before closing the task.

**Branch verification after commit.** After `git commit`, always run `git branch --show-current` and confirm it matches the intended branch. Prevents committing to `main` by accident when a worktree is misconfigured.

**Polish-brake.** If the last 3 checkpoints ship from the same surface, force-rotate to another surface next cycle. Polish is fractal; every green PR has another P3 comment.

## Anti-patterns

- **Hard-coded transient state.** A prompt that says "fix the auth flow" will stop making sense once auth is fixed. Put task-level specifics in PLAN.md; the prompt stays evergreen.
- **Multi-tasking in parallel.** Working unrelated surfaces at once breaks checkpointing — the tag no longer describes what happened. Sequential actions, one action, one line — draining the queue is fine, doing two things at once is not.
- **No retirement condition.** Lane runs forever, ships polish PRs no one reads. Every mission names an exit ("retires when Phase 9 launches" / "retires after the backfill completes").
- **Skipping the Authority block.** Lane drifts into sibling work, creates merge conflicts, edits Leo's historical prose. Authority is load-bearing.
- **Cross-tool delegation language.** Deprecated in vidux 2.10.0. A lane runs on Claude OR on Codex, never both. For Codex-native lanes, see `guides/recipes/codex-runtime.md`. For same-tool parallelism, see `guides/recipes/subagent-delegation.md`.
- **Doctrine restatement.** Don't repeat "plan is truth" or "five principles" prose in the prompt — `/vidux` loads it. Every sentence you can delete without changing behavior, delete.
- **Gating on the wrong file.** If Block 4 checks a meta-plan marked "done," the agent exits before loading any skill. Gate on actual work state (dirty tree, CI status, queue depth).

## See Also

- `guides/automation.md` — where to plug a prompt.md in a lane (Lane Bootstrap Recipe)
- `docs/reference/prompt-template.md` — canonical 8-block reference with full examples
- `guides/fleet-ops.md` — multi-lane operations, radar vs writer vs coordinator
- `guides/recipes/subagent-delegation.md` — same-tool Mode A / Mode B delegation
- `guides/recipes/codex-runtime.md` — Codex-native lane setup
