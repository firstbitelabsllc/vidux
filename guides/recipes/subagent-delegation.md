# Recipe: Subagent Delegation (Mode A / Mode B)

Same-tool delegation between a **parent agent** and a **child subagent** spawned via `Agent()`. Replaces the pre-2.10.0 cross-tool model (Claude parent → Codex secondary).

---

## When to use

- Your parent context is expensive or close to limits
- A task requires reading >3 KB of source or writing >10 lines of code
- The delegated task has a tight spec (Mode B) or returns a compressed summary (Mode A)
- You want parent context to stay bounded across long autonomous cycles

---

## Why same-tool only (2.10.0 change)

Cross-tool delegation (Claude parent → Codex secondary via `codex exec --sandbox read-only`) was deprecated in 2.10.0 for three reasons:

1. **Prompt-shim fragility.** The parent had to synthesize a shell-escaped prompt and parse Codex's stdout back into a summary; TOML/shell quoting broke on backticks, heredocs, and long prompts.
2. **Context loss across the boundary.** Codex ran in a fresh process with no memory of the parent's plan state, so every delegation re-explained the mission and summaries came back stripped of the parent's working hypothesis.
3. **Egress friction.** Codex ran in a separate sandbox; the parent couldn't reach into the worktree to confirm edits. Mode B required shared filesystem plus careful sandbox selection — routinely mis-configured.

Now delegation is **parent Agent → child `Agent()` subagent, same runtime.** The subagent inherits the parent's environment, gets a fresh context window, and returns via the same tool protocol. No shell escaping, no cross-process coordination, no sandbox mismatch.

If you run Codex as your primary tool, see `guides/recipes/codex-runtime.md` — same pattern, but the dispatch primitive is Codex's own equivalent of `Agent()`.

---

## Mode A — Research delegation

```
Parent: reads PLAN.md, picks next task
Parent: "This task needs 30 file reads. Hand it off."
Parent: writes a tight research prompt with the compression contract
   |
   v
Child subagent (spawned via Agent()):
   grinds through files, reasons, compresses to 3 sections
   returns: Summary + Evidence + Recommendation
   |
   v
Parent: reads the ~300-token summary
Parent: applies taste — accept, reject, or re-prompt
Parent: ships the edit, updates plan, checkpoints
```

Use for: audits, investigations, cross-file grep synthesis, pattern hunting, evidence gathering.

### The compression contract (paste verbatim in every Mode A prompt):

```
Output ONLY these sections, nothing else, no preamble, no code blocks, no closing:

1. Summary: 3 sentences MAX describing <the thing>.
2. Evidence: 3 file:line references MAX, one per line.
3. Recommendation: 1 sentence MAX on the next action.

Do not explain your reasoning. Do not echo the task. Do not write code.
If you find yourself writing more than those three sections, stop.
```

Honored reliably across reasoning levels (medium/high/xhigh all return exactly 3 sections, <0.2% token variance).

---

## Mode B — Implementation delegation

```
Parent: reads PLAN.md, picks next task
Parent: "This is a 50-line fix with a clear spec. Hand it off."
Parent: writes a 5-block implementation prompt (see below)
   |
   v
Child subagent (spawned via Agent()):
   reads task files, writes code, saves edits in the working tree
   |
   v
Parent: runs `git diff` in the working tree (~500 tokens)
Parent: applies taste — accept-and-commit, re-prompt, or `git checkout .` + redo
Parent: runs lint/test/build, commits, pushes (if authorized)
```

Use for: bug fixes, feature implementation, refactors, tests, docs — anywhere a tight spec produces 10-500 lines of code.

### The Mode B prompt shape (5 mandatory blocks):

Every Mode B prompt includes ALL FIVE blocks:

```
1. Task: one-sentence description of the change.
2. Files: exact paths the secondary may edit. NO other files.
3. Spec: what the code must do, in 3-10 bullets. Include error handling,
   edge cases, and test expectations when relevant.
4. Acceptance criteria: how the primary will judge the diff on review.
5. Out of scope: what the secondary must NOT change (prevents refactor creep).
```

