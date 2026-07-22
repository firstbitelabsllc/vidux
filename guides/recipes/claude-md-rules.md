# Recipe: CLAUDE.md / AGENTS.md Rules

> Rules to drop into your repo's agent instruction file. Each section is copy-pasteable. Trim what doesn't apply.

## When to use

- Seeding a new repo's `CLAUDE.md`, `AGENTS.md`, `.cursor/rules`, or equivalent
- Auditing an existing instruction file after a rule was violated in practice
- Retrofitting an older repo where agents keep re-learning the same lessons

## How to adopt

Paste the sections below into your agent instruction file. Keep the heading and rule sentence; trim the prose. Minimum viable skeleton at the bottom.

---

## Section: Re-read before edit

```markdown
Before editing a memory file, state file, or JSONL (anything you or another
agent recently wrote), re-read it in the same turn. Stale content causes
whitespace mismatches and silent corruption. After a failed Edit, never
guess the fix — re-read the file, then retry with the exact current content.
```

**Why:** Append-heavy multi-agent files mean a cached view from 30 seconds ago is already wrong.

## Section: Verify before completing

```markdown
Never mark a task [completed] or assert "it works" without running the
verification command (build, test, curl, screenshot) and confirming the
output in this session. A plan entry set to [completed] without
verification evidence is a lie. State the command you ran and its result
in the commit or plan note: "pnpm test → 143 passing, 0 failing (abc123)"
is evidence; "tests pass" is not.
```

**Why:** Unverified completion is the #1 source of lost trust between user and fleet.

## Section: Simple / creative asks get direct answers

```markdown
For simple copy or creative requests (hero text, tagline, CTA wording,
button label, email subject), respond directly with 2-3 options. Do NOT
invoke brainstorming skills, spin up TaskCreate chains, or write a plan
file. Save structured workflows for multi-surface design work.
```

**Why:** Heavy machinery on light asks wastes time and annoys the user. See `guides/recipes/lightweight-first.md`.

## Section: Evidence discipline

```markdown
Don't attribute behavior to a cause without concrete evidence. Cite logs,
commits, diffs, traces, or concrete output. If you don't have evidence,
say "I don't know yet" and investigate. "Probably X" is a guess, not a
diagnosis — assume it's wrong until proven.
```

**Why:** See `guides/recipes/evidence-discipline.md` for the full recipe. Guesses cost 15-60 min of rework per occurrence.

## Section: No tech-stack attribution in product UI

```markdown
Never add "Built with Next.js", "Powered by Vercel", "Made with Tailwind",
or similar tech-stack credits to the product UI unless the user explicitly
asks. The brand is the builder, not the SaaS showcase. Remove these on
sight in design PRs.
```

**Why:** A framework-default habit that dilutes the brand. Users rarely notice when it's gone; they always notice when it's there.

## Section: Git safety — per-action destructive authorization

```markdown
Push tiers:

- Tier 1 (ready PRs, feature branches): safe after publish propagation; no approval needed. Use draft only for true WIP or a missing gate.
- Tier 2 (direct-to-main, merge to trunk): session-scope authorization required, plus the same publish propagation before the push/merge.
- Tier 3 (destructive: force-push, branch delete, git reset --hard, history
  rewrite): per-action authorization required, every time.

Every commit, push, PR, direct-to-main update, or trunk merge is a publish
action: update the owning PLAN.md Progress/Tasks or Drift Log first, then emit,
via your configured ledger emitter,
`"$LEDGER_EMIT" --event publish --summary "<summary>" --task-id <task-id> --plan-path <PLAN.md> --proof "<command/artifact>"
--handoff-status <done|in_progress|blocked|needs_review> --resume "<resume point>"
--file <changed-file>
--claim <claimed-file>`. Carry the ledger eid into the PR, merge note, or final
handoff with files claimed and the next-agent resume point.

Never use --no-verify, --no-gpg-sign, or hook-skipping flags unless the
user explicitly requests them per-action. If a hook fails, investigate and
fix the underlying issue.
```

**Why:** A single unreviewed `git push --force origin main` can erase a week of work. Tiered authorization is cheap; recovery is not.

## Section: Trunk-first branch discipline

```markdown
Start every code change from the current trunk (usually `main`). Run
`git fetch origin && git log origin/main..HEAD` before committing — if
trunk has moved, rebase or restart from `origin/main`. Worktrees are
disposable integration helpers, not the source of truth. A merge back to
trunk is not enough by itself; the publish ledger row with proof, handoff
status, files claimed, and next-agent resume is the done signal.
```

**Why:** Long-lived feature branches diverge silently. Trunk-first keeps the merge surface small and conflicts local.

## Section: Anti-loop discipline

```markdown
- 3-strike escalation: if the same command fails 3 times with the same
  error, stop and re-read the file / re-check assumptions. Don't retry a
  4th time in a sleep loop.
- Same-command ban: after a failed command, don't run the identical
  command again hoping for a different result. Change an input or abort.
- All-blocked early exit: if every PLAN.md task is [blocked] and every PR
  is failing, exit the cycle with a [QC] checkpoint. Don't improvise.
- Compaction survival: assume every file you've read may be absent after
  compaction. State orientation lives on disk: PLAN.md plus publish ledger
  rows carry shipped-work truth; memory.md is the lane-local cycle log, not
  chat context.
```

**Why:** Loops consume tokens and produce no progress. Escalation is cheaper than 20 retries.

---

## Minimum viable skeleton

If you copy only one section, copy this:

```markdown
## Agent rules (non-negotiable)

1. Re-read memory/state/JSONL files in the same turn before editing them.
2. Never mark [completed] without a verification command + its output.
3. Simple creative asks (copy, taglines) → 2-3 direct options, no skills.
4. No cause attribution without concrete evidence; "I don't know yet" beats a guess.
5. No tech-stack attribution ("Built with X") in product UI unless the user asks.
6. Destructive git (force-push, reset --hard, branch delete) needs per-action authorization.
7. Every code change starts from origin/main. Any commit, push, PR, direct-to-main update, or trunk merge must update the owning PLAN.md and emit a publish ledger row with proof, handoff status, files claimed, and next-agent resume before done is claimed.
8. After 3 same-error failures, stop and re-diagnose. Don't sleep-loop.
```

## See Also

- `guides/recipes/evidence-discipline.md` — full evidence recipe
- `guides/recipes/lightweight-first.md` — when to skip the heavy machinery
- `guides/recipes/visual-proof-required.md` — verification for UI work
- `SKILL.md` — the five vidux principles (required reading before any of this)
