# Ready-PR Flow - Core Doctrine

Cloud-agnostic. Works with any git remote that supports `gh pr create`. No paid-service dependencies.

> Historical note: this file keeps the `draft-pr-flow.md` path so old links do not break. The current doctrine is ready-PR-first; drafts are a WIP exception, not the default.

## Why

Local worktrees are ephemeral. Crashes, disk cleanup, and `git worktree remove` destroy in-progress work silently. The owning PLAN.md plus matching publish ledger row is the durable shipped-work recovery packet; Pull requests on GitHub are transport/review handles. `gh pr list` shows which branch-backed work needs review or nursing, and the PR body points the next agent back to the owning plan and ledger row.

Ready-for-review PRs also let review bots, preview comments, and CI gates run immediately. Draft PRs are useful only when a real gate is missing and the PR should not yet enter review.

## The Flow

Every automation lane that ships code follows this after a green local build + test:

```bash
# 0. Update the owning PLAN.md Progress/Tasks/Drift Log before publish.
#    Record what changed, proof, handoff_status, path-like files claimed/claims, and resume point.

# 1. Emit the publish ledger row before the branch leaves the machine.
# "$LEDGER_EMIT" is your own configured ledger-emit executable (wired via
# `vidux-release.sh --ledger-emit <path>` or the LEDGER_EMIT env var) --
# scripts/lib/ledger-emit.sh is a sourced-only function library, not a
# --event-flag CLI.
LEDGER_EID="evt_$(date -u +%Y%m%d%H%M%S)_${RANDOM}"
"$LEDGER_EMIT" \
  --event publish \
  --repo-path "$(pwd)" \
  --lane "<lane-name>" \
  --task-id "<task-id>" \
  --plan-path "<PLAN.md>" \
  --proof "<command/artifact that passed>" \
  --handoff-status done \
  --resume "<resume point>" \
  --file "<changed-file-or-plan>" \
  --claim "<path-like-claimed-file>" \
  --skills vidux \
  --eid "$LEDGER_EID" \
  --summary "<1-3 bullet summary>"

# 2. Push the worktree branch to origin.
git push origin HEAD:claude/<lane-name>-<task-id>

# 3. Build the canonical PR body.
python3 scripts/vidux-pr-body.py \
  --lane "<lane-name>" \
  --task "<task-id>" \
  --summary "<1-3 bullet summary>" \
  --plan-path "<PLAN.md>" \
  --proof "<command/artifact that passed>" \
  --handoff-status done \
  --ledger "$LEDGER_EID" \
  --file-claimed "<path-like-claimed-file>" \
  --review-pass "invariant-audit:pass:<plan/ledger/drift proof>" \
  --review-pass "regression-runner:pass:<tests/docs proof>" \
  --review-pass "adversarial-reviewer:pass:<overclaim/stale-proof check>" \
  --resume "<what the next cycle should do if this PR stalls>" \
  --change "<1-3 bullet summary>" \
  > /tmp/vidux-pr-body.md

# 4. Open a ready-for-review PR by default.
gh pr create \
  --base main \
  --head "claude/<lane-name>-<task-id>" \
  --title "[<lane-name>] <task summary>" \
  --body-file /tmp/vidux-pr-body.md
```

Use `gh pr create --draft` only when the PR is true WIP or a required gate is missing; run `gh pr ready <number>` as soon as the gate passes.

Never push directly to `origin/main`. Sync the local base before each cycle with `git fetch --prune origin`.

Delete worktrees only after the plan/ledger packet exists, the PR branch is safely pushed, and the PR body carries the ledger eid plus resume point.

## Branch Naming

`claude/<lane-name>-<task-id>` or `codex/<lane-name>-<task-id>` - predictable, greppable, lane-attributable.

Examples:

- `claude/coach-p0-T3`
- `claude/acme-bug-fixer-ABv07GVF`
- `codex/web-executor-5.2.1`

## PR Body Template

The body MUST carry these fields so any agent or human can resume:

