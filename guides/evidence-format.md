# Evidence Directory Format

Reference guide for evidence file naming, structure, and PLAN.md referencing.
Extracted from Vidux core documentation.

---

## Purpose

Long-form evidence lives in `evidence/` files alongside `PLAN.md`, not inline in the plan.
Tasks cite file paths; the plan stays lean. Each snapshot is an auditable evidence record.

---

## Naming Convention

```
evidence/YYYY-MM-DD-<slug>.md
```

- Use ISO date prefix for chronological ordering in git history.
- Slug should be 2-4 words: `harness-retro`, `auth-patterns`, `api-latency-analysis`.
- One file per research session or material cycle. Do not append unrelated findings to existing files.

---

## Required Format

```markdown
# YYYY-MM-DD <Descriptive Title>

## Goal
One sentence: why this snapshot was created and what question it answers.

## Sources
- [Source: <tool/file/url>, <date>] <what was queried or read>
- [Source: codebase grep] <file:line pattern found>
- [Source: MCP query] <tool + query used>
- [Source: observed] <user-observed behavior, e.g. "flicker on first render", "Remove button silently no-ops">

## Findings

### 1. <Finding title>
<Finding body. Be specific: quote, file path, line number, metric value.>

### 2. <Finding title>
...

## Recommendations
- <Actionable next step derived from findings. Optional -- omit if findings speak for themselves.>
```

---

## When to Create vs Append

| Situation | Action |
|-----------|--------|
| New research session on a new topic | Create a new file with today's date |
| Adding a follow-up finding to an existing session | Append a new `### N. Title` under existing `## Findings` |
| Existing snapshot is from a different date | Create a new file (keep date-accurate audit trail) |
| Findings contradict an earlier snapshot | Note the contradiction in the new file; do not edit the old one |

---

## Referencing from PLAN.md

Task evidence citations point to the file and section, not the full content:

```markdown
- [pending] Task 5: ... [Evidence: `evidence/2026-04-03-api-patterns.md#findings`]
```

When a single snapshot covers multiple tasks, each task cites the relevant section anchor.

---

## Relationship to PLAN.md Evidence Section

`PLAN.md ## Evidence` summarizes what is known at plan creation -- one bullet per key finding.
`evidence/` files contain the raw, cited, time-stamped snapshots that back those summaries.
Both are required. Summaries without snapshots are guesses.
