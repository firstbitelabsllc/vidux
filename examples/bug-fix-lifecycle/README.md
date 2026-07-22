# Example: Bug Fix Lifecycle

A minimal worked example showing how vidux handles a bug report from start to finish. This is the simplest possible vidux cycle — one bug, one plan, one fix.

> _Illustrative scenario. The `LoginButton.tsx` bug, file paths, and commit
> SHAs below are hypothetical, chosen to show the shape of a cycle — they are
> not real files in this repository._

## The Scenario

A user reports: "Nothing happens when I tap Login right after the page loads." The agent doesn't know the codebase yet.

## Step 1: Gather Evidence

The agent searches the codebase and documents what it finds.

```
evidence/2026-04-01-login-button-early-tap.md
```

```markdown
# Evidence: Login Button Does Nothing On Early Tap

## Source
- User report: "Nothing happens when I tap Login right after the page loads"
- Reproduces only when the button is tapped before config finishes loading

## Findings
- `src/components/LoginButton.tsx:42` — `onClick` calls `login(config.endpoint)`
- `config` is fetched asynchronously and is `undefined` on the first render
- An early tap calls `login(undefined)`, which rejects silently — no error shown
- `SignupButton.tsx` already guards this with `disabled={!config}` (commit abc1234)

## Conclusion
Missing loading guard. The handler can run before `config` is ready; the signup
button was guarded but login was missed.
```

## Step 2: Write the Plan

The agent creates `PLAN.md` with evidence-cited tasks.

```markdown
# Fix: Login Button Does Nothing On Early Tap

## Purpose
Guard the login button until config loads. Users who tap early cannot log in.

## Evidence
- [Source: codebase search] LoginButton.tsx:42 calls login(config.endpoint) with no guard
- [Source: git blame] SignupButton.tsx was fixed for the same issue in abc1234
- [Source: user report] Reproduces on an early tap before config loads

## Tasks
- [pending] Task 1: Disable LoginButton until config is loaded [Evidence: LoginButton.tsx:42, SignupButton fix abc1234]
- [pending] Task 2: Add a test for the tap-before-config-ready case [Evidence: no existing early-tap test]
- [pending] Task 3: Verify the disabled state renders while config is pending [Evidence: user report]

## Decision Log
- [DIRECTION] [2026-04-01] Root cause is a missing loading guard, not a network error. Evidence: SignupButton had the same bug and the disabled-until-loaded fix resolved it.
```

## Step 3: Execute One Task

The agent pops task 1, writes the fix:

```diff
// src/components/LoginButton.tsx
- <button onClick={handleLogin}>
+ <button onClick={handleLogin} disabled={!config}>
```

Updates the plan:

```markdown
- [completed] Task 1: Disable LoginButton until config is loaded [Done: 2026-04-01]
- [pending] Task 2: Add a test for the tap-before-config-ready case
- [pending] Task 3: Verify the disabled state renders while config is pending
```

## Step 4: Verify

The agent runs tests, checks the build, confirms no regressions.

## Step 5: Checkpoint

The agent appends to `## Progress` in `PLAN.md`:

```markdown
## Progress
- [2026-04-01T14:30:00Z] Task 1 completed. Disabled LoginButton until config loads. Tests pass. Build clean.
```

Then exits. The next agent (or the same one in a new session) reads `PLAN.md`, sees task 2 is pending, and continues.

## Key Takeaways

1. **Evidence comes first.** The agent didn't guess — it searched the codebase and found the SignupButton precedent.
2. **One task per cycle.** The agent added the guard, didn't also refactor the component.
3. **The plan persists.** A different agent tomorrow can pick up task 2 without any context about today's session.
4. **Decisions are logged.** Future agents know _why_ this is a loading-guard issue, not a network error.
