# The 8-Block Prompt Template

Every vidux lane — Claude Code or Codex — has a `prompt.md` on disk that drives each cycle. The 8-block structure tells any agent picking up the lane what to read, when to gate, how to act, and what it owns. For how the prompt is injected each fire, see [claude-lifecycle.md](../fleet/claude-lifecycle.md) and [codex-lifecycle.md](../fleet/codex-lifecycle.md).

## The 8 Blocks

```
1. Mission       — why this lane exists, one paragraph
2. Skills        — skill tokens this lane activates
3. Read          — files to read every cycle, in order
4. Gate          — pre-flight checks that can abort the cycle
5. Assess        — priority rules for picking the next action
6. Act           — how to actually do the work
7. Authority     — paths owned vs paths forbidden
8. Checkpoint    — lane-local memory note plus publish packet fields for shipped work
```

Every block is required. A lane missing any is underspecified and will drift.

## Block 1: Mission

One paragraph: what this lane accomplishes and what "done" looks like.

```markdown
## 1. Mission

Ship and maintain the project surface this lane owns. Every cycle either moves a
[pending] PLAN.md task forward, fixes a CI failure, or merges an
eligible PR. When the queue is empty, scout INBOX.md for promotions
or rotate a filler audit. The lane retires when the owning PLAN.md
hits its named ship milestone.
```

**Rules:**
- Present-tense, concrete. Not "help with" — state the goal.
- Name the PLAN.md path the lane drives.
- Name the retirement condition. A lane without an exit is a zombie.

## Block 2: Skills

Skill tokens the lane invokes before acting, loading domain knowledge and discipline each cycle.

```markdown
## 2. Skills

Activate these skills every cycle, in order:
- `/vidux` — discipline + automation (cycle, FSM, checkpoint format, Part 2 lane mechanics)
```

**Rules:**
- Put `/vidux` first so the cycle and FSM load before anything else.
- Add repo-specific brand or domain skills only when the lane needs them.
- NEVER load skills the lane never uses — every token costs context.

## Block 3: Read

Explicit file-read order — every cycle reads the same files in the same order, so every agent starts with the same worldview.

```markdown
## 3. Read

Read in this order every cycle:
1. `memory.md` — last 3 entries, so I know what the previous cycle did
2. `{project-root}/PLAN.md` — queue state, Decision Log
3. `{project-root}/INBOX.md` — scanner findings
4. `git fetch && git status --short && git log --oneline -10` — repo state
5. `gh pr list --json number,title,mergeable,statusCheckRollup` — open PRs
6. (cross-lane) `{lane-dir}/session-gc/memory.md` — last 1 entry when session-gc exists
```

**Rules:**
- Start with own `memory.md` — self-awareness before world-awareness.
- End with any cross-lane reads that catch concurrent-cycle conflicts.
- Name shell commands literally — agents copy-paste them.

## Block 4: Gate

Pre-flight checks that **abort the cycle** before any action. Gates stop bad cycles cheaply.

```markdown
## 4. Gate

Abort this cycle (append `[QC] <reason>` to memory.md and exit) if:

- Dirty tree NOT mine (uncommitted work from another session or lane)
  → `[QC] concurrent-cycle` and exit
- Same PLAN.md task in `[in_progress]` for 3+ consecutive cycles
  → Set task to `[blocked]` with a Decision Log entry, then exit
- Main CI is RED on latest commit
  → Fix-first mode: triage the failing job, ignore other work
- Post-push defer: last cycle pushed a PR
  → This cycle may only review CI — do not attempt merge until
    1h since last fix-push AND all checks green
```

**Rules:**
- Gates are binary: trigger → exit. NEVER "maybe work around it."
- A concurrent-cycle exit is not a failure — it's the correct move.
- Keep the list short. Too many gates and cycles never fire.

## Block 5: Assess

The priority rule for picking **the one thing this cycle does** — unified so two agents on the same lane pick the same task.

