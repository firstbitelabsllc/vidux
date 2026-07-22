# Automation Recipes

Ready-to-deploy automation patterns for vidux fleets. Each recipe gives: when to use it, the trigger type, a complete prompt template, and the review pipeline it plugs into.

All recipes follow ready-PR-first discipline: automation opens ready-for-review PRs by default, never direct-to-main. Drafts are reserved for true WIP or missing gates.

---

## Trigger Types (platform-agnostic)

Recipes describe trigger *patterns*, not platforms. Map them to whatever automation primitive your agent platform offers:

| Trigger pattern | Fires when | Example platforms |
|---|---|---|
| **Scheduled** | Cron expression or interval matches | CronCreate (session-scoped), cloud scheduled jobs, CI cron |
| **Event-driven** | External webhook fires (PR, push, issues, deploy, etc.) | GitHub Actions, cloud webhooks, repo hooks |
| **On-demand** | Triggered by a manual action or another automation | CLI invocation, API POST, another lane's output |

A single lane can combine triggers (e.g., scheduled nightly + fires on every new PR). Platform-specific trigger wiring belongs in `/vidux` Part 2 and `references/automation.md`, not here.

---

## Recipe 1: Fleet Watcher — DEPRECATED (2026-04-17)

> ⚠️ **Deprecated.** Fleet Watcher is an orchestration smell — a scheduled lane reading other lanes' state to report drift the writer couldn't self-detect. It adds JSONL, memory.md writes, and cross-lane reads without catching bugs the writer couldn't already see in its own logs. Fleet health belongs in the coordinator's own cycle (it scans its queue each fire) or a one-shot manual audit — not a standing scheduled lane. **Do not build new Fleet Watcher lanes.**

**What it was:** Scheduled (every 2h) read-only coordinator that scanned every lane's memory + ledger + trunk, classified each lane (SHIPPING / IDLE / BLOCKED / CRASHED / STUCK), and escalated stuck lanes — never editing code or plans.

---

## Recipe 2: PR Reviewer

**What:** Automated code review pipeline triggered when an automation lane creates or updates a PR. Combines review-bot output, an architecture review agent, and mechanical checks into a single structured verdict.

**Trigger:** Event-driven — PR opened or synchronized. Filter to automation branches only (convention: `claude/`, `codex/`, or `auto/` prefix).
**Role:** Reviewer (read-only, never pushes code)

### Prompt Template

```
Use vidux as PR reviewer.

Mission: Review PRs from automation lanes. Post structured feedback.
Never approve, never merge unless this lane's authority explicitly allows it.

WHEN TRIGGERED (PR opened or updated):
1. Read the PR diff: gh pr diff <number>
2. Read the linked plan task (PR body carries task ID)

REVIEW PIPELINE (run all three, combine results):

Step 1 — Code review bot output:
  If an AI code-review bot is wired to the repo, read its comments.
  Extract: issues found, severity, suggested fixes.

Step 2 — Architecture review:
  Spawn a code-review agent with the diff.
  Check: scope creep, missing tests, style drift, security.

Step 3 — Mechanical checks:
  - Does diff touch only files listed in the task spec?
  - Do new functions have test coverage?
  - Any TODO/FIXME/HACK added without a plan task?
  - Any secrets, .env files, or credentials in the diff?

POST REVIEW as PR comment:
  ## Automated Review
  **Bot review:** [pass/issues] — <summary>
  **Architecture:** [pass/issues] — <summary>
  **Mechanical:** [pass/issues] — <summary>
  **Verdict:** READY_FOR_HUMAN | NEEDS_WORK | BLOCKED

If NEEDS_WORK: add inline review comments on specific lines.
If BLOCKED: label the PR and flag in the fleet watcher's next cycle.
Never approve. Never merge. Never mark ready-for-review.
```

### When to Use

Every fleet that creates automation PRs. This is the quality gate between "automation wrote code" and "merge" — reviewers get a pre-screened summary instead of a raw diff with no context.

### Review Bot Setup (optional)

If an AI code-review bot or static-analysis service is wired to the repo, the Bot review step reads its comments; otherwise Architecture + Mechanical checks still provide value. Platform-specific wiring lives in `/vidux` Part 2 and `references/automation.md`.

---

## Recipe 3: PR Lifecycle Manager

