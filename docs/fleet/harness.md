# Harness Authoring

Docs-site summary of `guides/harness.md`, the repo's source guide for writing automation prompts.

## Core rule

A prompt is a stateless harness:

- The harness stores process: mission, skills, guardrails, role boundaries.
- `PLAN.md` stores state: tasks, decisions, evidence, progress.
- Current task numbers, blockers, and branch names do NOT belong in the harness.

## The 8-block structure

`guides/harness.md` defines an eight-block order. Ordering is part of the contract — rearranging or omitting blocks causes known failure modes.

1. `MISSION`
2. `SKILLS`
3. `GATE`
4. `AUTHORITY`
5. `CROSS-LANE`
6. `ROLE BOUNDARY`
7. `EXECUTION`
8. `CHECKPOINT`

## Roles

Three lane roles, each with a different gate shape:

- `Writer` — ships code, executes plan tasks, merges. Reads plan state and decides whether to ship.
- `Radar` — read-only; produces evidence for a writer to promote. Scans reality instead of popping plan tasks.
- `Coordinator` — watches fleet health and adjusts focus. Looks for collisions, idle loops, fleet-level problems.

## Prompt size guidance

Target 2000-3000 chars:

- Under 1500: a block is probably missing.
- 1500-3000: healthy range.
- Over 3000: audit for repeated doctrine.
- Over 4000: the prompt is restating material skills already provide.

## Common failure modes

- Gating on the wrong file and exiting before real work starts.
- Giving a scanner a writer-style gate.
- Restating doctrine the agent already gets from the `vidux` skill.
- Vague authority paths instead of explicit file locations.
- Omitting a role boundary or cross-lane read step.

## Where to go next

- [Fleet Operations](/fleet/operations) — gate patterns and coordination rules prompts rely on.
- [Prompt Template](/reference/prompt-template) — docs-site reference for the lane prompt structure.
- [Claude Code Lifecycle](/fleet/claude-lifecycle) or [Codex Automation Lifecycle](/fleet/codex-lifecycle) — how the harness is consumed per platform.
