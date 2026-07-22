# Proj Alpha — Test Fixture

## Purpose

Hermetic test fixture for vidux-browse e2e specs. Two tasks, one in-progress + one pending.

## Operator Brief

- Status: shipping
- Priority: 90
- Outcome: Prove the browser leads with one evidence-backed mission.
- Next: Open the selected plan without entering Advanced view.
- Why: A first-time operator needs direction before the full fleet queue.
- Validation: Hermetic Playwright smoke.
- Cost: No paid runtime dependency.
- Evidence: evidence/mission-control.md
- Updated: 2026-07-09

## Outcome Scorecard

| Metric | Baseline | Current | Target | Status | Proof |
|---|---|---|---|---|---|
| First-viewport direction | Missing | Visible | Visible | winning | evidence/mission-control.md |
| Benchmark conclusion | Losing | Losing | Winning | losing | evidence/mission-control.md |

## Tasks

- [in_progress] First task — render the sidebar with this row [ETA: 1h]
- [pending] Second task — verify clicking this row opens the plan [ETA: 0.5h]
