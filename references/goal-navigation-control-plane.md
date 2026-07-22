# Goal Navigation Control Plane

Use this packaged prompt contract for a long-running goal whose durable state
lives in one already-selected plan. Replace the placeholders before launch.
This contract does not choose a model, start a worker, or create a second plan.

## Inputs

- `AUTHORITY_PLAN`: `<EXACT_AUTHORITY_PLAN_PATH>` — one absolute or repo-relative
  root `PLAN.md` or repo-native named plan selected by the host or user.
- `GOAL`: `<GOAL_OUTCOME>` — the outcome, not a frozen task list.
- `HARD_STOPS`: credentials, real money, destructive or irreversible actions,
  external messages, and genuine product-direction forks.

If `AUTHORITY_PLAN` is absent, resolve one existing planning authority using
repo instructions and explicit user steering. Create a root `PLAN.md` only when
no existing root or named authority governs the project. Once selected, carry
that exact path through every claim, steer, checkpoint, receipt, and handoff.
Never silently redirect a named authority to root `PLAN.md` or create a shadow
plan beside it.

## Pasteable Goal Prompt

```text
Pursue <GOAL_OUTCOME> as a persistent, outcome-driven loop.

Authority: <EXACT_AUTHORITY_PLAN_PATH>. Fresh-read that exact file and repo
instructions at the start of every cycle. It owns queue, decisions, blockers,
evidence, exit criteria, and the next resume point. This prompt is only a
navigation contract. Never redirect work to another plan or store live state in
chat.

Resume in-progress work first. Then choose the highest-impact reachable work
that most improves the outcome. When discovery changes what completion means,
update the exact authority before implementation. Park a blocked row only with
the blocker, proof, and exact resume; continue other reachable work. Stop only
when the authority's exit criteria are met or every remaining row is behind a
named hard stop.

Use Vidux only for thin plan, proof, claim, and resume durability. The host
runtime owns scheduling, model choice, delegation, and user replies. Direct
native work is preferred when durable coordination adds no value. Any delegated
worker gets one exact repo/worktree/branch, a bounded non-overlapping writable
path set, a proof floor, and a receipt. The lead inspects every diff and owns
local acceptance and foldback.

After each change, run the narrowest meaningful proof, inspect failures, repair
the cause, and rerun. For user-visible work, inspect the real surface and cover
action, result, loading, empty, error, narrow, wide, light, dark, keyboard, and
assistive-technology states as applicable. Keep source, test, commit, review,
merge, mount, release, deployment, and comparison claims separate.

At every checkpoint update <EXACT_AUTHORITY_PLAN_PATH> with rows moved, exact
proof, changed files, active claims, weakest supported claim, and the next
command. Continue immediately while reachable work remains.
```

## Cycle Contract

1. **READ** — repo instructions, exact authority, relevant evidence, claims,
   and git state.
2. **ASSESS** — infer the hardest reachable work and conflicts; do not drain
   easy polish ahead of a core blocker.
3. **ACT** — claim one bounded surface and make the smallest reversible change
   that advances the outcome.
4. **VERIFY** — run mechanical proof and inspect real behavior at the level of
   the claim.
5. **CHECKPOINT** — update the same exact authority and publish a receipt when
   transport occurs.

One-shot steering is transient intent for `AUTHORITY_PLAN`, not a second
authority. Lease at most one steer at a safe boundary; current plan truth wins
conflicts, and lasting effects go into that same file. A host acknowledges a
steer only after the matching user-facing response. Transport or usage failure
stays visible and retryable.

## Closeout Shape

```text
Authority: <EXACT_AUTHORITY_PLAN_PATH> (<rows moved>)
Selection: <chosen work and why it was highest impact>
Proof: <commands and artifacts>
Truth: <source/test/commit/review/merge/mount/release/deploy/comparison states>
Conflicts: <claims, dirty state, blockers, or none>
Next: <exact row and command>
```

