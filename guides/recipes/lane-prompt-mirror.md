# Recipe: Lane Prompt Mirror

> The live lane prompt lives in per-machine state (`~/.vidux/lanes/<lane>/prompt.md`) and can disappear when a lane is rebuilt. Mirror durable directives into the consuming repo so they survive rebuilds and cross-machine installs.

## When to use

- You authored or updated a lane prompt at `~/.vidux/lanes/<lane>/prompt.md`
- The prompt encodes durable directives (HARD NEVER constraints, post-rip rules, repo-specific behavior gates) — not just a "what to do this tick" snippet
- The consuming repo is committed to git and pulled across multiple machines
- A lane-memory rebuild or fresh-machine install would otherwise drop the directive

## The recipe

**1. Land the directive in the LIVE prompt first.** The lane reads from `~/.vidux/lanes/<lane>/prompt.md`; that file must contain the latest version. Edit there before mirroring.

**2. Copy the live prompt into the consuming repo at a predictable path.** Convention: `docs/lane-prompts/<lane>.md`. Sits alongside `docs/` so it's discoverable without polluting `scripts/`.

   ```bash
   cp ~/.vidux/lanes/<lane>/prompt.md <repo>/docs/lane-prompts/<lane>.md
   ```

**3. Prepend a header comment that points editors back at the live copy.** Without this, the next agent edits the mirror, the cron keeps reading the stale live copy, and the two drift silently:

   ```markdown
   <!--
     Mirror of ~/.vidux/lanes/<lane>/prompt.md (the live lane prompt the
     runtime reads). Tracked in git so the directive survives lane-memory
     rebuilds and reads on every machine that pulls this repo. On each
     machine, `cp` this file back to
     ~/.vidux/lanes/<lane>/prompt.md if the local copy was ever lost.

     Edit the LIVE copy first, then re-mirror here in the same commit so
     the two stay in lockstep.
   -->
   ```

**4. Commit the mirror in the SAME commit as any live-prompt edit.** Lockstep is a discipline. If you commit only the mirror, the live lane is reading the old directive. If you commit only the live edit, the next machine gets the old directive.

**5. Document the recovery path in the repo README.** One line under local setup:

   ```
- On a fresh machine, `cp docs/lane-prompts/<lane>.md ~/.vidux/lanes/<lane>/prompt.md`
  before bootstrapping the corresponding runner so the lane reads the
     current directive, not the codex default.
   ```

## Failure modes

Without this recipe:

- A machine install rebuilds the lane prompt from a template that predates the latest `[DIRECTION]`. The runner uses stale instructions for weeks before anyone notices.
- An agent updates the LIVE prompt but not the mirror. The current Mac is correct; every other Mac running the same lane disagrees.
- An agent updates the mirror but not the LIVE prompt. The runner keeps reading the stale directive; commits to the repo claim a change that the runtime doesn't honor.
- A lane-memory wipe (manual cleanup, fresh `~/.vidux` directory, config-management glitch) drops the directive entirely. The next cycle reverts to default behavior, including the bloat the directive was supposed to prevent.

## Example

A recurring `content-prep` lane is the calibration case. Its mirror:

- Carries the post-2026-05-17 `## UX Target` section that names the single-column TODAY-first cockpit and the `/household/calendar` separate route
- Carries the `HARD NEVER (2026-05-17 rip)` bullet listing forbidden CSS class names
- Carries the `## Tick Contract` step 4 that references `npm run test:household:shape` (the lint guard wired into `test:all`)
- Was committed in the same PR as the corresponding live-prompt edit and README setup pointer

Pair with [the-rip-pattern.md](the-rip-pattern.md) when the directive being mirrored is a post-rip constraint.

## Calibration

- Only mirror prompts that encode **durable** directives. Tick-by-tick task instructions live and die with the lane; they don't belong in the repo.
- Update the mirror in the SAME commit as the live edit. Lockstep or drift.
- If a single machine maintains the lane and the runner never runs anywhere else, skip the mirror — overhead without payoff.
