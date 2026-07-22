# Recipe Catalog

Two recipe surfaces, mapped into the docs site so VitePress nav matches the repo:

- `guides/recipes.md` — the main automation recipe catalog.
- `guides/recipes/` — focused guides for recurring patterns.

## Core automation recipes

`guides/recipes.md` ships:

| # | Recipe | Notes |
|---|---|---|
| 1 | Fleet Watcher | deprecated 2026-04-17 |
| 2 | PR Reviewer | review automation for PRs |
| 3 | PR Lifecycle Manager | triage, promote, clean up PRs |
| 4 | Observer Pair | deprecated 2026-04-17 |
| 5 | Deploy Watcher | verify deploys; stop after a bounded number of checks |
| 6 | Trunk Health | detect dirty or diverged main early |
| 7 | Skill Refiner | audit skill descriptions, stale references, overlap |
| 8 | Self-Improvement Loop | repo improves itself from current plan and docs |
| 9 | Edit-Then-Verify | pair changes with a verification pass |
| 10 | Cron Retry with Backoff | bound repeated retries |
| 11 | Multi-PR Dependency Shipping | handle ordered PR stacks |

## Supplemental guides in `guides/recipes/`

`claude-md-rules.md`, `codex-runtime.md`, `env-var-forensics.md`, `evidence-discipline.md`, `lane-prompt-patterns.md`, `lightweight-first.md`, `proactive-surfacing.md`, `subagent-delegation.md`, `user-value-triage.md`, `visual-proof-required.md`, `webfetch-fallback.md`.

## How to choose

1. Start with the `guides/recipes.md` recipe matching the automation you want — a lane shape or operating pattern.
2. Pull a focused `guides/recipes/` doc only for a narrow problem (Codex runtime setup, evidence discipline).
3. [Fleet Operations](/fleet/operations) covers always-on rules that apply when no recipe is active; [Harness Authoring](/fleet/harness) keeps the prompt short and stable.