```markdown
## 5. Assess

Priority order (first match wins):

1. Main CI red → fix the failure
2. Open PR with failing checks → fix-push
3. Open PR eligible for merge (CI green, push-age ≥1h, no P0/P1 reviews) → merge
4. PLAN.md has `[in_progress]` task → resume it (prior session died mid-task)
5. PLAN.md has `[pending]` task with evidence → promote to `[in_progress]`, execute
6. PLAN.md empty + INBOX.md has promotable finding → promote it to a task
7. All of the above empty → rotate one filler audit (bundle-size, sitemap, a11y),
   then exit [IDLE]
```

**Rules:**
- Drain connected reachable work — never stop at the first checkbox. Take actions sequentially, not concurrently: multi-tasking unrelated surfaces in parallel still breaks checkpointing.
- `[in_progress]` always resumes first — never leave mid-task work orphaned.
- `[IDLE]` is a valid outcome. Not all cycles ship.

## Block 6: Act

How to do the work — the heavy rules: worktree discipline, verification commands, merge procedure, delegation contracts.

```markdown
## 6. Act

### Code changes (worktree discipline)
- Create a fresh worktree from origin/main for every code change
- `git worktree add -b {branch} ../{project}-worktrees/{branch} origin/main`
- Never edit files on the main worktree directly

### Verification (mandatory before commit)
- `npm run lint` — must pass
- `npm run build` — must complete
- UI change? Take a screenshot with Playwright or craft-svg

### Commit + push
- `git add {specific files}` — never `-A`
- Commit message: `{verb}({scope}): {what}`
- After commit, `git branch --show-current` must match intended branch
- Before `git push`, update the owning PLAN.md Progress/Tasks/Drift Log and
  emit an `--event publish` row (via your configured ledger emitter) with
  concise summary, plan task id, plan path, proof, `handoff_status`, files claimed,
  next-agent resume, changed files, and path-like claims.
- Build the PR body with `python3 scripts/vidux-pr-body.py --lane "{lane}" --task "{task-id}" --summary "{summary}" --plan-path "{PLAN.md}" --proof "{command/artifact}" --handoff-status "{done|in_progress|blocked|needs_review}" --ledger "{publish-ledger-eid}" --file-claimed "{path}" --review-pass "invariant-audit:pass:{plan/ledger/drift proof}" --review-pass "regression-runner:pass:{tests/docs proof}" --review-pass "adversarial-reviewer:pass:{overclaim/stale-proof check}" --resume "{resume point}" --change "{summary}" > /tmp/vidux-pr-body.md`
- Open a ready PR with `gh pr create --base main --head "{branch}" --title "{title}" --body-file /tmp/vidux-pr-body.md`

### Merge (only when gate allows)
- `gh pr merge {n} --squash --auto` — only if CI green, push-age ≥1h,
  zero unresolved P0/P1 reviews

### Delegation (optional — Mode A / Mode B)
- If reading > 3 KB of source, use the runtime's native subagent primitive
  for Mode A research compression. See `guides/recipes/subagent-delegation.md`.
- For bug fixes with a clear spec (>10 lines), use Mode B implementation
  delegation in the same runtime, then review the diff before shipping.

### Long-horizon / multi-agent contract
- Work spanning more than one cycle, day, or agent keeps one canonical PLAN.md.
  Use L2 sub-plans only for investigation/Fix Spec work, linked from the parent
  task — NEVER sibling plans.
- Before editing a shared row, run `claims-bus.sh check <PLAN.md> <row-id>`;
  after a successful claim, record the owner and `files_claimed`.
- Stale-proof is a gate: evidence older than 24h, older than the latest material
  code/config change, or copied from another agent must be refreshed or marked
  stale before publish.
- At each meter checkpoint (every 30-60 min, before compaction, before handoff),
  update the owning PLAN.md Progress/Tasks/Drift Log with proof, what remains,
  `handoff_status`, next-agent resume.
- Before publish, run three self-review passes (invariant audit, regression
  runner, adversarial reviewer) and record the packet with
  `python3 scripts/vidux-publish-scrutiny.py --summary "..."
  --review-pass invariant-audit:pass:"..."
  --review-pass regression-runner:pass:"..."
  --review-pass adversarial-reviewer:pass:"..."`. Fix P0/P1 findings first.
```

