# Recipe: The Rip Pattern

> When an agent inherits a kitchen-sink surface with almost no real data, the right move can be to remove visible affordances and re-promote them only when the product actually needs them.

## When to use

- You inherit a surface where prior cycles shipped many visible controls: filters, prep strips, matrices, suggestion panels, calendars, multi-section queues, button grids, or 10+ field forms
- The user opens that surface and immediately says it's "too many buttons / too many options / awful MVP"
- The underlying data store is mostly empty (zero or near-zero records)
- The prior agent shipped those features over multiple consecutive cycles, each adding chrome

This recipe is for restoring trust after a product-direction miss, not for normal refactors. If the user is happy and the surface has real usage, do not rip.

## The recipe

**1. Capture the user's exact words verbatim in a `[DIRECTION]` entry in `PLAN.md`.** A direct quote is more durable than a paraphrase. Future agents read it and feel the temperature.

**2. Add a `HARD NEVER` constraint listing every forbidden surface by name.** Not "no bloat" — name the specific CSS class names, panel types, and field counts the previous version used. The constraint is enforceable, the platitude isn't.

**3. Rip the default surface back to one obvious question.** "What should I do next?" beats "fill in this form." Single column, comfortable reading width, and the house style the rest of the app already uses.

**4. Move every removed surface into its own route, but only if the user asks for it.** `/x/calendar`, `/x/templates`, `/x/queue`. Each new route requires its own fresh `[DIRECTION]` entry — the rip directive's restriction is on the default route, not on the data.

**5. Keep the data layer intact.** The previous agent's types, store, API routes, and helpers are real work; the UI just over-surfaced them. Delete UI, keep lib.

**6. Layer the directive in three places so future lanes can't drift back:**
   - `PLAN.md` Decision Log + `## Constraints` NEVER row
   - The cron lane's prompt file (live + a mirror committed to the repo at `docs/lane-prompts/<lane>.md`)
   - A lint guard script (`scripts/<repo>-shape-check.sh`) wired into `npm run test:all` / equivalent that greps the source for the forbidden class names

**7. Ship evidence the rip held.** Side-by-side screenshots (empty + with-data, light + dark, desktop + mobile), an evidence README indexing them, and a cron-stability observation log proving N consecutive idle ticks after the directive landed.

## Failure modes

Without this recipe, a feature-heavy surface can keep accumulating UI even after the first bad signal:

- The "improve the cockpit" cron tick interpreted as "add more features"; eight ticks shipped MCP-1 through MCP-3 stacking filter decks, readiness matrices, hook/packet panels, 42-cell calendar, and a 16-field form onto a workspace with zero records.
- User feedback fires late; without a `[DIRECTION]` entry the next automated cycle can still add more.
- "Polish the UX" with no NEVER constraint is unbounded — each agent rationalizes one more affordance.
- The 16-field form encoded everything the type system supported as a visible control. The type system doesn't say "always render this."

## Worked Example

A dashboard-page reset is the calibration case:

- Captured the user's words verbatim
- HARD NEVER lists 9 specific CSS class names (filter-deck, prep-strip, readiness-matrix, suggestion-panel, calendar-panel, queue-sections, hook-panel, packet-panel, matrix-grid)
- Default `/household` shrank from 821 → 409 tsx + 542 css; 70+ visible controls → 7
- `/household/calendar` was later authorized as a separate route via fresh `[DIRECTION]` entry; default route stayed minimal
- Lib (`lib/household/*.ts`) untouched — same SocialPost schema, same `/api/household/events` endpoint, same conflict-resolution semantics. Just the UI got smaller.
- A `shape-check.sh` script greps the source for the forbidden class names; wired into `npm run test:all` so the next cron tick that re-bloats fails loud.
- Cron lane prompt + memory `[DIRECTIVE]` + repo-tracked mirror at `docs/lane-prompts/content-prep.md` keep the directive durable across lane-memory rebuilds.

## Calibration

- Use this recipe when the rip is **the user's explicit request**, not when you personally think a surface is busy.
- Do NOT rip surfaces that have real data and real users. The trigger is "near-empty workspace AND user is upset." Without both, smaller refactors are the move.
- After the rip, polish has to stop. Each additional commit on the just-ripped surface risks being procrastination dressed as taste (vidux Principle 4 — a shipped surface that works is done).
