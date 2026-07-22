# Five Principles

The doctrine. Governs every agent decision: what to do next, when to gather evidence, when to stop, how to leave things for the next agent.

**publish packet** = ledger row carrying task id, proof, handoff status, files claimed, next-agent resume (defined in [The Cycle](/concepts/cycle)).

## Principle 1: Plan First, Code Second

PLAN.md is the planning authority for queue, decisions, constraints, progress. Code derives from plan state. To change code, update the plan first; to claim a shipped cycle, pair the plan update with the publish packet.

Every plan entry cites evidence — a codebase grep, PR comment, design doc quote, team chat message. **A plan entry without evidence is a guess. Guesses cause rework.** Evidence: evidence-first coding costs 2-5 min research, saves 15-60 min rework.

```markdown
# Bad (no evidence)
- [pending] Task 1: Add rate limiting

# Good (evidence cited)
- [pending] Task 1: Add rate limiting [Evidence: Sentry logs — 47 burst errors in 7 days, src/api/login.ts:42 — no throttle]
```

## Principle 2: Design for Interruption

Every session ends. Context will be lost. Auth will expire. State lives in repo files plus append-only ledger rows, never in memory. Checkpoints are structured, not freeform. Any agent resumes from the last plan/ledger packet.

After any interruption, re-read PLAN.md and evidence/ from disk. NEVER trust summaries or memory for plan details.

Every cycle updates the owning plan/progress record. Any publishable branch, PR, or release also emits the publish packet. A fresh agent reads plan + ledger packet and knows exactly where things stand.

## Principle 3: Investigate Before Fixing

Bug tickets are not line items. Before coding, map root cause, related surfaces, impact. A fix without investigation is a guess.

2+ tickets touch the same surface → bundle into one investigation. It produces a root cause analysis, impact map, fix spec. Investigation notes live locally in the working tree until the fix ships — not a separate deliverable. No investigation PR, no evidence PR, no plan-flip PR. The unit of progress is code change.

```
Bug reported: "checkout double-charges on fast retry"

Wrong:
- Add idempotency check → ship → done

Right:
- Investigation: map all checkout code paths
- Root cause: no in-flight guard + no idempotency key
- Impact map: affects web and mobile checkout
- Fix spec: submit.ts:42 + retry.ts:18
- Tests: cover the retry race condition
- Gate: build + test + visual proof
```

## Principle 4: Self-Extend with a Brake

Agents add tasks they discover. Fix a bug → log the related bugs you saw. Add a feature → log the edge cases you spotted.

But a shipped surface that works is done — stop polishing, move to the next gap. Polish on a done surface while the mission has gaps elsewhere is procrastination. Re-extend plans only when investigation reveals new surfaces, never to tweak finished work.

**The brake:** Surface works and tests pass → log what you noticed, move to the next task. Don't re-open completed work to "clean it up."

**Evidence changes mid-cycle → the queue re-sorts.** No permission needed; note the reorder in the next Progress entry.

## Principle 5: Prove It Mechanically

Never assert "it works." Run the build, run the tests, show the screenshot. Definition of done for UI work is visual proof, never just "the build passes."

When an audit or grep produces a count or classification, spot-check at least one entry from each category before deciding on it. A grep hit is a lead, not a fact — a line matching "git push" might be a prohibition ("NEVER git push"), not an instruction.

```
Wrong: "The rate limiter is working — I can see it in the code."

Right:
- Build: passes (17 tests, 0 failures)
- Test: rate_limit_test.ts passes (5/5)
- Manual: curl -X POST /api/login 6x → 6th request returns 429
```

**After a failure:** produce two artifacts — a code fix (immediate repair) and a process fix (a hook, test, constraint, or plan update). The process fix is the valuable output; it makes the system smarter next time.

## The Quick Check / Deep Work Model

Beyond the five principles, every run is one of two modes:

| Mode | Duration | Description |
|---|---|---|
| **Quick Check** | < 2 min | Nothing to do. Scan 5 surfaces, prove clean, exit with evidence. |
| **Deep Work** | 15+ min | Real work. Execute tasks until queue empties or a blocker hits. |

**The mid-zone (3-8 min) is the anti-pattern.** "A little checking" plus "a small fix" without committing to either mode produces the worst outcomes: shallow investigation that misses root cause, partial fixes leaving the codebase worse than before, checkpoints that don't tell the next agent what happened.

**Quick Check exit criteria:** Cite exactly what was scanned (file paths, git log range, grep patterns). A quick check without proof is an agent that gave up.

**Deep Work exit criteria:** Queue drained, or explicit blocker documented. Never exit deep work because progress feels slow.
