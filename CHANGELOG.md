# Changelog

All notable changes to vidux are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/) — minor bumps may
tighten doctrine; major bumps change the cycle or `PLAN.md` shape.

## [Unreleased]

### Fixed

- **SECURITY.md** documents shared-temp / multi-user threat class, XDG
  `browser.{pid,log}`, and an honest 1.0.x support table (drops stale
  “unreleased 3.0”) ([#11](https://github.com/firstbitelabsllc/vidux/pull/11)).

## [1.0.2] — 2026-07-24

### Fixed

- **README Release truth** no longer claims “no GitHub Release yet” / `1.0.0`-only;
  documents `1.0.2` source contract + pin to the tagged tip.

## [1.0.1] — 2026-07-24

### Fixed

- **Browser pidfile/log are per-user XDG state**, not shared `${TMPDIR}`.
  Sandboxed `vidux doctor` no longer PASSes on another account's live cockpit
  pid. Path: `${XDG_STATE_HOME:-~/.local/state}/vidux/browser.{pid,log}`;
  legacy `${TMPDIR}/vidux-browser.pid` warns only ([#8](https://github.com/firstbitelabsllc/vidux/pull/8)).
- **`vidux-worktree-gc`: reused branch names can no longer mark unmerged work
  removable.** PR attribution matched by branch name alone, so a branch whose
  earlier PR had merged classified a worktree full of new, genuinely unmerged
  commits as `merged_clean` — the guarded-removal bucket — and `--apply --yes`
  would have deleted them. MERGED/CLOSED PRs now attribute by name only when
  the PR's head OID still equals the worktree's HEAD; OPEN PRs (never
  removable) still attribute by name, and detached worktrees keep the head-OID
  map.
- **`vidux doctor`: a clean same-repo worktree mirror is no longer reported as
  a foreign source.** The mount check compared paths, but the concern it
  guards is stale bytes: a linked worktree of the same repository at the same
  clean HEAD is byte-identical, so it now counts `same_source`. The same
  worktree pinned at a different HEAD, or dirty, warns as `same_repo_stale`
  with the two commits named.
- **`vidux-worktree-gc`: concise error instead of a Python traceback** when
  pointed at a path that is not a git repository.
- **`vidux-worktree-gc`: printed apply commands now include the repository
  path, shell-quoted**, so copying them from another directory targets the
  audited repo rather than the current one.
- **`vidux status`: a plan deleted mid-scan no longer aborts the whole
  board** (the unguarded `stat()` after a guarded read).

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
