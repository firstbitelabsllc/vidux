# Scripts Reference

The `scripts/` directory is vidux's executable support layer — shell and Python utilities with responsibilities documented in their header comments.

## Core cycle and plan scripts

| Script | Purpose |
|---|---|
| `scripts/vidux-loop.sh` | Read-only stateless cycle helper. Reads a plan and emits machine-readable next-action state: `hot_tasks`, blocker/stuck-aware `runnable_tasks`, `refresh_proof` routing, stuck-loop `surface_switch` candidates (skipping mechanically stuck, blocker-, dependency-, section-completion-, and approval-gated rows), `handoff_contract` fields on selected-task/missing-plan/no-task exits, latest stale-proof dates, meter checkpoints, `task_id`/resume metadata, archive-pressure warnings. Default read mode never rewrites the plan or appends loop-start ledger rows unless opted in; `--checkpoint` records the plan/progress mutation without inventing commit proof. |
| `scripts/vidux-checkpoint.sh` | Structured checkpoint helper for marking work done, blocked, or archived. Its checkpoint ledger row carries the derived plan task id, plan path, proof, handoff status, files claimed, and next-agent resume. Its two entry shapes are `vidux-checkpoint.sh <plan> <task> <summary> ...` and `vidux-checkpoint.sh <plan> --archive`. |
| `scripts/vidux-config.py` | User-facing config inspector and initializer. Resolves `vidux.config.json`, falls back to `vidux.config.example.json`, validates plan-store and external-root shape, warns on obvious inline secrets, expands configured paths, and prints redacted summaries. Invoked directly: `python3 scripts/vidux-config.py`. |
| `scripts/vidux-status.py` | Read-only status board for operational `PLAN.md` files under the configured roots. Default output hides only empty or fully shipped plans, skips example/fixture trees, prefers task-level `Claims board` status tables over stale task stubs, and keeps plans with literal or prose-blocked rows visible with blocker counts. |
| `scripts/vidux-pr-body.py` | Builds the canonical ready-PR body: lane, existing plan path/checkbox-FSM task row, summary, proof, a matching publish ledger eid (must exist as a publish event in the hot/archive ledger for the same lane/task/summary/plan/proof/handoff/changed-files/file-claims/resume packet), claimed files resolving to existing paths or git-known deletions, self-scrutiny review-pass, resume, and change fields. |
| `scripts/vidux-publish-scrutiny.py` | Read-only preflight for publish packets. Fails closed unless summary/plan path/checkbox-FSM task row/proof/publish ledger eid/handoff/path-like file+claim/resume metadata exists, claims cover every file-claimed entry, claimed paths resolve to existing paths or git-known deletions, and invariant + regression + adversarial review passes are recorded passing. |
| `scripts/vidux-release.sh` | Plan/ledger-gated release helper. In `--apply` mode, release publish requires an existing plan path/task row, proof, handoff status, changed-file claims, and next-agent resume. It synchronizes `VERSION`, npm metadata, and the Claude plugin manifest, verifies the package candidate, then performs CHANGELOG/PLAN/git/ledger mutations. |
| `scripts/vidux-release-package.py` | Builds the exact npm candidate twice in isolated temp directories and fails closed unless hashes match, all version surfaces agree, required CLI/browser files exist, every packaged file is git-tracked and its working-tree bytes plus Git mode match `HEAD`, forbidden local/evaluation/proof roots are absent, and size/count limits hold. This direct comparison does not trust assume-unchanged or skip-worktree status hints. Exposed as `npm run release:verify`. |
| `scripts/vidux-claims.py` | Append-only claims bus for claiming, releasing, and listing active repo surfaces in `~/.agent-ledger/claims.jsonl`. |
| `scripts/vidux-plan-guard.sh` | Detects silent `PLAN.md` task-count drops (a merge, checkout, or stale branch silently deleting tasks). `snapshot <plan>` records the current count to a `.plan-taskcount` sidecar; `verify <plan> [--json]` compares and flags a drop beyond threshold unless authorized by a dated `- [DELETION] [YYYY-MM-DD] ...` Decision Log entry. `vidux-checkpoint.sh` snapshots on every checkpoint; `vidux-loop.sh` verifies on every READ (`plan_integrity_warning`). See `investigations/2026-04-09-plan-clobber-postmortem.md`. |
| `scripts/vidux-step-journal.sh` | Append-only JSONL step journal for crash-safe intra-row resume (idempotency key = row+step). `record`/`is-done`/`resume-point`/`status`/`clear`. `vidux-checkpoint.sh` archives a task's journal on true completion (preserved on `blocked`); `vidux-loop.sh` surfaces `step_journal.{available,row}` when resuming an `[in_progress]` task with an existing journal. |
| `scripts/vidux-write-verify.sh` | Mechanizes Recipe 9 (Edit-Then-Verify): `check <file> [--min-bytes N] [--contains STRING] [--json]` re-reads a just-written file and fails closed on missing/empty/truncated/missing-expected-content. Deterministic pass/fail signal for the agent-side retry loop; does not itself retry. |