**What:** Tracks all open automation PRs across repos. Detects stale drafts, monitors CI status, and surfaces PRs ready for merge.

**Trigger:** Scheduled, every 1 hour
**Role:** Coordinator or tracker (merge only if the lane authority explicitly allows it)

### Prompt Template

```
Use vidux to track PR lifecycle across all repos.

Mission: No PR goes stale. Every reviewed PR gets merged, fixed, or closed.

READ:
1. For each repo in scope: gh pr list --state open --json number,title,isDraft,createdAt,headRefName,statusCheckRollup
2. Filter to PRs from automation lanes (branch prefix convention: claude/, codex/, auto/)
3. Read PR comments for review verdicts (READY_FOR_HUMAN / NEEDS_WORK / BLOCKED)

CLASSIFY each PR:
- FRESH: created < 24h ago, no review yet -> waiting for PR Reviewer
- REVIEWED: has review verdict → action depends on verdict
- DRAFT: still draft after local gates passed -> run or request `gh pr ready <N>`
- STALE: created > 48h ago with no activity -> flag for cleanup
- FAILING: CI checks failing -> flag for investigation
- READY: review passed + CI green -> merge if lane authority allows, otherwise notify promoter

ACTION:
- READY PRs: merge when authorized, otherwise post a summary to the promoter's preferred notification channel (email, Slack, or plain digest)
  "3 PRs ready: <project-a>#283, <project-b>#44, <project-c>#12"
- STALE PRs: add comment "This PR has been open 48h+ with no activity. Close or update."
- FAILING PRs: check if the failure is flaky (re-run) or real (flag for the owning lane)

OUTPUT: PR dashboard — one line per open PR with status + age + review verdict.

Never merge a draft, failing PR, or PR with unaddressed required review findings. Never approve. Never close unless explicitly stale > 7 days with no commits.
```

### When to Use

Any fleet using ready-PR-first discipline. Without a lifecycle manager, the fleet keeps creating new PRs while old ones rot.

---

## Recipe 4: Observer Pair — DEPRECATED (2026-04-17)

> ⚠️ **Deprecated.** Observer Pair is the Fleet Watcher smell applied per-writer: extra memory.md files, cadence-offset cycles, and cross-lane reads for bugs the writer couldn't see. Observers catch far less drift than expected, and most of what they catch is better fixed by editing the writer's prompt. See `references/automation.md` Sections 3 / 8. **Do not build new Observer Pair lanes.**

**What it was:** Scheduled (offset from writer cadence) strictly read-only audit of a writer lane's PLAN/PROGRESS/memory + git log + ledger. Checked FSM compliance, chronological + append-only progress, completions-match-commits, no strategic drift / scope creep, valid evidence citations; emitted a Summary / Findings / Verdict (SHIPPING | IDLE | WARNING | BLOCKED | CRASHED) audit file the writer read each cycle (WARNING = fix before any other task). Never edited code or plan.

---

## Recipe 5: Deploy Watcher

**What:** Monitors deployment status after a PR merges to main. Has a hard exit condition — once verified, it stops.

**Trigger:** GitHub event — `push` to main branch
**Role:** Verifier (read-only, time-bounded)

### Prompt Template

```
Use vidux as deploy watcher.

Mission: Verify deployment succeeded after merge. Exit after confirmation.

WHEN TRIGGERED (push to main):
1. Identify the merged PR from the push commit
2. Check deployment platform:
   - Vercel: vercel inspect or check deploy URL
   - App Store: check fastlane status or TestFlight
   - Custom: check the repo's deploy mechanism

VERIFY:
- Is the deployment live?
- Does the deployed version match the merged commit SHA?
- Any error logs in the first 5 minutes?

EXIT CONDITIONS (CRITICAL — learned from Apr 2026 incident):
- Deployment verified successfully → log to ledger, EXIT. Do not re-verify.
- Deployment failed → log failure, create [blocked] task in PLAN.md, EXIT.
- 3 checks with no deployment detected → log timeout, EXIT.
- NEVER verify more than 3 times. The stuck cron that re-verified 300+ times
  is the anti-pattern this recipe prevents.

OUTPUT: One ledger entry with deploy status + commit SHA + verification time.

After EXIT, this routine does not fire again until the NEXT push to main.
```

### When to Use

Any repo with automated deployments. Without an exit condition, deploy watchers are the #1 source of wasted cycles (proven in production).

