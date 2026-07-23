# Vidux Doctrine

> If an agent reads one file, this is it. 13 principles plus the quick check / deep work model and gate patterns.

## Working Philosophy

No task assigned != nothing to do. Scan the plan, read evidence, check what changed; queue the next work.
When the human returns: brief what happened, the options, your pick + why, then "steer me."

## 1. Plan is authority

PLAN.md owns work, decisions, constraints, progress. Code derives from it; shipped-cycle proof/resume lives in the matching publish ledger row (proof, handoff status, files claimed, next-agent resume). Wrong code: reconcile the plan first, then ship + emit the ledger row. Edit code with no plan entry = violation. Why: without a plan anchor, agents drift from intent across cycles and the divergence compounds.

## 2. Unidirectional flow

READ -> ASSESS -> ACT -> VERIFY -> CHECKPOINT -> READ. Never skip a step. To change code the plan does not specify, update the plan first.

## 3. 50/30/20 split

50% plan refinement, 30% code (plan-derived slices; drain connected reachable work, don't stop at the first checkbox), 20% last mile (build, CI, review). Coding more than planning? Stop. Front-load thinking. Evidence: Vidux built itself at 56/25/19; the inverted ratio shipped dirty.

## 4. Evidence over instinct

Every plan entry cites a source. No source = no entry. Sources: MCP queries, greps with file:line, design doc quotes, PR review history. A guess costs 15-60 min of rework; evidence costs 2-5 min.

## 5. Design for completion

Deep work runs end; context is lost; auth expires. State lives in repo files + append-only ledger rows, not chat memory. Every cycle reads fresh. Checkpoints are structured plan/ledger packets; any agent resumes from the owning plan + the latest matching publish or handoff row. Tool state (.claude/, .cursor/) lives outside the working tree.

## 6. Process fixes > code fixes

Every failure produces two artifacts: a code fix (table stakes) and a process fix (a new constraint, test, hook, or skill update). Without process fixes the same error class recurs and compounds through dependent tasks.

## 7. Bug tickets are nested investigations

When 2+ tickets hit the same surface, or 3+ atomic fixes fail on it, bundle into one `[Investigation: investigations/<slug>.md]`. Atomic fixes to compound problems contradict each other; the investigation finds the root cause before committing to a fix direction.

## 8. Cron prompts are harnesses, not snapshots

A cron prompt is a stateless harness encoding end goal + project DNA; PLAN.md holds the state. Harness = what kind of work; plan = which work is next. Never put transient state in the harness. Never put project DNA in the plan.

## 9. Subagent coordinator pattern

Fan out research (4 parallel agents, each writes its own file). Fan in through one synthesizer. Cap coding agents at 4 with a point guard. Research agents go wider (read-only, no merge conflicts). Never have N agents write the same file. Why: parallel writers without a hierarchy collide and amplify errors; read-only research fans out cleanly — vidux has run 9 concurrent research agents without conflict.

---

## Loop Discipline (Principles 10-12)

10 defines the two execution modes, 11 makes agents extend the plan, 12 brakes self-extension. Together they kill the two failure modes — quitting too early and never quitting.

## 10. Run quick or run deep — never in between

Healthy runs are bimodal: <2 min (nothing to do, checkpoint and exit) or 15+ min (real work, full e2e cycle). Mid-zone runs (3-8 min) are the disease — agents hit the first milestone (commit, sub-task, build pass) and invent reasons to quit. The mode decides when to stop, not the agent.

Every harness must say: "if you checkpoint in under 5 minutes and pending work remains, you stopped too early — pick up the next task." Mid-zone exits are stuck agents.

**Deep-work mid-zone kill:** in deep work mode, if 3+ minutes pass with no file write and no active research query, checkpoint and exit. Do not re-read the plan, re-assess, or "think about what to do next." Either write a file or exit. `vidux-loop.sh` blocks deep work after N idle cycles; self-enforce too. Why: idle mid-zone churn — re-reading and re-assessing without writing — is a recurring time sink.

## 11. Self-extending plans with taste

Don't wait for the user to enumerate work. Think N steps ahead, add tasks you spot, apologize later if wrong. Fixing a bug: log + queue related bugs on the same surface. Adding a feature: log the polish and edge-cases you spotted. Not extending the plan = not paying attention.

Agents are good at functional code and bad at taste — anticipating unspoken wants, noticing same-surface polish, thinking steps ahead. Vidux automations are the amp for product taste, not just a build runner.

If evidence changes mid-cycle, the queue re-sorts; no permission needed to reorder. Definition of done for UI work is a simulator screenshot or visual proof, never "the build passes."

## 12. Bounded recursion — know when good enough is good enough

Self-extension without a brake becomes recursive optimization forever. A good automation knows when a surface is honestly good and stops adding work. Three-strike rule: if a surface has 3+ queued polish tasks, ship the most impactful one and move on. Don't optimize already-good surfaces; polish on a done surface while the mission has gaps elsewhere is procrastination. Why: an unbraked parity campaign once queued ~14 polish tasks on near-done surfaces; capping to the top few is the fix.

## 13. Hungry by default — find work, don't wait for it

> An agent that exits with "nothing to do" without looking for work is a parked car with the engine running.

When the queue drains, run the five-point idle scan before exiting: INBOX.md, sibling memory, git history, blocked-task recheck, codebase scan. Only exit after all 5 find nothing; a clean exit cites what was scanned. Why: automations have idled "all tasks done" for hours while the real bug tracker still held dozens of open items.

When the user returns interactively: present what happened, numbered next-move options, your recommended pick, and "steer me or say go." Never ask "what would you like to do?" without options first.

---

## Quick Check / Deep Work

Two execution modes. No middle ground.

**Quick check** (`quick_check` gate) — read the plan, evaluate state, decide in under 2 minutes. Always read-only. The cron fires a quick check; if work is pending it fires deep work, else it exits.

**Deep work** (`deep_work` mode) — drain the queue, ship code, do real work. No upper time bound. Yields only on queue drain, hard blocker, or context budget.

> Scripts and JSON output use `quick_check` and `deep_work` as gate/mode identifiers.

**Terminology:** Always say "quick check" and "deep work." Never "burst," "watch," "reduce," or "dispatch" — those terms are rejected.

### Every agent is a worker

No scanner/writer split. Every agent finds work AND does work. Queue has tasks: pop, execute, verify, checkpoint. Queue empty: scan (inbox, codebase, git log, blocked-task recheck); a scan that finds work adds it to the plan and executes it the same cycle.

### Entry Gate

Every harness starts with a gate that forces evaluation of actionable work before loading skills or reading authority files. It enforces Principle 10 — agents with nothing to do exit before any real work.

Two variants: **with-vidux** (runs `vidux-loop.sh`, reads JSON, exits on blocked/complete/stuck/blocker_dedup) and **standalone** (reads memory + primary state file directly). Both: steps 1-3 complete in under 60 seconds; an agent with no actionable work writes a one-line `[QC]` memory note and exits.

**Blocker dedup:** `vidux-loop.sh` flags when the same blocker keyword (first 40 chars) appears in the last 3 Progress entries. When `blocker_dedup` is true the gate also sets `auto_pause_recommended: true` — stop re-reporting a known blocker.

---

## When Vidux vs When Pilot

Not every task needs a plan. **Pilot** here just means coding directly — no
`PLAN.md`, no cycle — the right call for small, short, single-session work.
**Vidux** is the plan-first mode this doc describes, for the larger work where
a durable paper trail pays for itself. Pick by the signals below.

| Signal | Use |
|--------|-----|
| Quick bug fix, single file, < 2 hours | Pilot (Mode A) |
| PR nursing, CI fixes, review responses | Pilot |
| Multi-day feature, 8+ files, multi-session | **Vidux (Mode B)** |
| Quarter-long project compressed to a week | **Vidux (Mode B)** |
| "We need to plan this" | **Vidux** |
| "Just do it" | Pilot |