## Checkpoint script contract

The hook manifest points at `scripts/vidux-checkpoint.sh`, but the raw script is not a bare post-task hook:

- Normal checkpoint mode: `vidux-checkpoint.sh <plan-path> <task-description> <summary> [--blocker <text>] [--status done|done_with_concerns|blocked] [--outcome useful|busy|blocked_clarified]`
- Archive mode: `vidux-checkpoint.sh <plan-path> --archive`

To wire it into an app-level `afterTask` event, wrap it with the task-specific arguments to record; the normal path derives `task_id` from the task row prefix.

## Health and verification scripts

| Script | Purpose |
|---|---|
| `scripts/vidux-doctor-cli.sh` | User-facing install/readiness doctor exposed as `vidux doctor`. Hard-checks Python, token permissions, and config; reports source/package kind, source root/version/SHA/branch, cached-upstream distance, PATH target parity, and optional skill-mount parity. Optional GitHub, development-root, stale PID residue, and source-test capabilities warn without making a packaged install fail. `--json` emits the structured seven-check result. |
| `scripts/vidux-doctor.sh` | Runtime health checks for plans, worktrees, automations, browser processes, and Codex state. |
| `scripts/vidux-http-smoke.py` | Observe-only HTTP smoke helper for local monitor budgets. Classifies fast responses `pass`, byte-streaming-then-timeout `warn_partial`, zero-byte budget timeouts `fail_budget`, keeping only a bounded response sample so probes never dump full HTML or huge JSON into evidence. JSON `ok` follows hard-fail exit status; `strict_ok` is false when any warning is present. `--timeout` must be > 0; `--max-sample-bytes` must be ≥ 0. |
| `scripts/vidux-test-all.sh` | Comprehensive self-test harness for contract tests and related checks. |
| `scripts/vidux-worktree-gc.py` | Read-only by default. Classifies worktrees (`primary`, `open_pr`, `merged_clean`, `dirty`, `closed_unmerged`, `unmerged_no_pr`, `unknown`); `open_pr` can be found by branch name or by a detached checkout whose `HEAD` matches a PR head SHA. Emits a top-level `cleanup_decision` (`guarded_removal_available`, `owner_approval_required_before_apply`, `cleanup_approval_status`), `owner_review_items` (`commits_not_in_base`, `last_commit_subject`/`date`/`age_days`, safe `review_command`), and `safe_cleanup_items` for exact `merged_clean` rows with `cleanup_approval_status=required_before_apply`. `--owner-review-markdown` prints an owner-review packet. With owner approval, `--apply --yes` removes only `merged_clean` worktrees and protects both the primary and invocation checkouts. |

### Doctor split

