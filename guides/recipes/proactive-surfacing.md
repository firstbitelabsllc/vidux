# Recipe: Proactive Surfacing

> When the queue feels empty, scan — don't ask. Stale intents from days ago are real work.

## When to use

- Queue has no `[pending]` or `[in-progress]` tasks and you're about to declare `[IDLE]`
- You're tempted to ask "what should I work on next?"
- A `[DIRECTION]` entry from the Decision Log is sitting unaddressed
- A `[blocked]` task has been in that state for more than a day

## The recipe — scan in this order before going idle

**1. INBOX.md** — any findings waiting for promotion to tasks?

**2. Decision Log entries from the last 7 days** — any `[DIRECTION]` that led to a now-deferred task? Any promises that didn't translate into plan entries?

**3. `[blocked]` tasks** — does new evidence unblock any of them? Re-read the blockers against today's state.

**4. Recent `[Source: observed]` entries** — are all observations addressed, or are some dangling?

**5. Owned paths** — `git log --since=7.days` and `git status` on paths this lane owns. Any drift? Any uncommitted exploration that should become a task or be reverted?

**6. PR comments from the last 3 days** — `gh pr list --state=all --search "commenter:@me updated:>3d"`. Anything unresolved on open or recently-merged PRs?

**7. Only after all 6 find nothing** — exit `[IDLE]` and cite the scan report:

> "Scan complete: INBOX (0 promotable), Decision Log (0 stale directions), blocked tasks (2, both still blocked by Task Y), observed (0 dangling), owned paths (clean), PR comments (0 unresolved). Going [IDLE]."

## Stale-intent surfacing (separate trigger)

If any `[DIRECTION]` from 3+ days ago has no follow-up task, surface it without waiting to be asked:

> "4 days ago we wanted to unify the status-bar color logic, no task was created. Should I promote it to a task now, or is this deliberately deferred?"

Do this **at the start of the cycle**, not after finishing other work.

## Failure modes

Without this recipe:

- Queue "feels empty" so agent asks the user what to do — the user has to context-switch into planning
- `[DIRECTION]` entries from days ago rot in the Decision Log with no follow-up
- `[blocked]` tasks stay blocked because no one re-checks the blockers
- Agent declares `[IDLE]` when there's actually 3 promotable findings in INBOX.md
- Observed pattern: "Queue feels empty; stale intents from days ago sit unaddressed; agent asks for feedback instead of scanning for work."

## Example

**Wrong:**

> All tasks complete. What would you like me to work on next?

**Right:**

> Scanning: INBOX has 2 promotable findings (flicker on guest flow, duplicate status-bar logic). Decision Log has a [DIRECTION] from 4 days ago about unifying status-bar color — no task was created. I'm promoting the flicker finding to a task now. The status-bar unification is bigger; should I scope it or defer?

## See Also

- `guides/recipes/user-value-triage.md` — how to pick among the surfaced candidates
- `guides/recipes/evidence-discipline.md` — when surfacing, cite the source (INBOX line, Decision Log entry, commit)
