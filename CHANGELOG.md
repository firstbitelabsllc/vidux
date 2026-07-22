# Changelog

All notable changes to vidux are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/) — minor bumps may
tighten doctrine; major bumps change the cycle or `PLAN.md` shape.

## [1.0.0] — 2026-07-21

First public release. Vidux is a thin, local-first plan/proof/resume layer for
coding-agent work: durable `PLAN.md` planning authority, append-only proof and
handoff packets, and a read-mostly local browser cockpit. It never invokes a
model, selects a provider, runs a scheduler, or transports work — the coding
host owns execution.

### Included

- **CLI**: `vidux init`, `vidux status`, `vidux browse`, `vidux doctor`
  (plus `--version`/`--help`).
- **Plan contract**: scaffolded `PLAN.md` with Purpose, Evidence, Constraints,
  Operator Brief, Outcome Scorecard, Tasks, Decision Log, and Progress;
  task states `pending → in_progress → completed` with terminal `blocked`;
  union-merge `.gitattributes` plus `scripts/vidux-plan-guard.sh` so merge
  conflicts and silent task drops stay visible.
- **Browser cockpit**: local read-mostly plan browser (`vidux browse`) with
  plan discovery, truth-band config checks, optional one-shot steering inbox,
  and bounded coordination claims — loopback-only, provider-neutral,
  non-executing. Artifact HTML renders in a network-isolated sandboxed iframe.
- **Doctor**: install, PATH, source-identity, and config diagnostics
  (`vidux doctor`, `--json` for machines).
- **Internal libraries**: steering mailbox, coordination claims, and local
  config helpers under `scripts/`, invoked by script path (not CLI surface).
- **Gates**: vitest + Python unittest suites, release-package byte-identity
  verification, and a public-ready content/identity grep gate wired into CI
  alongside per-diff gitleaks scanning.
- **Runtime**: Python 3.9+ with no third-party dependencies, so vidux runs on a
  stock Mac against `/usr/bin/python3` with no interpreter install. CI runs the
  suite on 3.9 and 3.12 to keep newer syntax from re-entering the tree.

This release is tagged `v1.0.0` with a matching GitHub Release. The `1.0.0` in
`VERSION`/npm metadata is the source contract version; no npm package is
published.
