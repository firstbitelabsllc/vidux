# Vidux — Plan

This is the repository's own working plan, kept in the same shape `vidux init`
scaffolds. It is planning authority for this repo; proof lives in the gates it
names, not in this prose.

## Purpose

Ship and maintain Vidux as a small, local-first plan/proof/resume layer that
complements native coding agents. It records durable planning authority
(`PLAN.md`), shipped-cycle proof packets, and a read-mostly local cockpit — and
it never routes models, schedules work, or transports provider traffic.

## Evidence

- `README.md` — public contract and quick start.
- `CHANGELOG.md` — 1.0.0 scope.
- Test suites under `tests/` and `browser/tests/`; CI in `.github/workflows/`.

## Constraints

- Local-first and read-mostly: no new mutation, shell execution, secret
  access, or remote dispatch endpoint without an explicit threat model and a
  regression gate.
- The steering inbox and coordination claims stay loopback-only, plan-scoped,
  provider-neutral, non-executing, and independently auditable.
- Provider selection, worker dispatch, and evaluation belong to the coding
  host, never to Vidux.

## Operator Brief

- Status: 1.0.0 source contract landed
- Outcome: minimal public surface — `init`, `status`, `browse`, `doctor` —
  with green vitest + unittest suites, release-package verification, and the
  public-ready gate wired into CI.
- Next: keep the surface minimal; new capability requires a plan row here
  first, with its gate named before code lands.
- Validation: `npm run verify` (tests + public-ready gate) and
  `npm run release:verify`.

## Outcome Scorecard

| Metric | Current | Target | Proof |
|---|---|---|---|
| Test suites | green | green | `npm test` |
| Package byte-identity | passing | passing | `npm run release:verify` |
| Public-ready gate | passing | passing | `npm run public-ready:grep` |

## Tasks

- [completed] Cut the CLI to the minimal public surface and align docs.
- [completed] Wire CI: tests, release verification, secret scan, public-ready gate.
- [pending] Triage issues and PRs after the repository is public.

## Decision Log

- [2026-07-21] 1.0.0 is a local source contract, not a published release: no
  npm publication, git tag, or GitHub Release is claimed until one exists.
- [2026-07-21] Internal helpers (steering mailbox, coordination claims, config)
  stay invoked by script path; the CLI surface stays at four commands.

## Progress

- 2026-07-21: 1.0.0 cut — minimal CLI surface, consolidated CI, fresh
  changelog, plan reset to the scaffold shape.