| Field | Purpose |
|---|---|
| **Lane** | Which automation created this PR |
| **Plan task** | Which `PLAN.md` task this addresses |
| **Plan path** | The owning plan that moved before publish |
| **Proof** | Command or artifact proving the state being published |
| **Ledger** | Ledger eid or dry-run payload path for the publish row |
| **Handoff status** | `done`, `in_progress`, `blocked`, or `needs_review` |
| **Files claimed** | Path-like changed/claimed files a next agent must inspect first |
| **Resume point** | What the next cycle should do if this PR stalls |

## Transport Recovery Via `gh pr list`

When a worktree is lost:

```bash
gh pr list --state open --json number,title,isDraft,headRefName --jq '.[]'
```

Each open PR is a transport/review handle. Before checkout, read the PR body for its plan path and ledger eid, then re-read the owning plan plus matching publish ledger row. Inspect the branch with `gh pr checkout <number>`. If the PR is draft and no longer blocked, flip it ready with `gh pr ready <number>`.

## Fallback

If `gh pr create` fails (auth issue, network, no `gh` CLI):

1. Keep the already-emitted publish ledger eid (`$LEDGER_EID`) and branch name.
2. Record the failed PR creation in the owning PLAN.md with proof, `handoff_status=needs_review`, path-like files claimed/claims, and next-agent resume; use `memory.md` only as a lane-local note.
3. Do NOT fall back to pushing main.
4. The next cycle retries PR creation against the existing branch and reuses the existing ledger reference.

## What This Does Not Cover

- Who reviews the PR. Use the repo's normal review-bot and human-review rules.
- Auto-merge policy. Core vidux says merge only when checks are green and required review findings are addressed; personal overlays may authorize more aggressive merging.
- Paid-service integrations. Those live in `/vidux` Part 2 scope as composable add-ons.
- Personal pushes. Human-owned flows stay under that repo's local policy.

## Adopting This In A Lane Prompt

Replace any existing push policy with the block below. In particular, replace any "stop after branch push" instruction with "push branch + create ready PR," and any "draft PR only" instruction with "ready PR by default; draft only for WIP/missing gate."

```markdown
**PUSH POLICY (ready-PR-first per vidux):**
After green build + test in the worktree:
1. Update owning PLAN.md Progress/Tasks/Drift Log with proof, `handoff_status`, path-like files claimed/claims, and resume point.
2. Set `LEDGER_EID="evt_$(date -u +%Y%m%d%H%M%S)_${RANDOM}"`, then emit publish ledger row before push via your configured ledger emitter: `"$LEDGER_EMIT" --event publish --repo-path "$(pwd)" --lane "<lane>" --task-id "<task-id>" --plan-path "<PLAN.md>" --proof "<command/artifact>" --handoff-status done --resume "<resume point>" --file "<path>" --claim "<path>" --skills vidux --eid "$LEDGER_EID" --summary "<summary>"`.
3. Push branch: `git push origin HEAD:claude/<lane>-<task-id>`.
4. Body: `python3 scripts/vidux-pr-body.py --lane "<lane>" --task "<task-id>" --summary "<summary>" --plan-path "<PLAN.md>" --proof "<command/artifact>" --handoff-status done --ledger "$LEDGER_EID" --file-claimed "<path>" --review-pass "invariant-audit:pass:<plan/ledger/drift proof>" --review-pass "regression-runner:pass:<tests/docs proof>" --review-pass "adversarial-reviewer:pass:<overclaim/stale-proof check>" --resume "<resume point>" --change "<summary>" > /tmp/vidux-pr-body.md`.
5. Ready PR: `gh pr create --base main --head "claude/<lane>-<task-id>" --title "[<lane>] <summary>" --body-file /tmp/vidux-pr-body.md`.
6. Draft only for true WIP or a missing gate; run `gh pr ready <N>` as soon as the gate passes.
7. NEVER push directly to origin/main.
8. Fallback: if `gh pr create` fails, keep the branch plus `$LEDGER_EID`, record the failed PR creation in the owning PLAN.md with `memory.md` only as a lane-local note, and retry PR creation next cycle. Never push main.
```

## Validated

Draft-first was validated on 2026-04-12 via `firstbitelabsllc/vidux#4`. Ready-first supersedes it because modern review pipelines skip or delay drafts, hiding the feedback automation lanes need to nurse and merge safely.
