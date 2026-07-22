# Vidux Writing Style — say less

Agents follow ~150-200 instructions reliably. Compliance degrades **uniformly** as you add more — one anecdote dilutes *every* rule, not just itself. So: spend the budget on testable directives. Delete the prose around them. This doc is a model of its own rules.

---

## 1. State the rule. Don't narrate it.

Drop "Why this exists / Why this matters" framing. Keep a story ONLY if it carries a hard number; fold it into a one-clause `Evidence:` tag and move the long version to an appendix.

<bad>
PLAN.md is the queue/planning authority for work, decisions, constraints, and progress. Code is derived from that plan state... *Why this matters: The Acme iOS fleet drifted 400+ lines from spec in 6 cycles before this rule existed.*
</bad>

<good>
PLAN.md owns work, decisions, constraints, progress. Code derives from it. Edit code with no plan entry = violation. Evidence: Acme drifted 400+ lines in 6 cycles pre-rule; SlopCodeBench: agent degradation is monotonic.
</good>

Anecdotes with no number are pure decoration — cut them whole.

---

## 2. Every line must be true/false testable

Replace mood lines with falsifiable directives an agent can check against.

<bad>
Silence is not confirmation. Be hungry for steering. The whole point is anticipating what needs to happen next.
</bad>

<good>
No assigned task != no work: scan the plan, read evidence, check what changed. Brief the human — what happened, options, your pick — then "steer me."
</good>

<bad>
If you are coding more than planning, stop. Front-load thinking.
</bad>

<good>
Coding more than planning? Stop. Target 50% plan / 30% code / 20% last-mile.
</good>

---

## 3. Define repeated phrases ONCE as a named term

The field list "publish ledger row carrying proof, handoff status, files claimed, path-like claims, and next-agent resume" appears 15+ times. Name it once; reference it forever.

<bad>
...pair the shipped change with a publish ledger row carrying proof, handoff status, files claimed, path-like claims, and next-agent resume point.
</bad>

<good>
publish packet = {summary, task-id, plan-path, proof, handoff_status, files, claims, resume}

...ship the change + emit the publish packet.
</good>

---

## 4. Tables/lists beat prose for enumerable content

Parallel prose paragraphs ARE a table. Same shape repeated N times = N rows.

<bad>
**1. Brainstorm-Plan-Execute-Verify Chain. What it does.** Enforces a strict phase sequence... **How Vidux adopts it.** ... **What we do NOT adopt.** Superpowers' brainstorm phase is interactive...
</bad>

<good>
| Pattern | Source | Adopt | Skip |
|---|---|---|---|
| Brainstorm->Plan->Execute->Verify | superpowers (128K) | plan-as-gate (LOOP Step 3) | interactive brainstorm; skill-per-phase |
</good>

But don't inflate ONE sentence into a multi-column band. Prose for one claim; table for many.

---

## 5. Reference, don't paste

Point to a canonical file/script. Never render the same content twice in two formats.

<bad>
### Configuration
{hook JSON with prompt text}

### What gets injected
> VIDUX CHECKPOINT: Before this session ends, ensure you have: {identical text re-printed verbatim}
</bad>

<good>
Reminds the agent to checkpoint before exit so the next session resumes. Config: see `settings.local.json` example (shown once).
</good>

Move war-stories out of the kernel doc:

<bad>
**Real-world incident (2026-05-12).** `...html` dropped into `artifacts/` as a symlink... rendered 403... {+25 lines of walkthrough}
</bad>

<good>
Artifacts sharing an inode with a canonical source must be HARD links, not symlinks (server fails-closed on out-of-tree symlinks -> 403). Full case: `browser/INCIDENTS.md`.
</good>

---

## 6. One concept per chunk

Welded mega-paragraphs hide rules. Split 4 rules into 4 bullets.

<bad>
Prove it mechanically: hit the live surface not the merge, and spot-check one entry per audit category, and every failure gets a code fix and a process fix, and a wiring PR... {354 words, 4 rules}
</bad>

<good>
Prove it mechanically:
- Hit the live surface, not the merge.
- Spot-check 1 entry per audit category.
- Every failure -> code fix + process fix.
- Wiring a pending path: activate its skipped tests or delete them. No stale skips.
</good>

---

## 7. Lead with the hard gate. Repeat it at the foot.

U-shaped attention: the start and end of a file get read. Don't bury a NEVER mid-paragraph.

<bad>
Prereqs: clone the repo... Verify: resolve the plan path... Safety: do not create duplicate plans, execute local-CI lanes, install LaunchAgents, delete worktrees, or push/merge unless the owning plan and user authorization make that operation explicit.
</bad>

<good>
NEVER: duplicate plans, run local-CI lanes, install LaunchAgents, delete worktrees, or push/merge unless plan AND user auth make it explicit.
Prereqs: clone the repo + ~/Development/vidux, install toolchain, read AGENTS.md/PLAN.md.
Verify: resolve plan path, inspect git state, run the smallest repo-owned proof.
</good>

---

## 8. One name per concept

The core loop has FOUR names across four files. Pick one 5-verb spine.

<bad>
Gather->Plan->Execute->Verify->Checkpoint (DOCTRINE)
READ->ASSESS->ACT->VERIFY->CHECKPOINT (SKILL)
Orient->Choose->Execute->Handoff (Harness Contract)
Read->Assess->Act->Checkpoint->Complete (LOOP)
</bad>

<good>
READ -> ASSESS -> ACT -> VERIFY -> CHECKPOINT (canonical, defined in loop.md; every other file links it).
</good>

---

## 9. Grep-and-kill list

These cost budget and drive no behavior. Find them, rewrite to a rule or delete.

<bad>
try to / be hungry for / crystal clear / the whole point / masquerading as / It's worth naming / two seams worth naming / The canonical failure this prevents / Despite having only N stars / This is the single rule that / wearing a lab coat / a parked car with the engine running / dramatic / genuinely / honestly / badly stale / pure overhead
</bad>

<good>
Keep ONE memorable metaphor if it earns its line. Delete the rest. Prefer the bare imperative.
</good>

---

## 10. Entry formats (task / evidence / progress)

**Task:**
<bad>- [ ] We should probably go through and make sure the checkout flow properly handles the edge case where a user has an expired session, since this has caused problems before</bad>
<good>- [ ] Checkout: handle expired-session edge case. Evidence: prior 403 in #34238.</good>

**Evidence line:**
<bad>It's worth noting that based on my investigation the currency API actually returns integers and not ISO codes as one might assume.</bad>
<good>Evidence: currency API returns integers, not ISO codes (worker/fx.ts:42).</good>

**Progress entry:**
<bad>I went ahead and made good progress on the reviews widget — got it mostly wired up and it's looking pretty solid, will pick up the remaining bits next session.</bad>
<good>Progress: reviews widget wired to metaobject backend. Done: render + submit. Next: Turnstile gate (Leo-gated). Files: reviews-widget.js, worker/reviews.ts.</good>

---

## The mandate

Vidux's §Voice & Tone says "terse, concrete, evidence-cited, no hedging." Hold the docs to it. Cutting prose RAISES compliance — shorter is more obeyed.