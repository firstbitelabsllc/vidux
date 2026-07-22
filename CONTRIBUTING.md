# Contributing

Vidux is MIT-licensed and prepared for public reuse, critique, and feedback.

Current policy:

- Please open Issues for bugs, gaps, critiques, and adoption feedback.
- External pull requests are not being accepted right now. `.github/PULL_REQUEST_TEMPLATE.md`
  exists for PRs the maintainer or their agents open against this repo — its
  presence isn't an invitation for unsolicited external PRs; the policy above
  still applies.
- If you build on Vidux, examples and field reports are especially useful.
- Please do not propose integrations that sync Vidux state into an external
  project-management board. Vidux's queue authority is `PLAN.md` in git; teams
  can mirror that state by hand, but Vidux will not round-trip it.

Why:

- The doctrine is still being tightened.
- The portable core is intentionally small and opinionated.
- Feedback is high-signal right now; code intake is not.
- Board sync creates a second queue authority, which is the failure mode Vidux
  is designed to avoid.

If that policy changes, this file will change first.

## Running the tests locally

Useful for verifying a bug report or exploring the codebase even though PRs
aren't merged right now:

```bash
npm install
npm run verify        # npm test (JS + Python units) + the public-ready grep gate
npm run test:e2e       # Playwright, needs `npm run playwright:install` once
npm run release:verify # reproducible, tracked-only installable package boundary
```

## Code style

There's no linter/formatter config in this repo (no ESLint/Ruff/Prettier) —
match the surrounding file's formatting. `WRITING-STYLE.md` is a different
thing: it's prose-writing guidance for the agent-facing doctrine docs
(SKILL.md, DOCTRINE.md, etc.), not a code style guide.
