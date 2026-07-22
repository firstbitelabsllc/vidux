# Recipe: Evidence Discipline

> Never attribute behavior to a cause without concrete evidence. Never claim "done" without verification.

## When to use

- Explaining why something broke, flaked, or behaves unexpectedly
- About to mark a task `[completed]` in a plan file
- Tempted to write "probably" or "likely" in a root-cause claim
- Debugging a cross-system symptom (auth failure, cache staleness, cross-machine drift)

## The recipe

**1. No cause without evidence.** Cite logs, commits, diffs, traces, or concrete output. If you don't have evidence, say "I don't know yet" and investigate.

**2. "Probably" is not evidence.** According to /insights data, guesses cost 15-60 min of rework per occurrence. Assume the guess is wrong until proven otherwise.

**3. Never mark `[completed]` without running a verification command.** Build, test, curl, screenshot — in the same session — and confirm the output. A plan entry set to `[completed]` without verification evidence is a lie.

**4. State what you ran.** The commit or plan note must name the verification command and its result. "Tests pass" is weaker than "`pnpm test` → 143 passing, 0 failing (abc123)."

**5. When uncertain, split the claim.** "The token store is missing the refresh token (verified: `sqlite3 tokens.db 'select * from refresh'` returns empty). I don't yet know why vault rotation cleared it."

## Failure modes

Without this recipe:

- Agent attributes a 401 to "cross-machine activity interference" with no supporting log
- Real root cause (stale refresh token) is discovered 45 minutes later after retrying the wrong fix
- Plan shows 3 `[completed]` entries that weren't actually verified, user finds broken behavior in production
- User loses trust in the fleet's status reports

## Example

**Wrong:**

> That 401 is probably cross-machine activity interference.

**Right:**

> The 401 started after vault rotation. Checking the token store (`sqlite3 ~/.vault/tokens.db 'select refreshed_at from sessions'`) shows the OAuth refresh endpoint isn't being hit — last refresh timestamp is from before rotation. Root cause: stale refresh token. Fix: re-auth flow.

**Wrong:**

> [completed] Fixed the font loading issue.

**Right:**

> [completed] Fixed the font loading issue — ran `pnpm build && pnpm e2e` (all 47 pass), screenshot attached showing Inter renders correctly on the guest flow.

## See Also

- `guides/recipes/visual-proof-required.md` — the specific verification flavor for UI work
- `guides/recipes/env-var-forensics.md` — concrete evidence checklist for env-var mysteries
