# Recipe: Visual Proof Required

> For UI and CSS changes, unit and e2e tests are not evidence of "done." Take the screenshot.

## When to use

- Any change that could affect a user-visible surface (fonts, colors, layout, spacing, components)
- Tailwind v4 `@theme` registrations — fonts, colors, custom tokens
- CSS variable changes, design-token updates
- Font loading, icon rendering, SVG inlining
- About to mark a UI task `[completed]`

## The recipe

**1. Unit + e2e tests are NOT sufficient evidence for UI work.** They don't see what the user sees. A font registration can fail silently and still pass every test in the suite.

**2. Before declaring complete, capture visual proof in-session:**
   - Playwright screenshot (preferred for web)
   - `mcp__XcodeBuildMCP__screenshot` for iOS simulator
   - `craft-svg` render check for inline SVG work
   - Manual simulator capture or browser screenshot attached to the commit
   - Visual regression test passing (Percy, Chromatic, etc.) if the project has one

**3. Specifically check Tailwind v4 `@theme` registrations when fonts or tokens are involved.** Registration errors pass unit tests but break visually. Open the page, look at the surface.

**4. Definition of done for UI work:**
   - Visual proof exists in-session (attached, described, or linked in the commit)
   - Checked against the before state (screenshot diff, or explicit "matches design")
   - Checked at least one edge: dark mode, mobile viewport, or long-content state

**5. Blocking gate:** If a user-visible surface changed and no visual proof exists, the task is **not** `[completed]`. Mark it `[in-progress]` until proof is captured.

## Failure modes

Without this recipe (from /insights):

- Tailwind v4 `@theme` font registration broke the guest flow visually
- Unit tests passed. E2E tests passed. Everything green.
- User saw the wrong font on a real device — test coverage gap
- Bug shipped to production because "done" was claimed on test evidence alone
- Fix rolled back, time lost, trust eroded

## Example

**Wrong:**

> Registered `Inter` in `@theme`. Ran `pnpm test` (143 pass) and `pnpm e2e` (47 pass). Marking [completed].

**Right:**

> Registered `Inter` in `@theme`. Ran `pnpm test` (143 pass) and `pnpm e2e` (47 pass). Took Playwright screenshots of guest flow at `/signup` and `/dashboard` in light + dark mode. Verified Inter renders (not the system fallback). Screenshots attached to commit abc123. Marking [completed].

**Wrong:**

> Updated the button color token. Tests pass. Done.

**Right:**

> Updated the button color token. Took a screenshot of the primary CTA in light + dark mode, compared against Figma. Matches. Marking [completed].

## See Also

- `guides/recipes/evidence-discipline.md` — the general version of this rule
- A browser-automation tool (Playwright, Puppeteer, Browserbase, etc.) — web screenshot capture
- An iOS simulator capture tool — iOS visual proofs
- A Figma-to-code design tool — pixel comparison against the spec