**Rules:**
- Every verification command is literal — NEVER paraphrase.
- "Never `git add -A`" prevents the classic "accidentally committed .env" bug.
- Delegation is optional per lane; include the sub-block only if the lane ships code.
- Long-horizon work is still one canonical plan. Sub-plans explain; they NEVER
  become competing sources of truth.

## Block 7: Authority

Explicit paths the lane **owns** vs paths it must **never** touch — the lane's immune system.

```markdown
## 7. Authority

### Paths this lane owns (may edit freely)
- `{repo-owned-source-paths}`
- `{project-root}/PLAN.md`, `{project-root}/INBOX.md`, `{project-root}/evidence/`
- `{lane-dir}/{lane-id}/memory.md`

### Paths this lane must NEVER touch
- `{human-authored-prose-paths}` body text when the repo treats that prose as immutable
- `.env*` files (secrets)
- `scripts/**` (cross-lane tooling, not coord-owned)
- Other lanes' `memory.md` files — read-only

### Push authorization
- Operational PRs: push branch + open ready-for-review by default; no approval needed.
- Draft PRs: only for true WIP or a missing gate; flip ready as soon as the gate passes.
- PR body must carry `Lane:`, `Plan task:`, `Summary:`, `Plan path:`, `Proof:`, `Ledger:`, `Handoff status:`, `Files claimed:`, and `Resume point:`.
- Direct-to-main or destructive operations (force-push, branch delete, `git reset --hard`): forbidden for this lane.
```

**Rules:**
- List the "never touch" paths explicitly — a lane that silently edits out-of-scope files is worse than one that does nothing.
- Cite the **reason** for forbidden paths (historical prose, secrets, cross-lane). Future agents read it to judge edge cases.
- The push-authorization section is mandatory for any code-writing lane. See SKILL.md for the full contract.

## Block 8: Checkpoint

The `memory.md` append format — one line per cycle. Future agents scan the last 3 entries for context.

```markdown
## 8. Checkpoint

After the cycle, append ONE line to
`{lane-dir}/{lane-id}/memory.md`:

### Signal-only format

```
- [YYYY-MM-DDThh:mm:ssZ {runtime} {lane-role}] [TAG] {what happened}. {optional second sentence on next-cycle plan}.
```

### Durable handoff fields

When the cycle changed code, published a branch/PR/release, or leaves work in
progress for another agent, the checkpoint must also name the durable surfaces:

- Plan row moved: `{PLAN.md}#{task-id}` or `[NO PLAN CHANGE]` with reason.
- Ledger: `{eid}` or dry-run payload path.
- Proof: exact command/artifact that passed, plus stale-proof refresh if needed.
- Files claimed: `files_claimed=[...]`.
- Handoff status: `handoff_status={done|in_progress|blocked|needs_review}`.
- Next-agent resume: exact next command, PR, plan row, or blocker to inspect.

### Valid tags
- `[SHIP]` — pushed a PR
- `[MERGED]` — merged a PR
- `[FIX]` — fixed a CI failure
- `[PROMOTE]` — promoted an INBOX item to a task
- `[DEFER]` — post-push defer / active review wait / human currently driving the surface
- `[IDLE]` — queue empty, no work surfaced
- `[QC]` — aborted cycle (dirty tree, stuck, etc)
- `[AUDIT-N]` — rotated filler audit N
- `[MILESTONE]` — plan phase boundary / big ship / course correction

### No-noise rule
No "everything fine" entries. If there's nothing to report beyond what
the last entry already said, skip the entry entirely.
```

**Rules:**
- One line, not a paragraph. The owning plan plus matching publish ledger row carries the shipped-cycle story; memory.md only orients the lane-local cycle note.
- ALWAYS tag. Untagged entries are unsearchable by future agents.
- Include the session SHA (`{session-sha}`) when the lane hosts cross-session state.

## Full Example

An abridged prompt file showing all 8 blocks assembled:

```markdown
# project-coordinator — lane prompt

## 1. Mission
Ship and maintain the owned project surface. Every cycle moves PLAN.md
forward, fixes CI, merges eligible PRs, or rotates a filler audit.

## 2. Skills
- /vidux

## 3. Read
1. memory.md (last 3)
2. {project-root}/PLAN.md
3. {project-root}/INBOX.md
4. `git fetch && git status --short && git log --oneline -10`
5. `gh pr list`

## 4. Gate
- Dirty tree not mine → [QC] concurrent-cycle, exit
- Same task [in_progress] 3+ cycles → [blocked] + exit
- Main CI red → fix-first mode
- Post-push defer: previous cycle pushed → no merge attempt this cycle

## 5. Assess
Priority: CI red > failing PR fix > eligible PR merge > resume [in_progress]
> first [pending] with evidence > promote INBOX > rotate filler audit > [IDLE]

## 6. Act
- Fresh worktree per code change
- Verify: lint + build + (UI) screenshot
- Commit: `{verb}({scope}): {what}`; never `git add -A`
- Before push: update PLAN.md and emit, via your configured ledger emitter, `--event publish --summary --task-id --plan-path --proof --handoff-status --resume --file --claim`
- PR body: `scripts/vidux-pr-body.py` with Lane / Plan task / Summary / Plan path / Proof / Ledger / Handoff status / Files claimed / Self-Scrutiny review passes / Resume point
- Long horizon: one canonical PLAN.md, L2 sub-plans only for investigations,
  `claims-bus.sh check`, `files_claimed`, stale-proof refresh, meter checkpoint
  every 30-60 min, invariant audit + regression runner + adversarial reviewer
  before publish via `scripts/vidux-publish-scrutiny.py`, and `handoff_status`
  + next-agent resume in the checkpoint.
- Merge: gh pr merge --squash --auto; only if CI green + push-age ≥1h
- Delegate via native Mode A / Mode B subagents when the task is large enough

## 7. Authority
- Owns: {repo-owned-source-paths}, {project-root}/PLAN.md, INBOX.md, evidence/
- Never: {human-authored-prose-paths} body, .env*, other lanes' memory.md
- Push tier: operational PRs only; ready-for-review by default, canonical PR body required, no direct-to-main/destructive ops

## 8. Checkpoint
Append one lane-local line to memory.md:
`- [YYYY-MM-DDThh:mm:ssZ {runtime} {lane-role}] [TAG] {what}. {next-cycle hint}.`
For code/publish/in-progress work also include: Plan row moved, Ledger eid,
Proof, Files claimed, `handoff_status`, and next-agent resume.
Tags: SHIP / MERGED / FIX / PROMOTE / DEFER / IDLE / QC / AUDIT-N / MILESTONE.
No "everything fine" entries.
```

A prompt.md this tight fits under ~80 lines and gives any agent everything needed to run one cycle correctly.

## Common Failure Modes

Prompts fail in predictable ways. Hit one → add the missing block.

| Failure | Root cause | Fix |
|---|---|---|
| Agent edits forbidden files | Block 7 missing or vague | Enumerate forbidden paths with reasons |
| Two agents both grab the same task | Block 5 priority non-deterministic | Sharpen priority order; "first match wins" |
| Week-long lane cannot resume after context loss | Missing long-horizon handoff contract | Add canonical PLAN.md, claims, stale-proof, meter checkpoint, `handoff_status`, and next-agent resume fields |
| Lane ships 5 redundant polish PRs | Block 6 missing polish-brake rule | Add: "if last 3 ships same surface → force rotate" |
| Memory.md unreadable drift | Block 8 format sloppy or missing | Enforce one-line + tagged format |
| Agent reads wrong PLAN.md | Block 3 doesn't name the absolute path | Use absolute paths, not relative |
| Lane never exits | Block 1 missing retirement condition | Add "retires when X" to Mission |

## See Also

- [Five Principles](/concepts/principles) — the doctrine a prompt is enforcing
- [The Cycle](/concepts/cycle) — the runtime flow the prompt is trying to drive
- [PLAN.md field reference](plan-fields.md) — what the prompt's Read block is reading
- [Claude Code Lifecycle](../fleet/claude-lifecycle.md) — how the prompt fires each cycle
- [Codex Lifecycle](../fleet/codex-lifecycle.md) — same, for Codex lanes
