# Quick Start

Your first Vidux cycle, install to checkpoint.

## 1. Install Vidux

```bash
git clone https://github.com/firstbitelabsllc/vidux.git ~/Development/vidux
mkdir -p "$HOME/.local/bin"
ln -sfn "$HOME/Development/vidux/bin/vidux" "$HOME/.local/bin/vidux"
export PATH="$HOME/.local/bin:$PATH"   # add to your shell profile to keep it
ln -sfn "$HOME/Development/vidux" "$HOME/.claude/skills/vidux"   # optional: the /vidux skill
vidux --version
```

The CLI symlink powers `vidux init --here` and the local browser; the Claude
skill symlink is optional. See [Installation](/guide/installation) for an
optional locally-built tarball (`npm pack`) that does not require keeping the
checkout on `PATH`.

## 2. Start a Session

In the project you want Vidux to track, initialize the cockpit once:

```bash
vidux init --here
vidux browse --root .   # scoped to this repo; browse scans ~/Development by default
```

Then open Claude Code in that project and run:

```
/vidux "your project description"
```

**On the first cycle**, Vidux gathers evidence and writes a `PLAN.md`. No code until the plan is ready — "plan first, code second" is the core discipline.

## 3. Understand the Startup Contract

`/vidux` resolves state first, then decides whether to plan or execute:

1. **Load the skill** and read `vidux.config.json` if present.
2. **Resolve the authority plan store** (`PLAN.md` in the repo, or an external/local plan store from config).
3. **Read current state**: authority `PLAN.md`, recent progress, Decision Log, git diff.
4. **Choose the next path**:
   - no authority plan yet -> gather evidence and draft one
   - authority plan exists -> resume `[in_progress]` work first, otherwise pick the next ready `[pending]` task

The public `/vidux` spec requires no intermediate "amplified prompt" review step or "fire" confirmation. The command resolves the plan, reads repo state, runs the stateless cycle.

## 4. The First Cycle: Evidence Gathering

The first cycle always produces a `PLAN.md`, not code. Rule:

> **A plan entry without evidence is a guess. Guesses cause rework.**

The agent:
1. Greps the codebase for relevant patterns
2. Reads related files
3. Checks git log for recent changes
4. Synthesizes findings into a structured PLAN.md

After the first cycle, you'll have a `PLAN.md` that looks like:

```markdown
# My Project

## Purpose
Why this exists. One paragraph.

## Evidence
- [Source: codebase grep] src/auth/login.ts:42 — missing rate limit
- [Source: git log] commit abc123 — "fix: auth bypass" (3 days ago)

## Tasks
- [pending] Task 1: Add rate limiting to login endpoint [Evidence: ...]
- [pending] Task 2: Write tests for auth bypass fix [Evidence: ...]

## Decision Log
## Progress
```

## 5. Subsequent Cycles: Stateless Execution

On the second `/vidux` invocation (READ → ASSESS → ACT → VERIFY → CHECKPOINT):

1. **READ**: loads PLAN.md, checks for `[in_progress]` tasks (crash recovery)
2. **ASSESS**: first pending task has evidence → ready to code
3. **ACT**: sets task to `[in_progress]`, executes it
4. **VERIFY**: runs build and tests, shows proof
5. **CHECKPOINT**: updates the plan/progress record and emits the publish ledger row before any branch/PR/release publish

When code changed, the local commit stays concise:

```
vidux: add rate limiting to login endpoint

- Added express-rate-limit middleware to /auth/login
- Configured: 5 requests per 15 minutes per IP
- Tests: auth.test.ts passes (12/12)
```

The durable handoff is the owning `PLAN.md` update plus the matching publish
ledger row: task id, proof, handoff status, files claimed, next-agent resume.

## 6. Crash Recovery

If a session dies mid-task, the next cycle auto-recovers:

```
CRASH RECOVERY: uncommitted work detected
git diff shows changes to src/auth/login.ts

Preserving WIP: map changes to the owning PLAN.md row
Recording: plan + ledger handoff before commit/push/cleanup
```

The agent preserves in-progress work first, records a plan/ledger handoff, then commits only after the plan/ledger packet exists and only if code changed.

## 7. When All Tasks Complete

When the queue empties, the agent scans for new work:

1. Checks `INBOX.md` for unprocessed findings
2. Scans owned paths for issues
3. Checks git log for changes needing follow-up
4. Rechecks blocked tasks for resolved blockers

If nothing is found, it checkpoints and exits with proof of what was scanned.

## Common Patterns

**Starting a new feature:**
```
/vidux "add dark mode support"
```

**Fixing a bug:**
```
/vidux "users report checkout double-charges on fast retry"
```

**Continuing existing work:**
```
/vidux
```
(No description needed — reads PLAN.md and resumes)

**Plan-only (no code this cycle):**
```
/vidux "investigate performance issues in the dashboard. Plan only, no code this cycle."
```

No `/vidux --plan` flag exists in the shipped command spec. For a planning-only pass, say so in the request.

## Next Steps

- [Five Principles](/concepts/principles) — the doctrine behind the discipline
- [The Cycle](/concepts/cycle) — detailed step-by-step mechanics
- [PLAN.md Structure](/concepts/plan-structure) — full template reference
