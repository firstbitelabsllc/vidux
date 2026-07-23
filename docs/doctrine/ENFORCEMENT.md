# Vidux Enforcement

> Instructions in CLAUDE.md are suggestions. Hooks are enforcement.

SKILL.md tells the agent what to do. Hooks make it actually do it. Instructions degrade first under token pressure; hooks fire at lifecycle points and inject guidance (or block) regardless of what the agent is "thinking about."

## Three enforcement levels

| Type | What it does | When to use |
|------|-------------|-------------|
| **prompt** | Injects text into context before the agent acts | Guide behavior without blocking. Agent sees the reminder and self-corrects. |
| **command** | Runs a script; non-zero exit blocks the tool call. | Hard gates: lint, format, destructive-command prevention. |
| **agent** | Spawns a sub-agent to evaluate. | Judgment calls that need reasoning, not pattern matching. |

**Why prompt for all four plan-compliance hooks:** plan compliance is a judgment call, not a binary check — the agent may edit a file that isn't literally in PLAN.md but is implied by the task. A `command` hook can't reliably do that semantic comparison and a hard-block wastes a cycle; the agent has the context to make the call, so prompt hooks delegate the judgment to it and guide it back to the plan when it drifts.

---

## Hook 1: PreToolUse — Write/Edit Gate

**Doctrine enforced:** #2 (Unidirectional flow), #1 (Plan authority)
**Trigger:** Before any `Write` or `Edit`.
**What it does:** If the target file path isn't in (or implied by) a PLAN.md task, injects a reminder to update the plan first.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "prompt",
            "prompt": "VIDUX PLAN CHECK: Before writing or editing a file, verify this file is mentioned in (or clearly implied by) a task in PLAN.md. If this file is NOT covered by any task in the plan:\n\n1. STOP — do not proceed with the edit yet.\n2. Update PLAN.md first: add a new task entry (with evidence) that covers this file.\n3. Then return to the edit.\n\nIf the file IS covered by an existing task, proceed normally. PLAN.md is the queue/planning authority. All code changes flow from plan entries."
          }
        ]
      }
    ]
  }
}
```

**Compliance examples:**
- Edit `utils/helpers.ts`; Task 3 says "refactor shared helpers for the new API" → covered, edit proceeds.
- Clean up an unrelated test file no task mentions → agent updates PLAN.md with a new task, THEN edits.

---

## Hook 2: PostToolUse — Drift Detection

**Doctrine enforced:** #2 (Unidirectional flow), #6 (Process fixes > code fixes)
**Trigger:** After any `Write` or `Edit` completes.
**What it does:** Reminds the agent to reconcile the change against the task description. On divergence, update the owning PLAN.md (Progress / Tasks) so the plan reflects the true state of the work.

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "prompt",
            "prompt": "VIDUX DRIFT CHECK: You just modified a file. Reconcile planned vs actual:\n\n1. What did the task in PLAN.md say you would do?\n2. What did you actually change?\n3. If they diverge: update the owning PLAN.md (Progress / Tasks) to record planned, actual, why, the plan update, and next.\n\nDo NOT silently drift from the plan. The plan must always reflect the true state of the work."
          }
        ]
      }
    ]
  }
}
```

Catches drift per-edit, not per-cycle. Evidence: agent code degradation is monotonic (SlopCodeBench, arxiv 2603.24755) — agents don't break, they drift; by cycle 10 the code bears little resemblance to the plan.

---

## Hook 3: Stop — Checkpoint Enforcement