---

## Recipe 6: Trunk Health

**What:** Periodic check of repository health: dirty checkouts, diverged branches, stale worktrees, failing CI.

**Trigger:** Scheduled, every 4 hours
**Role:** Infrastructure monitor (read-only)

### Prompt Template

```
Use vidux for trunk health monitoring across all active repos.

Mission: Catch infrastructure rot before it blocks the fleet.

CHECK (for each repo in ~/Development/ with active automation):
1. Trunk status: git -C <repo> status --short --branch
2. Divergence: git rev-list --count HEAD..origin/main (behind) and origin/main..HEAD (ahead)
3. Stale worktrees: git worktree list | count entries older than 24h
4. CI status: gh run list --limit 3 -- is the latest green?
5. Branch hygiene: git branch -r | count automation branches (claude/*, codex/*) not merged

CLASSIFY each repo:
- HEALTHY: clean trunk, not diverged, CI green, < 5 stale worktrees
- WARNING: dirty trunk OR diverged > 5 commits OR CI red
- CRITICAL: diverged > 20 commits OR 10+ stale worktrees OR trunk dirty with uncommitted plan changes

ACTION:
- WARNING repos: log finding, recommend fix
- CRITICAL repos: create [blocked] task in the repo's PLAN.md
- Run ledger --gc --report for worktree health
- Run ledger --hygiene --dry-run for branch cleanup recommendations

OUTPUT: Repo health dashboard — one line per repo with status + recommended action.

Never force-push. Never delete branches without confirmation. Never reset --hard.
Recommend actions; let the fleet watcher or a human execute.
```

### Parallel variant (fan-out per repo)

The CHECK loop above is written serially ("for each repo... 1, 2, 3, 4, 5") — on a fleet of N repos that's N sequential round-trips of read-only checks that don't depend on each other. Apply Principle 9 (DOCTRINE.md — read-only fan-out is safe because there are no merge conflicts, and vidux has run 9 concurrent research agents without incident): dispatch one agent per repo to run checks 1-5 and return its CLASSIFY verdict, then fan in through one synthesizer that assembles the dashboard and files the CRITICAL/WARNING actions. Same checks, same classification thresholds, same never-force-push guardrails — only the scheduling changes, from N sequential passes to one wall-clock pass. See Recipe 12 for the general pattern this is an instance of.

---

## Recipe 7: Skill Refiner

**What:** Periodic quality sweep of skill files. Checks description quality (drives activation rates), stale references, and cross-ref consistency.

**Trigger:** Scheduled, every 6 hours
**Role:** Quality auditor (writes to skill files via PR only)

### Prompt Template

```
Use vidux as skill refiner for <your-skills-dir>/.

Mission: Every skill's description drives its activation rate. Polish descriptions,
fix stale refs, ensure cross-refs are valid. Ship improvements as ready PRs after local gates pass.

READ:
1. List all skills: ls <your-skills-dir>/*/SKILL.md
2. For each: extract name, description, last-modified date
3. Check activation signals: grep across lane prompts for skill references

AUDIT (pick ONE skill per cycle — rotate through the list):
- Description quality: is it specific enough to trigger correctly? (20%→90% with good descriptions per Anthropic research)
- Stale references: do file paths and function names in the skill still exist?
- Cross-refs: do sibling skill references point to valid skills?
- Length: is the skill concise or bloated? (vendor guidance: "earn your complexity")

FIX (if issues found):
1. cd ~/Development/ai && git pull --ff-only
2. Identify the owning PLAN.md row before editing. If the skill repo has no
   active row, add one before changing files.
3. Edit exactly one skill file plus any focused regression test/doc reference.
4. Update the owning PLAN.md Progress/Tasks or Drift Log with what changed,
   proof to run, `handoff_status`, files claimed, and next-agent resume point.
5. Emit the publish ledger row before the branch leaves the machine, via your configured ledger emitter:
   `"$LEDGER_EMIT" --event publish --repo-path "$(pwd)" --lane skill-refiner --task-id "<task-id>" --plan-path "<PLAN.md>" --proof "<command/artifact>" --handoff-status done --resume "<resume point>" --file "<skill-file>" --claim "<PLAN.md-or-skill-file>" --skills vidux,ledger --summary "skill(<name>): <improvement>"`.
6. git checkout -b claude/skill-refine-<name>
7. git add <skill-file> <test-or-doc-file> <PLAN.md>
8. git commit -m "update: <skill> - <what changed>"
9. git push -u origin claude/skill-refine-<name>
10. Build a PR body carrying summary/plan/proof/ledger/handoff/files-claimed/self-scrutiny/resume
    fields, including the three `--review-pass` entries, then open the ready PR:
    `gh pr create --title "skill(<name>): <improvement>" --body-file /tmp/vidux-pr-body.md`

ONE skill per cycle. Rotate through the full list over 24-48 hours.
Never delete a skill without the human operator's explicit approval.
Never bulk-edit — one skill, one PR, one review cycle.
```

