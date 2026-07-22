# Investigations & Compound Tasks

Reference guide for nested investigations, compound task architecture, and escalation rules.
Extracted from Vidux core doctrine and loop mechanics.

---

## Doctrine 7: Bug Tickets Are Investigations, Not Tasks

A bug ticket is NOT a task to check off. It is a **nested investigation** -- a plan-within-a-plan
that follows the same unidirectional flow as the parent ("tree of viduxing"): the parent plan
spawns sub-investigations, each with its own evidence/root-cause/fix cycle.

**Why this matters:** Treating tickets as line items makes agents jump straight to code, fixing
one symptom but missing the root cause -- then the next ticket on the same surface regresses it.
The popover amount-editor had 8+ tickets and 8+ "fixes" that kept undoing each other because no
one mapped the full system first.

**The rule:** Before writing code for a bug ticket, produce a nested investigation.
Mark the parent task with `[Investigation: investigations/<slug>.md]`.

---

## When to Investigate vs Just Fix

- ALWAYS for 2+ tickets on the same surface (bundle them into one investigation)
- ALWAYS for UI bugs needing runtime/visual verification
- ALWAYS when root cause is unclear ("it's weird", "even buggier than before")
- ALWAYS three-strike: 3+ prior fixes on the same area
- OPTIONAL for pure data/logic bugs with obvious single-file fixes (keep atomic)

---

## Three-Strike Escalation

If a surface has had 3+ tickets filed against it, the investigation MUST include a full
Impact Map before any code. A surface with 3+ tickets is not a series of bugs -- it's a
design problem.

---

## Atomic vs Compound Tasks

Some tasks require investigation before code -- root cause analysis, impact mapping, evidence
gathering across related tickets. These are **compound tasks**.

```
Parent PLAN.md (the expedition)
+-- [pending] Task 1: update copy token          <- atomic: execute directly
+-- [pending] Task 2: fix popover amount-editor   <- compound: needs investigation
|   +-- investigations/popover-amount-editor.md   <- sub-plan
+-- [pending] Task 3: folder nav dismiss          <- atomic
+-- [pending] Task 4: assignment label rendering  <- compound
    +-- investigations/assignment-labels.md       <- sub-plan
```

**Atomic tasks** have self-contained descriptions with inline evidence. Pop, execute, checkpoint.

**Compound tasks** link to an investigation file. The task in PLAN.md looks like:

```markdown
- [pending] Task 2: Fix popover amount-editor system [Investigation: `investigations/popover-amount-editor.md`] [Depends: none]
```

The `[Investigation: ...]` marker tells the agent: read the sub-plan before coding.
Use compound tasks under the same conditions as "When to Investigate vs Just Fix" above.

---

## Investigation Template

Lives in `investigations/` alongside `evidence/` in the project directory.

```markdown
# Investigation: [surface name]

## Tickets
- [ASC-ID] "[exact reporter quote]" -- [triaged|fixed|blocked]
- [ASC-ID] "[exact reporter quote]" -- [triaged|fixed|blocked]

## Evidence
- Files that own this surface: [list with line numbers]
- Related tickets (same surface, any status): [list]
- Recent commits: `git log --oneline -5 -- <files>`
- Repro: [steps or screenshot path]

## Root Cause
What is actually broken and why. Not symptoms -- the specific code path.

## Impact Map
- Other UI paths that render this surface: [list]
- Other tickets fixed/broken by this change: [list]
- State flow: [data model -> view model -> view chain]

## Fix Spec
- File:line -- change X to Y
- File:line -- add Z
- [Evidence: why this is the right fix]

## Tests
- Test 1: [what it asserts, covering THIS ticket]
- Test 2: [what it asserts, covering RELATED tickets]
- Test 3: [what it asserts, preventing reintroduction]

## Gate
- [ ] build passes
- [ ] tests pass (including new)
- [ ] visual check or runtime smoke (for UI)
```

**If the Fix Spec is missing, keep notes local and move on — no commit or PR until the fix ships alongside the investigation in a single code PR.**

---

## Sub-Plan Linking with `[spawns:]`

A task can link to its sub-plan explicitly using the `[spawns:]` tag:

```markdown
- [in_progress] Task 5: Fix payment flow [spawns: investigations/payment-flow.md]
```

Rules:
- The sub-plan follows the same PLAN.md structure (tasks with `[pending]`/`[in_progress]`/`[completed]`/`[blocked]` states)
- vidux-loop.sh reports sub-plan status in its JSON output when the parent task is `in_progress` or `pending`
- Sub-plan tasks inherit the parent's priority unless overridden
- Traversal is 1 level deep (sub-plans do not recurse into their own `[spawns:]` tags)
- `[spawns:]` and `[Investigation:]` serve the same purpose; `[spawns:]` is the machine-readable form vidux-loop.sh traverses

---

## Status Propagation

The parent task in PLAN.md reflects the investigation lifecycle:

| Investigation state | Parent task status |
|--------------------|--------------------|
| Not started | `[pending]` |
| Evidence gathering in progress | `[in_progress]` |
| Investigation complete, fix spec ready | `[in_progress]` (agent executes) |
| Code done, verified | `[completed]` |
| Blocked on external dependency | `[blocked]` |

### When tickets share a surface

Bundle them into ONE investigation. The evidence gathering and root cause analysis cover ALL
tickets. The fix spec addresses all of them. The tests cover every ticket's scenario. One plan,
one agent, one surface. This prevents the ping-pong pattern where fix A breaks ticket B.

### Relationship to Doctrine 7

Doctrine 7 ("Bug tickets are investigations, not tasks") establishes the WHY. This document
defines the HOW -- the file structure, template, and status propagation rules that make nested
plans work in practice.
