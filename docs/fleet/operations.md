# Fleet Operations

Summarizes `guides/automation.md` and `guides/fleet-ops.md` for a multi-lane vidux setup, after the core planning discipline is in place.

Boundary: these operations are optional scheduling mechanics. The coding host or supervisor owns dispatch and foldback; Vidux owns the plan/proof packet every run reads and updates.

## Operating model

Invariant: lanes persist on disk, sessions are disposable. Durable files live in the lane directory and the project plan store; session logs are hot state expected to cycle or be garbage-collected. `session-gc` is mandatory for 24/7 fleets so session logs don't grow unbounded.

## Lane management

Default: one coordinator lane per active repo, not a swarm of specialists.

- One coordinator reduces plan stampedes; the lane that ships a change fixes its fallout.
- Target 2-4 total lanes for 1-3 active repos; hard cap 6 per session.
- Polish-brake: force a surface switch if the last three checkpoints all ship from the same area.

## Dispatch model

Optional runtime dispatch has two common shapes:

- **Research dispatch** — reads a large surface, compresses to a short summary with evidence lines. (read-heavy work)
- **Implementation dispatch** — edits files from a five-block spec; parent reviews the diff. (bounded code-writing)

Small obvious changes stay in the parent lane.

## Lifecycle observability

Every dispatch cycle leaves the same local proof shape, whether the parent runtime is Claude Code, Codex, or an editor-bound Cursor lane:

- `python3 scripts/vidux-config.py check --json` proves local config or example fallback before plan-store assumptions.
- `scripts/vidux-doctor.sh --json` is the beforeTask runtime health probe; `vidux doctor` remains the terminal install/readiness doctor.
- `VIDUX_RUNTIME=claude`, `VIDUX_RUNTIME=codex`, or `VIDUX_RUNTIME=cursor` keeps spawned-worker attribution honest.
- The final handoff is the owning `PLAN.md` plus matching publish ledger row.

## Coordination checks

Mandatory before a lane acts:

- Read recent sibling `memory.md` entries.
- Check hot files before touching a surface another lane may own.
- Verify trunk health early — a dirty or diverged main wastes a long cycle.
- Reuse or merge existing worktrees instead of spawning new ones.

## Writer and scanner gates

- **Quick check** gates — writers and plan-driven workers. A writer on the wrong plan wastes a cycle.
- **SCAN** gates — radars/scanners inspecting the codebase itself. A scanner on the wrong gate stays dead forever — it exits on plan state instead of scanning the owned surface.

## Worktree and branch discipline

PR sweep and worktree handoff are operational requirements:

- The owning `PLAN.md` plus matching publish ledger row is the durable shipped-work recovery packet; open automation PRs are transport/review handles, swept before new branch work starts.
- Resume or garbage-collect active worktrees instead of duplicating.
- `vidux-worktree-gc.py` protects both the primary checkout and the checkout it is invoked from; only `merged_clean` rows are auto-removable.
- Keep PLAN changes append-mostly so stale merges do not clobber task queues.
- Do not exit with unexplained local worktree commits or branch-only drift.

## Inbox and merge conflict protocol

`guides/fleet-ops.md` also documents:

- An `INBOX.md` handoff pattern for radar-to-writer promotions.
- Merge conflict rules for plan files and long-lived worktrees.
- A fleet-health coordinator pattern for dead lanes, collisions, and repeated blockers.

## Recommended companions

- [Recipe Catalog](/fleet/recipes) — reusable patterns (PR review, deploy watching, retry-with-backoff).
- [Harness Authoring](/fleet/harness) — before changing a lane prompt.
- [Configuration](/reference/config) — repo-level defaults these scripts and guides rely on.
