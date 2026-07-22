# Recipe: User-Value Triage

> Protect the user-visible work ratio before the fleet drowns in audit and hygiene PRs.

## When to use

- Starting a new cycle and the queue has a mix of audit, docs, and bug-fix tasks
- Recent merges feel like "meta work" (ghost-checks, audits, docs sweeps)
- Users have reported bugs that haven't been addressed while the fleet ships process PRs
- /insights or a retro surfaces a skewed audit-to-user-fix ratio

## The recipe

**1. Classify every candidate task before picking.** Assign exactly one label:

- `user-visible-fix` — a real bug a human would notice
- `feature` — new user-facing capability
- `audit-hygiene` — ghost checks, audits, lint sweeps
- `docs` — README, skill files, guides
- `infra` — CI, tooling, internal plumbing

**2. Compute the rolling ratio at the start of each cycle.** Look at merges shipped this week:

- If `audit-hygiene + docs` exceeds 25% of merges, self-flag.
- If the ratio of `audit-hygiene` to `user-visible-fix` exceeds 1:2, stop and reprioritize before picking the next task.

**3. When the queue has both cheap audit tasks and real bug fixes, pick the bug fix.** Audit work is the snack, user fixes are the meal.

**4. Surface the ratio out loud.** Say it in the first message of the cycle so the user can override:

> "This week: 6 audit, 2 user-fix (75% meta). Picking Task X (user-reported flicker) instead of the next docs audit."

## Failure modes

Without this recipe:

- Fleet ships a steady stream of audit/ghost-check/docs PRs (the findings from /insights)
- Real bugs sit in the queue for days while the audit pile gets smaller
- User feels like the fleet is busy but nothing they can see is improving
- Ratio drift goes undetected because no one computes it

## Example

**Wrong:** Queue has 4 audit tasks and 1 user-reported flicker. Agent picks the first audit task because it's at the top of the list.

**Right:** Agent classifies the queue, computes "cycle ratio 6:2 audit:user-fix — 75% meta," and says:

> "Rather than the next `docs(audit)` task, picking Task X (user-reported flicker fix). Will return to the audit queue once the ratio is back under 25%."

## See Also

- `guides/recipes/proactive-surfacing.md` — how to find user-visible work when the queue feels empty
- `guides/recipes/lightweight-first.md` — don't wrap user-fixes in heavy process