The "Out of scope" block is load-bearing. Without it, the subagent often refactors adjacent code it decides "looks wrong" — the parent's diff review then either accepts unasked-for scope (tech debt) or rejects the whole diff (wasted cycle).

---

## Decision tree

- **Substantial code writing (>10 lines, clear spec)** → Mode B
- **Reading code, research, grinding a hard problem** → Mode A
- **Small (<10 lines), obvious, pure taste** → parent does it directly

---

## Diff-review checklist (parent's job after Mode B returns)

Run `git diff` and verify in this order — stop at the first fail:

1. **Scope.** Does the diff touch only files listed in the prompt? If not → `git checkout .` + re-prompt with stricter "Files" list.
2. **Spec fit.** Does each change map to a Spec bullet? Unexplained edits → reject.
3. **Out-of-scope drift.** Renamed functions, import reordering, style-only tweaks, "cleanup" refactors → reject unless explicitly asked.
4. **Obvious correctness.** Does the logic make sense? Spot-check against the Spec's edge cases.
5. **Taste.** Readable? Matches surrounding style? If not → re-prompt, don't hand-fix.
6. **Lint + test + build.** Run local toolchain. If red: small fix = parent fixes; structural = re-prompt subagent.
7. **Commit.** ONE commit per delegated task. Parent writes the message.

---

## Measured wins (historical, from cross-tool era)

The 10-110x Mode A and ~5x Mode B savings were measured with Claude-primary + Codex-secondary, where the secondary's cost sat on a **separate token account**. Same-tool dispatch still saves significantly — the parent reads only the compressed summary or the diff, never the full working set — but absolute numbers differ since parent and child draw from the same account. Treat the old tier table as directional:

| Tier | Source size | Direct-read parent tokens | Delegated parent tokens |
|---|---:|---:|---:|
| TINY | 33 KB | 8,262 | ~800 |
| MEDIUM | 160 KB | 40,208 | ~800 |
| HEAVY | 357 KB | 89,339 | ~800 |

Savings ratio is lower under same-tool dispatch, but the bounded-parent-context property still holds — the real win for long autonomous cycles.

---

## Execution rules

1. **One cycle per invocation.** Do not chain multiple delegated tasks.
2. **Compression contract is mandatory in Mode A.** Mode B uses the 5-block spec shape instead.
3. **Parent keeps taste.** Never let the subagent make final architectural or design decisions.
4. **Verify before acting.** Mode A: discard off-topic summaries and re-prompt. Mode B: if `git diff` shows over-scope or spec mismatch, `git checkout .` and re-prompt.
5. **Log every delegation.** One line per call in the plan's `## Progress` section, or in a lane `PROGRESS.md` overlay when one exists: task id, mode (A/B), approximate subagent tokens, parent tokens consumed, exit code.
6. **Parent owns the commit boundary.** Even in Mode B, the subagent never runs `git commit`, `git push`, or mutates `.git/`.
7. **No Mode B for schema/migration/destructive work.** Database migrations, dependency bumps, CI config, auth flows stay in the parent's direct-write path.

---

## Deprecated patterns

- **Cross-tool delegation** (Claude parent → Codex `codex exec --sandbox read-only` secondary). Fragile and context-lossy. Retired 2026-04-17 in vidux 2.10.0.
- **Codex shim prompts** (shell-escaped prompts piped to `codex exec`). Tolerated for historical lanes during the breadcrumb window, not for new work — new code-writing lanes spawn same-tool subagents.
- **Mixed-fleet coordination** (Claude writer + Codex peer writer against the same PLAN.md). Retired. If you run Codex, run Codex-only — see `guides/recipes/codex-runtime.md`.

---

## See Also

- `guides/recipes/codex-runtime.md` — if you're running vidux ON Codex, not delegating TO it
- `references/automation.md` Section 4 — full delegation doctrine with tier math
- `CHANGELOG.md` 2.10.0 — deprecation notice and rationale