---

## Recipe 8: Self-Improvement Loop

**What:** Vidux improving vidux. Reads its own PLAN.md, identifies improvements to the vidux repo itself, ships them.

**Trigger:** Scheduled, every 24 hours (or API-triggered after a fleet run)
**Role:** Meta-writer (writes to vidux repo only)

### Prompt Template

```
Use vidux to improve vidux itself.

Mission: One improvement per cycle. Read the plan, pick the highest-priority
unfinished item, do the work, then publish only after the owning plan and ledger
row already describe the change.

READ:
1. PLAN.md in ~/Development/vidux — find [pending] tasks
2. git log --oneline -10 — see what other lanes shipped recently
3. README.md — check for stale claims or missing coverage

ASSESS:
- Is there a [pending] task with evidence? → execute it
- Is the README inconsistent with current SKILL.md? → fix it
- Are any guides stale (referencing deprecated automation primitives or superseded patterns)? → update them
- Are tests failing? → fix them first

ACT:
- Trivial local notes can stay unpushed; any commit, push, or PR is a publish
  cycle and must update PLAN.md plus emit the ledger emitter's `--event publish`
  with non-empty `--summary`, `--task-id`, `--plan-path`, proof, handoff
  status, changed file, claim, and a next-agent resume point before the branch
  leaves the machine
- Substantial changes → branch + ready PR with summary/plan/proof/ledger/handoff/files
  claimed/resume fields in the PR body
- Always commit as: vidux: self-improvement - <what changed>

VERIFY:
- Run tests if they exist: python -m pytest tests/
- Check that referenced files/paths are valid
- Ensure README claims match reality

CHECKPOINT:
- Update PLAN.md Progress section before publish
- Keep the publish ledger eid with the branch/PR handoff
- If all [pending] tasks are done → go IDLE (don't invent work)
- After 2 consecutive IDLE cycles → routine should reduce frequency or pause

Delegate to a secondary model via `/vidux` Part 2 Mode B for any change >10 lines.
```

---

## Composing Recipes into a Fleet

A typical fleet combines 3-5 recipes:

```
┌─────────────────────────────────────────────────────────┐
│                 Production Fleet                        │
│                                                         │
│  Scheduled (every 1-6h):                                │
│    PR Lifecycle ──→ stale detection + ready notification │
│    Trunk Health ──→ repo hygiene + worktree GC          │
│    Skill Refiner ──→ description quality + stale refs   │
│                                                         │
│  Event-driven:                                          │
│    PR Reviewer ──→ review bot + code-review agent       │
│    Deploy Watcher ──→ verify after merge (with EXIT)    │
│                                                         │
│  Meta:                                                  │
│    Self-Improvement ──→ vidux improving vidux (24h)     │
└─────────────────────────────────────────────────────────┘
```

### Cadence Planning

Every platform has caps — daily run limits, webhook-per-hour limits, token budgets, session lifetime. Plan cadences with headroom:

| Recipe | Trigger | Est. fires/day | Notes |
|---|---|---|---|
| PR Reviewer | Event-driven | ~5 | Per PR from automation |
| PR Lifecycle | Scheduled 1h | 24 | Drop to scheduled 2h if cap-constrained |
| Deploy Watcher | Event-driven | ~3 | Exits after verification (max 3 checks) |
| Trunk Health | Scheduled 4h | 6 | Light — mostly git status checks |
| Skill Refiner | Scheduled 6h | 4 | One skill per cycle |
| Self-Improvement | Scheduled 24h | 1 | Meta — vidux improving vidux |

**Cadence strategy:** Start with PR Reviewer + PR Lifecycle (highest ROI). Add recipes as you verify the platform's caps support them.