Use `vidux doctor` when a human or terminal lane needs local CLI readiness:
Python version, optional GitHub auth, token permissions, local config, stale
browser pidfile state, install identity/link truth, and the source contract
bundle when present. Install truth distinguishes a normal checkout, Git
worktree (`.git` file), and packaged install; names the resolved source root,
version, short SHA, and branch; and compares `HEAD` with cached `origin/HEAD`
(falling back to cached `origin/main`). It never fetches or repairs, so its
ahead/behind result is explicitly a cached-ref observation. Ahead is reported
without treating a source-under-test as stale; detached/pinned, behind,
diverged, missing-PATH, and different-source link states warn.

The PATH executable and any present common mounts
(`~/.claude/skills/vidux`, `~/.codex/skills/vidux`,
`~/.agents/skills/vidux`, `~/.ai/skills-active/vidux`, and
`~/.ai/skills-active-dir/vidux`) must resolve to the same source root. Missing
optional mounts pass, which keeps CLI-only and packaged installs valid. Stale
dead/empty/malformed browser PID residue is a warning and is never removed by
the doctor. Use `vidux doctor --json` for per-surface structured state while
keeping this install doctor separate from runtime health.

The install doctor may run `npm test`, so set
`VIDUX_DOCTOR_SKIP_NPM_TEST=1` only in fast loops with a separate test gate.
The install doctor exits `0` when no hard check fails (optional warnings may
remain), `1` when a hard check fails, and `2` for invalid usage.

Use `scripts/vidux-doctor.sh --json` when a hook or monitor needs runtime
health: plans, worktrees, automations, browser processes, Codex state. Read-only
by default and JSON-friendly — the beforeTask/pre-hook probe.
`scripts/vidux-doctor.sh --fix` is an explicit cleanup path; NEVER wire it into
automatic pre-hook checks. Orphan automation cleanup stays `warn` when safety
rules retain a directory instead of deleting it.

The runtime doctor keeps macOS memory fields source-specific: `memory_pressure -Q`
reports `memory_pressure_free_pct`; raw page-derived MB from `vm_stat` reports
`vm_free_mb` and `vm_speculative_mb`. Legacy aliases remain in JSON for existing
consumers.

The runtime doctor's `schedulewakeup_doctrine_intact` check verifies the
`CronCreate` > `ScheduleWakeup` for ≥10 fires rule is still stated in both
canonical locations (`guides/automation.md`, `docs/fleet/claude-lifecycle.md`).
This catches silent doctrine drift, not a live violation — vidux cannot observe
a running session's actual `ScheduleWakeup` tool calls.

## Codex maintenance scripts

| Script | Purpose |
|---|---|

## Support libraries in `scripts/lib/`

| Library | Purpose |
|---|---|
| `codex-db.sh` | Safe Codex database read/write helpers. |
| `compat.sh` | Portable wrappers for OS-specific `stat` and `date` behavior. |
| `ledger-config.sh` | Ledger path discovery from env vars and config. |
| `ledger-emit.sh` | Emit vidux events into the shared ledger. |
| `ledger-query.sh` | Fleet analysis queries over ledger data. |
| `queue-jsonl.sh` | Experimental derived JSONL queue helpers alongside `PLAN.md`; `PLAN.md` remains the queue/planning authority and publish ledger rows carry shipped-cycle proof/resume. |
| `resolve-plan-store.sh` | Resolve the configured plan store path. |

## How to navigate the directory

- Start with the header comment in each script — purpose and usage sit at the top of the file.
- `scripts/vidux-worktree-gc.py` is covered by `tests/test_worktree_gc.py`, run locally via `npm run test:py` (GitHub Actions test execution is disabled repo-wide; see `.github/workflows/test.yml`).
- Use [Configuration](/reference/config) when a script reads defaults from `vidux.config.json`.
- Use [Hooks](/reference/hooks) if you want lightweight git-based enforcement instead of a full automation lane.
