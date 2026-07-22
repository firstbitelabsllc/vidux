# Thin-token Vidux (use the cockpit, not the corpus)

**Why this exists:** Loading full SKILL/orchestration into every agent cycle burns tokens without improving outcomes. Vidux’s high-value surface is **one plan, decisions, proof, resume** — not a second control plane.

## Load this (≤1 screen)

| Need | Open / pass the agent |
|------|------------------------|
| What to do next | Owning `PLAN.md` → Open work + Current State |
| Why | `## Decisions` / Decision Log only if the row cites one |
| Proof bar | The row’s `[validation: …]` or Evidence path |
| Resume | Current State “Resume pointers” one-liner |
| UI | Browser Simple view (default): plan list + PLAN body |

## Do not load by default

- Full `SKILL.md` (load only when editing doctrine/contracts)
- `guides/automation.md`, `fleet-ops`, PE harness, `evaluations/`
- Planner-executor / Fable kernel handoff templates
- Entire recipe book — one recipe ID is enough

## Agent cycle (cheap)

```text
1. Read PLAN.md Current State + first agent-reachable Open work row
2. Do one vertical slice on allowed paths only
3. Run the row’s validation command (or the focused suite below)
4. Checkpoint PLAN: status, weakest claim, next resume
5. Stop or take the next explicit row — do not invent orchestration
```

### Default proof commands (facelift / cockpit work)

```bash
cd ~/Development/vidux
# one command = focused gate + Simple/thin-token structure checks
bash scripts/vidux-thin-loop-verify.sh
# deeper when UI server changed:
# python3 -m unittest tests.test_browser_server -q
```

Broader `npm run test:py` may show **2 known `/auto` failures** if a private `/auto` skill still exists on the machine — treat as env, not facelift regressions, until rehomed.

## Multi-agent (max 2–3 workers)

| Role | Owns | Must not |
|------|------|----------|
| **Lead** | PLAN status, proof claim, PR shape, foldback | Overlapping file edits with workers |
| **Worker A** | Tests / size gate | Docs or broad UI |
| **Worker B** | One UI surface (e.g. Simple mode) | PLAN doctrine rewrites |
| **Worker C** | One guide/recipe file | Runtime code |

- Fan-out only on **non-overlapping paths**.
- Workers return: paths changed, commands run, weakest claim, blockers.
- **Never** spawn PE kernel sidecars for routine product work.

## Browser: Simple vs Advanced

- **Simple (default):** plan browser + progress — what most humans/agents need.
- **Advanced (toggle):** fleet dashboard, ops truth, Decision/Session/Ledger tabs.

Operators who need fleet/ops switch Advanced; everyone else stays Simple and keeps context small.

## Pointers

- Ranked queue: `evidence/2026-07-09-multi-agent-work-queue.md`
- Kernel-cut evidence: `evidence/2026-07-07-kernel-cut-pivot.md`
- Fan-out pattern: Recipe 12 (assessors) + Recipe 13 (product slices) in `guides/recipes.md`