### Hybrid Strategy: Persistent + Session-scoped

Not everything needs a persistent cloud lane. Use session-scoped automation (e.g., CronCreate) for:
- Short experiments ("run this for the next 2 hours")
- Rapid iteration on a new recipe before promoting it to a persistent lane
- Anything that needs access to local-only resources (Xcode, simulators, local builds)

Use persistent cloud lanes (or a persistent local runner) for:
- Anything that must survive laptop close
- Event-driven triggers (session-scoped cron can't do webhooks)
- Fleet watchers and lifecycle managers (must be always-on)

---

## Recipe 9: Edit-Then-Verify

**When to use:** Any automation lane that edits state files (memory.md, PLAN.md, JSONL) where concurrent writers exist, or any lane writing a report/artifact file another agent or a human will trust.

**Pattern:** After every file edit, immediately re-read the file to verify the change applied. If the re-read shows unexpected content, log the mismatch to memory and retry with fresh content.

```
Write to memory → re-read memory → compare expected vs actual
  match → continue
  mismatch → log to memory, re-read full file, retry edit (max 3 attempts)
  3 failures → mark lane degraded, checkpoint, exit
```

**Mechanized check:** `scripts/vidux-write-verify.sh check <file> [--min-bytes N] [--contains STRING] [--json]` gives the re-read-and-compare step a deterministic pass/fail signal instead of "looked fine to me" — non-zero exit means the write didn't land as expected. The retry loop stays agent-side (the script can't regenerate content); it just tells you when to fire it.

```bash
bash scripts/vidux-write-verify.sh check evidence/report.md --min-bytes 200 --contains "## Summary"
```

**Exit condition:** 3 consecutive edit-verify failures on the same file = lane exits with DEGRADED status. Do not retry indefinitely.

**Why:** Edit whitespace mismatches and 0-byte/truncated writes are a recurring fleet friction type. The re-read catches stale or empty content before it corrupts state or gets reported as done.

---

## Recipe 10: Cron Retry with Backoff

**When to use:** Any cron lane that encounters transient failures (auth expiry, rate limits, external service timeouts, context overflow).

**Pattern:** When a cycle exits due to an external blocker or context overflow, back off and retry once. If the retry also fails, mark the task `[blocked]` and exit.

```
Cycle fails with external_blocker or context_overflow
  → record lane-local failure reason in memory.md
  → if blocking or handing off, update the owning PLAN.md plus ledger handoff
  → wait 5 minutes (ScheduleWakeup if same-session, next CronCreate fire if lane-based)
  → retry once with fresh context
  → second failure → mark task [blocked], add Decision Log entry, exit
```

**Exit condition:** Max 1 retry per failure. Two consecutive failures = blocked. Never retry in a tight loop.

**Why:** Transient failures (auth, rate limits) often resolve in minutes — one retry catches them. Persistent failures (wrong config, missing permissions) need a human; retrying wastes cycles.

---

## Recipe 11: Multi-PR Dependency Shipping

**When to use:** When a coordinator lane manages 3+ open PRs with merge-order dependencies (e.g., shared types must merge before consumers, migration must merge before the code that reads new schema).

**Pattern:** Build a dependency DAG from changed files, then ship in topological order.

```
1. List open PRs: gh pr list --state open --author @me
2. For each PR, get changed files: gh pr diff <N> --name-only
3. Build dependency edges:
   - PR A touches shared types → PR B imports those types → B depends on A
   - PR A adds a migration → PR B reads new columns → B depends on A
4. Topological sort: ship roots first (no dependencies)
5. For each root PR:
   - Verify CI green (or run local checks for repos without CI)
   - If all review comments addressed → post READY_FOR_MERGE comment
6. After root merges → rebase dependents, re-verify, repeat
```

**Exit condition:** All PRs either merged or marked `[blocked]` with reason. Never hold a PR queue open indefinitely — if a root PR is blocked for 2+ cycles, escalate.

**Why:** Manual dependency tracking across 5+ PRs causes ordering mistakes (merge consumer before provider → broken build). The DAG makes ordering mechanical.

---

## Recipe 12: Parallel Assessor Fan-Out for Health Checks

**When to use:** Any "confirm everything is still green" pass that reads N independent, read-only surfaces before deciding whether to act — CI status across repos, PR-queue dedup, test-depth/coverage drift, plan/state reconciliation across lanes. Recipe 6 (Trunk Health) is a worked instance of this.

