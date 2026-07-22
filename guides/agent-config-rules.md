# Agent Config Rules

Hygiene rules for AI agents running the vidux cycle. These rules are platform-agnostic — they apply whether your agent config lives in CLAUDE.md, .cursorrules, AGENTS.md, or any other format.

Each rule addresses a specific failure pattern observed when agents run unattended.

---

## Rule 1: Re-read before editing state files

Before applying any edit to a plan file, memory file, state file, or JSONL, re-read the file in the same turn. Stale context from earlier in the session causes whitespace mismatches, silent clobbers, and corrupted state.

**Why:** Agents that read a file early in a cycle and edit it later often fail because another process (a parallel agent, a hook, a cron) modified the file between the read and the edit. The edit tool matches against stale content and fails.

**Config rule to add:**
```
When editing memory/state files, always re-read the file immediately before
applying edits. Never assume file contents from a previous read are current.
```

## Rule 2: Re-read after failed edits

After a failed edit (string not found, wrong match, unexpected content), never guess the fix. Re-read the file, then retry with the exact current content.

**Why:** The most common response to "old_string not found" is to tweak the whitespace and retry. This guesses at the file state instead of observing it. The fix is always the same: read the file, copy the actual content, then edit.

**Config rule to add:**
```
After a failed Edit, re-read the target file before retrying. Do not guess
what the content should look like — read it and use what's actually there.
```

## Rule 3: Proportional response

For simple copy, naming, or creative requests, respond directly with 2-3 options. Do not create plan tasks, investigations, or multi-step workflows for work that takes under 2 minutes.

**Why:** Agents optimized for multi-step autonomous work sometimes apply heavyweight patterns to lightweight asks — spinning up task chains, invoking brainstorming skills, or creating investigation files for a simple "give me a better headline." This wastes time and often leaves the session incomplete because the overhead consumed the budget.

**Config rule to add:**
```
For simple creative/copy requests (hero text, tagline, CTA wording), respond
directly with 2-3 options. Save structured workflows for multi-surface work.
```

---

## What's already covered in core

**Verification before completion** is covered by Principle 5 ("Prove it mechanically"). If your agent marks tasks `[completed]` without running the build or tests, the fix is enforcing Principle 5 in your agent config:

```
Never mark a task [completed] or assert "it works" until you have run the
verification command (build, test, screenshot) and confirmed the output.
```

This is not a new rule — it's the operational form of an existing vidux principle.

---

## How to apply

Copy the rules above into your agent's config file. Adapt the format to your platform:

| Platform | Config file | Format |
|---|---|---|
| Claude Code | `CLAUDE.md` or `.claude/CLAUDE.md` | Markdown rules |
| Cursor | `.cursorrules` | Plain text rules |
| Codex | Agent instructions or `AGENTS.md` | Markdown rules |
| Other | Project-level agent config | Varies |

These rules complement the vidux cycle — they don't replace it. The cycle gives you the workflow (READ, ASSESS, ACT, VERIFY, CHECKPOINT). These rules make the tools inside that workflow more reliable.

---

## Change Classification (T1-T4)

When you discover a friction pattern (from session analysis, `/insights`, or manual observation), classify it before changing anything. The tier determines where the fix goes:

| Tier | What changes | Where the fix lives |
|---|---|---|
| **T1: Prompt** | Lane/automation prompt wording | The specific automation's prompt file |
| **T2: Agent config** | Global agent behavior rules | CLAUDE.md / .cursorrules / AGENTS.md |
| **T3: Companion** | New automation pattern or recipe | `guides/automation.md`, `references/automation.md`, or related guides/ |
| **T4: Core** | Fundamental principles or contracts | vidux SKILL.md |

**The rule: work from T1 up.** If the fix can live in a prompt, don't touch the agent config. If it can live in the agent config, don't add a recipe. If it can live in a recipe, don't change the core discipline.

**T4 has a gate.** Core vidux only changes when the DISCIPLINE produced the wrong outcome — not when an implementation detail failed. A whitespace mismatch in Edit is a T2 fix (agent config rule). A stuck cron loop is a T3 fix (new recipe). The five principles changing is T4 — and should be rare.

### Triage process

After every ~10 sessions, review your session analytics:

1. **Identify friction** — what went wrong, what tools failed, what took too long
2. **Classify each finding** — T1, T2, T3, or T4
3. **Apply T1/T2 immediately** — prompt tweaks and agent config rules are safe to apply
4. **Plan T3** — new recipes get a PLAN.md task before implementation
5. **Escalate T4** — core changes need evidence that the discipline itself is broken

Build automation for this process only when manual triage proves painful (>15 findings per review). A 2-minute manual pass is cheaper than maintaining a classification script.
