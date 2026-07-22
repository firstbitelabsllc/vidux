# Fleet Overview

Vidux automation is opt-in: the core discipline works without long-running lanes. This section documents scheduled runs, fleet coordination, and platform-specific lifecycle for Claude Code and Codex. Runtime dispatch is owned by the coding host or supervisor; Vidux records the plan/proof packet those runs must rehydrate. For Codex these docs cover the native macOS path; the automation guide defaults Codex-created automations to `Chat`, so use the TOML + DB flow only for a repo-bound `Local` or `Worktree` lane.

## What lives in this section

Read in this order:

1. [Platform Comparison](/fleet/platforms) — Claude Code vs Codex; start here when deciding.
2. [Harness Authoring](/fleet/harness) — prompt authoring rules (`guides/harness.md`); read before writing/updating a prompt.
3. [Fleet Operations](/fleet/operations) — cross-lane rules, worktree handoff, trunk-health (`guides/automation.md`, `guides/fleet-ops.md`).
4. [Recipe Catalog](/fleet/recipes) — reusable patterns (`guides/recipes.md`, `guides/recipes/`).
5. [Claude Code Lifecycle](/fleet/claude-lifecycle) — how a Claude lane fires, reads authority files, checkpoints.
6. [Codex Automation Lifecycle](/fleet/codex-lifecycle) — the native Codex Mac app model + persistence rules.
7. [Codex Setup Guide](/fleet/codex-setup) — the TOML + DB + app-restart sequence for native lanes.

## When to automate

Automate only when ALL hold: work spans multiple sessions and would lose context across handoff; the cycle is repeatable across fires; State orientation can live on disk (owning `PLAN.md`, publish ledger rows, evidence, lane-local `memory.md` notes); you accept disposable sessions for steady progress.

Stay manual when ANY hold: work needs live human judgment every step; the cycle can't be described in a self-contained prompt; state would have to live in session memory; it's a one-off fix done directly.

## Shared lifecycle spine

Every runtime follows the same proof spine; only scheduling differs:

1. Resolve local config: `python3 scripts/vidux-config.py check --json`.
2. Pre-task runtime health: `scripts/vidux-doctor.sh --json` (not the slower terminal `vidux doctor`).
3. Attribute spawned workers with `VIDUX_RUNTIME=claude`, `VIDUX_RUNTIME=codex`, or `VIDUX_RUNTIME=cursor` when the ambient env would mislabel the event.
4. Finish by updating the owning `PLAN.md` plus the matching publish ledger row with proof, handoff status, files claimed, and next-agent resume.
