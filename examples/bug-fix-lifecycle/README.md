# Example: Bug Fix Lifecycle

A minimal worked example showing how vidux handles a bug report from start to finish. This is the simplest possible vidux cycle — one bug, one plan, one fix.

## The Scenario

A user reports: "Login button doesn't work on mobile Safari." The agent doesn't know the codebase yet.

## Step 1: Gather Evidence

The agent searches the codebase and documents what it finds.

```
evidence/2026-04-01-login-button-mobile.md
```

```markdown
# Evidence: Login Button Mobile Safari

## Source
- User report: "Login button doesn't work on mobile Safari"
- Tested on: Safari 17.3, iPhone 15 Pro

## Findings
- `src/components/LoginButton.tsx:42` — uses `onClick` handler
- Mobile Safari requires `onTouchEnd` for reliable tap detection on certain elements
- No touch event handling anywhere in the auth flow
- Similar fix applied to `SignupButton.tsx` in commit abc1234 (6 months ago)

## Conclusion
Missing touch event handler. The signup button was fixed but login was missed.
```

## Step 2: Write the Plan

The agent creates `PLAN.md` with evidence-cited tasks.

```markdown
# Fix: Login Button on Mobile Safari

## Purpose
Fix the login button tap handler for mobile Safari. Users on iOS cannot log in.

## Evidence
- [Source: codebase search] LoginButton.tsx:42 uses onClick only
- [Source: git blame] SignupButton.tsx was fixed for the same issue in abc1234
- [Source: user report] Confirmed on Safari 17.3, iPhone 15 Pro

## Tasks
- [pending] Task 1: Add onTouchEnd handler to LoginButton [Evidence: LoginButton.tsx:42, SignupButton fix abc1234]
- [pending] Task 2: Add mobile Safari test case [Evidence: no existing mobile touch tests]
- [pending] Task 3: Verify fix on iOS simulator [Evidence: user report specifies Safari 17.3]

## Decision Log
- [DIRECTION] [2026-04-01] Root cause is missing touch handler, not a CSS issue. Evidence: SignupButton had the same bug and the onClick→onTouchEnd fix resolved it.
```

## Step 3: Execute One Task

The agent pops task 1, writes the fix:

```diff
// src/components/LoginButton.tsx
- <button onClick={handleLogin}>
+ <button onClick={handleLogin} onTouchEnd={handleLogin}>
```

Updates the plan:

```markdown
- [completed] Task 1: Add onTouchEnd handler to LoginButton [Done: 2026-04-01]
- [pending] Task 2: Add mobile Safari test case
- [pending] Task 3: Verify fix on iOS simulator
```

## Step 4: Verify

The agent runs tests, checks the build, confirms no regressions.

## Step 5: Checkpoint

The agent appends to `## Progress` in `PLAN.md`:

```markdown
## Progress
- [2026-04-01T14:30:00Z] Task 1 completed. Added onTouchEnd to LoginButton.tsx. Tests pass. Build clean.
```

Then exits. The next agent (or the same one in a new session) reads `PLAN.md`, sees task 2 is pending, and continues.

## Key Takeaways

1. **Evidence comes first.** The agent didn't guess — it searched the codebase and found the SignupButton precedent.
2. **One task per cycle.** The agent fixed the handler, didn't also refactor the component.
3. **The plan persists.** A different agent tomorrow can pick up task 2 without any context about today's session.
4. **Decisions are logged.** Future agents know _why_ this is a touch handler issue, not a CSS issue.