**Doctrine enforced:** #5 (Design for completion), #2 (Unidirectional flow)
**Trigger:** When the session ends (user stops, timeout, or agent completes).
**What it does:** Reminds the agent to write a checkpoint before dying. Every shipped session leaves a structured plan/ledger packet so the next session can resume from the owning plan plus the matching ledger row.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "prompt",
            "prompt": "VIDUX CHECKPOINT: Before this session ends, ensure you have:\n\n1. Updated the owning PLAN.md Progress/Tasks/Drift Log with what changed, blockers, proof, files claimed, and the next-agent resume point.\n2. Emitted a publish ledger row for shipped work with summary, task id, plan path, proof, handoff_status, files claimed, claims, and resume.\n3. Committed only after the plan/ledger packet exists, and only if code changed.\n4. If no work shipped, leave a plan/ledger handoff or blocker note instead of inventing a commit.\n\nThe next session is a different agent. It knows nothing except what's in the files and matching ledger row. Leave it a clear trail."
          }
        ]
      }
    ]
  }
}
```

### Optional command pairing

Pair the prompt with an `async` command that warns (does not block) when `## Progress` has no entry for today. The prompt guides; the command alarms.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "prompt",
            "prompt": "VIDUX CHECKPOINT: Before this session ends, update the owning PLAN.md Progress/Tasks/Drift Log, emit a publish ledger row for shipped work with proof, handoff_status, files claimed, claims, and resume, then commit only after that packet exists and only if code changed. The next session knows nothing except what's in the files and matching ledger row."
          },
          {
            "type": "command",
            "command": "bash -c 'PLAN=$(find . -maxdepth 3 -name PLAN.md -path \"*/vidux/*\" 2>/dev/null | head -1); if [ -n \"$PLAN\" ] && ! grep -q \"$(date +%Y-%m-%d)\" \"$PLAN\" 2>/dev/null; then echo \"WARNING: PLAN.md has no progress entry for today. Record the plan plus ledger handoff before stopping.\"; fi'",
            "async": true
          }
        ]
      }
    ]
  }
}
```

---

## Hook 4: SessionStart — Resume Protocol

**Doctrine enforced:** #5 (Design for completion), #1 (Plan authority)
**Trigger:** When a new session starts.
**What it does:** Injects a directive to read PLAN.md and the latest matching ledger row first. Every session starts by reading durable files and ledger proof, not by remembering anything. This is the highest-leverage hook: if the agent reads the plan and ledger, the other hooks are safety nets.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "prompt",
            "prompt": "VIDUX RESUME: This is a Vidux-managed project. Start by reading PLAN.md and the latest matching ledger row:\n\n1. Read PLAN.md — find the Purpose, then go to the Progress section.\n2. Find the last progress entry and matching publish/handoff ledger row — that's where shipped work resumes.\n3. Check for uncommitted work: run git status and git diff --stat.\n4. If uncommitted work exists from a crashed session, preserve it first: inspect the diff, map it to the owning plan row, and record recovery path in owning plan plus ledger handoff before any commit, push, cleanup, or overwrite.\n5. Find the highest-priority unblocked task — that's your job this session.\n6. Follow the Vidux loop: Gather -> Plan -> Execute -> Verify -> Checkpoint.\n\nDo NOT start coding until you know what the plan says. PLAN.md is the queue/planning authority; matching publish ledger rows prove shipped work."
          }
        ]
      }
    ]
  }
}
```

### Optional command pairing

