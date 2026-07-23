# Vidux Automation Guide

For running vidux lanes on a schedule or in long-running sessions. Load only when you need automation — Vidux core (the five principles, the cycle, PLAN.md discipline in `SKILL.md`) stands alone. Automation is additive: it never overrides SKILL.md, it only describes *how* to run workers on a schedule so work progresses while you're away.

2026-07-07 boundary: this guide is operator reference, not a second control plane. Vidux owns plan/proof/decision/resume truth. The coding host or supervisor owns runner/model selection, subagent dispatch, and worker foldback.

For Codex-created automations, the default run mode is **Chat**. Treat `Worktree` and `Local` as explicit opt-ins — only when the user asks for repo-bound execution or the task is impossible from chat.

Control-plane overlays may choose an execution mode but do not own queue state. A control plane may store provider refs, cadence, last fire, next fire, and retirement rules; each fired run must rehydrate from `PLAN.md`, `INBOX.md`, evidence, and publish ledger rows before acting.

---

## When to automate (and when not to)

Automate when **all** of these are true:

- Work spans multiple sessions and would lose context across handoff
- The cycle is repeatable (each fire does the same kind of work on whatever's pending)
- State orientation can live on disk: owning PLAN.md, publish ledger rows, evidence, and lane-local memory notes
- You accept losing conversation scrollback in exchange for 24/7 progress

Do NOT automate when:

- The work needs live human judgment every step
- The cycle can't be described in a self-contained prompt
- The state would have to live in session memory
- It's a one-off fix — just do it directly

---

## The 24/7 Fleet Operating Model

One invariant: **lanes persist on disk, sessions cycle through them.**

```
Lanes (persistent)                    Sessions (disposable)
<lane-dir>/<lane>/         ~/.claude/projects/*/*.jsonl
├── prompt.md   (mission/rules)       - cycle when bloated
└── memory.md   (lane-local cycle log) - shipped-work proof never lives here alone
```

A lane = `prompt.md` + `memory.md` on disk. These files persist regardless of which session fires them. When a session dies, the files stay; the next session re-schedules the cron, reads memory.md for lane-local orientation, and resumes from the owning PLAN.md plus publish ledger rows for shipped-work proof.

### Hot vs cold storage

| Layer | Lives here | GC |
|---|---|---|
| **Cold** (durable) | PLAN.md, evidence/, investigations/, publish ledger rows, lane-local memory.md notes | Agent-decided archive when the plan feels heavy |
| **Hot** (disposable) | `~/.claude/projects/*/*.jsonl` | Automatic via the session-gc lane's operator-provided JSONL cleanup helper |

### session-gc is mandatory for 24/7

A lane at `<lane-dir>/session-gc/prompt.md` fires hourly, runs the operator's JSONL cleanup helper against stale Claude session logs, and emits `[CYCLE SIGNAL]` over 40 MB so you know when to `/resume`. This repo documents the lane pattern but does not ship a `scripts/session-prune.py` helper. Without session-gc, JSONLs grow unbounded and `/resume` stops working.

### Session bloat controls

- Cycle session at 40 MB (fresh session starts under 1 MB)
- `"skillListingBudgetFraction": 0.005` in settings.json (halves skill-listing payload)
- Disable unused plugins (Vercel plugin on a non-Vercel project = ~30% of JSONL)
- `CronCreate` over `ScheduleWakeup` for ≥10 fires (CronCreate = fresh session per fire)

---

## Lane management — minimum needed, max 6 per session

Every lane must earn its keep. More than 6 lanes per session causes worktree contention and JSONL bloat (measured).

### Coordinator pattern (default for 24/7)

ONE coordinator lane per active repo that owns ALL concerns (ship code, fix CI, archive PLAN.md, watch INBOX). Beats the specialist model (separate shipper/product/a11y/seo lanes):

- No PLAN.md stampede (one writer per plan)
- End-to-end ownership (same lane that shipped fixes the test)
- 60% less JSONL growth (1 coordinator × 3 fires vs 5 specialists × 3 fires)
- Simpler mental model when something breaks

### Polish-brake

If your last 3 checkpoints all ship from the same surface, force a surface switch. Polish is fractal — every green PR has another P3 comment. The brake prevents infinite iteration on a done surface.

---

## Subagent dispatch (the primary context cutter)

Vidux runs single-tool: Claude parent with Claude subagents, or Codex parent with Codex subagents. The savings come from the subagent's fresh context budget — not from jumping runtimes. Two dispatch shapes split work between the parent (metered, decides/reviews) and a child subagent spawned via `Agent()` in the same runtime:

### Research dispatch

Parent writes a prompt, child subagent reads 30–150 KB in its own context, returns a 3-section summary (~300 tokens). Parent reads only the summary. Measured: **10–110× token savings** vs direct reads in the parent.

```
Parent: "30 files, needs auditing. Hand it off."
Subagent: reads, reasons, compresses to Summary + Evidence + Recommendation.
Parent: reads ~300 tokens, applies taste, ships.
```

The compression contract (paste verbatim in the subagent prompt):

```
Output ONLY these sections, nothing else:
1. Summary: 3 sentences MAX.
2. Evidence: 3 file:line references MAX, one per line.
3. Recommendation: 1 sentence MAX.
Do not explain. Do not echo the task. Do not write code.
```

### Implementation dispatch

Parent writes a 5-block spec, child subagent edits files in the working tree. Parent reviews `git diff` (~500 tokens) instead of writing 50 lines itself. Measured: **~5× further savings** on code-writing cycles.

```
Parent: "50-line fix. Here's the 5-block spec."
Subagent: writes code.
Parent: git diff → accept | re-prompt | git checkout . + retry.
```

The five-block prompt shape (all mandatory):

```
1. Task: one-sentence description.
2. Files: exact paths the subagent may edit.
3. Spec: what the code must do, 3–10 bullets.
4. Acceptance criteria: how the parent will judge the diff.
5. Out of scope: what the subagent must NOT change.
```

The "Out of scope" block is load-bearing. Without it, the subagent refactors adjacent code it decides "looks wrong" and the parent either accepts scope creep or rejects the whole diff.

### Decision tree

- Substantial code writing (>10 lines, clear spec) → implementation dispatch
- Reading code, grinding a hard problem, research → research dispatch
- Pure planning, taste call, <10 lines of obvious writing → parent does it directly

---

## Lane Bootstrap Recipe

When the user asks to create an automation ("I want a lane that…", "automate this", "run this every hour"), follow this recipe.

### 1. Decide the runtime

Default: **Claude-local (CronCreate)**. Simpler to debug, fast feedback, reads memory.md on every fire.

For Codex-created automations, default to **Chat** execution. Only choose `Worktree` or `Local` if the user explicitly asks or the automation truly needs direct project-folder runtime; for those repo-bound lanes see `guides/recipes/codex-runtime.md`. The rest of this guide assumes Claude lanes via `CronCreate`.

Use this provider-neutral mode table when an overlay asks Vidux how to run:

| Situation | Default |
|---|---|
| Chat-scoped "keep this thread going" | Chat heartbeat in the current thread |
| Must survive laptop close or needs external event/API trigger | Routine or CronCreate |
| Local-only simulator/browser/Mac state | Local cron or launchd |
| One-shot research or bounded disagreement audit | Subagent |
| Small direct task | Inline Vidux loop |

Whichever runtime fires, the state contract is the same: routines drive runs; `PLAN.md` and ledger remain the authority.

### 2. Pick the role

- **Coordinator** — owns a whole repo (ship + fix + GC). 1 per active repo. Max 1.
- **Burst** — single short-lived task with auto-expire. Delete when done.
- **Radar** — read-only scan, no writes, no worktree. For research-only missions.

### 3. Create the files

```
<lane-dir>/<lane-id>/
├── prompt.md        # Mission, authority, role, hard rules, checkpoint format
└── memory.md        # Empty on creation; lane appends 2-3 sentences per cycle
```

### 4. Write the prompt

Every prompt.md follows the eight-block structure in
[`harness.md`](harness.md#8-block-prompt-structure) — MISSION, SKILLS, GATE,
AUTHORITY, CROSS-LANE, ROLE BOUNDARY, EXECUTION, CHECKPOINT, in that order.
That guide owns the block definitions and the reasons the order matters.

Two notes specific to lane prompts:

- The hard rules live in EXECUTION: never use `--no-verify`, never force push,
  never touch files outside AUTHORITY.
- ROLE BOUNDARY names the lane's role (Writer | Radar | Burst) and what belongs
  to siblings.

The MISSION block matters most: it's what differentiates this lane from all others. Be specific about the *output* (a merged PR, a checkpointed decision, an appended evidence line) not just the *input* (check this, scan that).

### 5. Register + schedule

```
CronCreate({
  name: "<lane-id>",
  cron: "0 */1 * * *",    # hourly, or your cadence
  prompt: "Read <lane-dir>/<lane-id>/prompt.md and execute the cycle it describes."
})
```

Test-fire once. If the first-fire output looks right, leave it.

### 6. Verify + checkpoint

- Confirm the lane's `memory.md` gets its first lane-local entry on the next fire
- Confirm the `[CYCLE] ...` log format matches the CHECKPOINT spec in prompt.md
- If the fire shipped work, confirm the owning PLAN.md plus publish ledger row carries proof and resume metadata
- Add the lane to INBOX or coordinator memo so future sessions know it exists

---

## When to use this guide

Load this guide when any of these are true:

- Creating, managing, or auditing a lane
- Debugging fleet behavior (a lane isn't firing, checkpoints look wrong)
- Setting up session-gc
- Designing the research / implementation dispatch split for a long-running session

For everything else — planning, investigating, shipping a one-off fix — SKILL.md Part 1 alone is the full tool. Don't let automation mechanics leak into ordinary plan work.

---

## See Also

- `../SKILL.md` — Vidux core discipline (five principles, the cycle, PLAN.md template, investigations). Required reading before this guide.
- `recipes/codex-runtime.md` — Codex-native lane setup: automations table, shim pattern, SQLite registration. Load only if you're running Codex-local lanes instead of Claude-local.
- `fleet-ops.md` — Day-to-day fleet operations beyond bootstrap (lane audit, PR lifecycle nursing, cross-lane coordination).
- `harness.md` — Session-level tuning (settings.json knobs, plugin discipline, JSONL bloat forensics).