**Pattern:** Applies DOCTRINE.md Principle 9 (Subagent coordinator pattern) to the specific shape of "poll several independent things, then decide." Serial polling of N surfaces costs N round-trips even though the surfaces don't depend on each other; a single fan-out dispatch costs one wall-clock pass.

```
1. Enumerate the independent read-only lanes to check (repos, PR queues, plan
   files, test-coverage reports — whatever the health pass covers).
2. Dispatch one read-only assessor per lane IN A SINGLE FAN-OUT (not a loop
   that spawns and waits one at a time). Each assessor returns a small
   structured verdict: { lane, status: HEALTHY|WARNING|CRITICAL, finding }.
3. Fan in through ONE synthesizer that merges the verdicts into a single
   dashboard/report and decides what, if anything, needs action.
4. Only the synthesizer acts (files a blocked task, posts a comment, etc.) --
   assessors are read-only and never write, so there is no merge-conflict
   risk from running them concurrently (Principle 9).
```

**Cap:** Principle 9's existing ceiling applies — vidux has run 9 concurrent read-only research agents without conflict; that's the proven envelope, not a hard platform limit. Coding/writing agents stay capped at 4 with a point guard; this recipe is read-only assessors only.

**Exit condition:** A lane whose assessor fails to return (timeout, error) is reported as `UNKNOWN`, not silently dropped — the synthesizer's dashboard must account for every dispatched lane, matching the "no silent caps" discipline elsewhere in vidux (don't let a quiet failure read as "covered and healthy").

**Why:** The insights-report friction this closes: serial "confirm all green" polling is slow by construction, and a cron/coordinator lane re-deriving each surface one at a time burns cycles that a single concurrent pass would not. Precedent already exists (Principle 9, Recipe 6 Trunk Health, Evidence fan-out in docs/reference/loop.md Step 2) — this recipe just names the pattern once so a future lane reaches for it instead of writing another serial loop.

---

## Recipe 13: Thin-Token Multi-Agent Product Slice

**When to use:** Shipping Vidux product/cockpit work (or any plan-first repo) with multiple agents. Goal is parallel progress **without** reloading full doctrine or inventing a second control plane.

**Load:** `guides/thin-token.md` + owning `PLAN.md` row only. Do not load full `SKILL.md` for routine slices.

```
1. Lead picks one agent-reachable PLAN row and splits into ≤3 path-disjoint slices
   (example: tests/size | Simple UI | one guide file).
2. Each worker gets: cwd, branch/worktree, allowed paths, proof command, foldback target.
3. Workers implement + run their proof floor; return {paths, commands, weakest_claim, blockers}.
4. Lead merges foldback, updates PLAN, runs the combined focused suite once.
5. Stop when the row's validation is met — do not open PE kernel sidecars.
```

**Cap:** 1 lead + 2–3 workers. Coding writers stay path-disjoint. Prefer Recipe 12 assessors for pure read-only health; this recipe is for **implementation** slices.

**Exit condition:** Row has a weakest truthful claim and a resume pointer; green focused tests or a named known-red exception (e.g. env `/auto` contracts).

**Why:** Token burden after kernel-cut is mostly context bloat (full skill + orchestration), not missing agents. Many agents help only when scope is bounded and doctrine stays thin.

---

## Anti-Patterns

**1. Unsafe auto-merge.** Never merge a draft, failing PR, or PR with unaddressed required review findings. Personal overlays may authorize auto-merge after checks are green and findings are acked/resolved.

**2. Stuck verification loop.** Deploy watchers that re-verify 300+ times. Every recipe with a verification step MUST have an EXIT CONDITION with a max retry count.

**3. Ledger noise.** Lanes that log every heartbeat. Log once when idle, not per-fire. (Lesson from 395K empty `vidux_loop_start` entries.)

**4. Fabricated evidence.** Lanes that invent memory files or audit results to justify actions. COPY SAFETY applies to all automation output.

**5. Direct-to-main pushes.** All automation code changes go through PRs. The only exception is explicitly authorized human/local policy. Never let automation fall back to pushing main.

**6. Prompt bloat.** Recipe prompts should be under 30 lines. The vidux skill handles the cycle mechanics — prompts specify role, mission, and boundaries. Don't restate doctrine.