Pair with a command that prints a quick PLAN status summary (last Progress line + first few open tasks). The prompt tells the agent WHAT to read and WHERE; the command gives a glance.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "prompt",
            "prompt": "VIDUX RESUME: This is a Vidux-managed project. Read PLAN.md and the latest matching ledger row first. Find the last Progress entry, check git status for uncommitted work, preserve crashed-session WIP before cleanup or commit, then find the highest-priority unblocked task. Follow the loop: Gather -> Plan -> Execute -> Verify -> Checkpoint."
          },
          {
            "type": "command",
            "command": "bash -c 'PLAN=$(find . -maxdepth 3 -name PLAN.md -path \"*/vidux/*\" 2>/dev/null | head -1); if [ -n \"$PLAN\" ]; then echo \"=== VIDUX PLAN STATUS ===\"; grep -A1 \"^## Progress\" \"$PLAN\" | tail -1; echo \"---\"; grep \"^- \\[ \\]\" \"$PLAN\" | head -3; echo \"($(grep -c \"^- \\[ \\]\" \"$PLAN\") tasks remaining)\"; fi'"
          }
        ]
      }
    ]
  }
}
```

---

## Full Configuration

All four hooks combined in a single `settings.local.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "prompt",
            "prompt": "VIDUX PLAN CHECK: Before writing or editing a file, verify this file is mentioned in (or clearly implied by) a task in PLAN.md. If this file is NOT covered by any task in the plan:\n\n1. STOP — do not proceed with the edit yet.\n2. Update PLAN.md first: add a new task entry (with evidence) that covers this file.\n3. Then return to the edit.\n\nIf the file IS covered by an existing task, proceed normally. PLAN.md is the queue/planning authority. All code changes flow from plan entries."
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "prompt",
            "prompt": "VIDUX DRIFT CHECK: You just modified a file. Reconcile planned vs actual:\n\n1. What did the task in PLAN.md say you would do?\n2. What did you actually change?\n3. If they diverge: update the owning PLAN.md (Progress / Tasks) to record planned, actual, why, the plan update, and next.\n\nDo NOT silently drift from the plan. The plan must always reflect the true state of the work."
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "prompt",
            "prompt": "VIDUX CHECKPOINT: Before this session ends, ensure you have:\n\n1. Updated the owning PLAN.md Progress/Tasks/Drift Log with what changed, blockers, proof, files claimed, and the next-agent resume point.\n2. Emitted a publish ledger row for shipped work with summary, task id, plan path, proof, handoff_status, files claimed, claims, and resume.\n3. Committed only after the plan/ledger packet exists, and only if code changed.\n4. If no work shipped, leave a plan/ledger handoff or blocker note instead of inventing a commit.\n\nThe next session is a different agent. It knows nothing except what's in the files and matching ledger row. Leave it a clear trail."
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "prompt",
            "prompt": "VIDUX RESUME: This is a Vidux-managed project. Start by reading PLAN.md and the latest matching ledger row:\n\n1. Read PLAN.md — find the Purpose, then go to the Progress section.\n2. Find the last progress entry and matching publish/handoff ledger row — that's where shipped work resumes.\n3. Check for uncommitted work: run git status and git diff --stat.\n4. If uncommitted work exists from a crashed session, preserve it first: inspect the diff, map it to the owning plan row, and record recovery path in owning plan plus ledger handoff before any commit, push, cleanup, or overwrite.\n5. Find the highest-priority unblocked task — that's your job this session.\n6. Follow the Vidux loop: Gather -> Plan -> Execute -> Verify -> Checkpoint.\n\nDo NOT start coding until you know what the plan says. PLAN.md is the queue/planning authority; matching publish ledger rows prove shipped work."
          }
        ]
      }
    ]
  }
}
```

---

## Design Principles

### Prompt is the right default for plan compliance

Plan compliance needs the _intent_ of a task, not file-path matching. Reserve `command` hooks for objective checks: lint passes, file exists, build succeeds. "Does this edit align with the plan?" → prompt.

### Hooks compose, not compete

Each hook enforces one doctrine principle at one lifecycle point; they don't overlap.

| Hook | Lifecycle | Doctrine | Question it asks |
|------|-----------|----------|-----------------|
| PreToolUse | Before edit | Unidirectional flow | "Is this edit in the plan?" |
| PostToolUse | After edit | Unidirectional flow | "Did this edit match the plan?" |
| Stop | Session end | Design for completion | "Did you checkpoint?" |
| SessionStart | Session begin | Design for completion | "Did you read the plan?" |

Together they form a closed loop: start from the plan, edit per the plan, verify against the plan, checkpoint for the next session, resume from the plan.

### The enforcement gradient

Graduated pressure, a cascade where each hook catches what the previous missed:

1. **SessionStart** — "Read the plan." (Orientation. Gentle.)
2. **PreToolUse** — "Is this in the plan?" (Friction before action. Medium.)
3. **PostToolUse** — "Did you drift?" (Reflection after action. Medium.)
4. **Stop** — "Did you checkpoint?" (Obligation before death. Firm.)

### Enforcement limits

Hooks fire at the AI-tool level (Claude Code, Cursor, Codex). They cannot prevent:
- **Direct git operations** — `git commit`, `git push`, manual edits bypass all hooks.
- **Non-tool agents** — custom scripts, CI, other tools that don't fire hook events.
- **In-memory drift** — agents can carry context forward within a session if they ignore hook guidance.

For these, rely on:
- **Git commit hooks** (`pre-commit-plan-check.sh`) — verify committed files match plan entries.
- **Ledger event logging** — records all work for post-hoc audit even if hooks were bypassed.
- **Code review** — humans catch drift automated enforcement misses.
- **Decision Log** — PLAN.md's Decision Log prevents cron agents from undoing deliberate choices.
