# Hooks Reference

Vidux ships three optional git hooks in `hooks/`, plus `hooks/hooks-reference.json` — a source-grounded manifest mapping those scripts and two task-lifecycle helpers into higher-level hook events.

This file used to live at `hooks/hooks.json`, a path
Claude Code's plugin loader auto-scans and validates as real, loadable
plugin-hook config. Its event names (`pre-commit`, `post-commit`,
`post-build-failure`, `beforeTask`, `afterTask`) are git/task concepts this
repo invented for cross-tool documentation, not actual Claude Code hook
lifecycle events -- `claude plugin validate` correctly rejected the shape,
and no reshape would have made it functionally real. Renamed to
`hooks-reference.json` so it's read as the example manifest it always was,
without colliding with the plugin loader's reserved filename.

## Git hooks

| Hook | Behavior |
|---|---|
| `hooks/pre-commit-plan-check.sh` | Blocks a commit when code changes are staged but the repo has no active or pending task in `PLAN.md`. |
| `hooks/post-commit-checkpoint.sh` | Prints a reminder if `PLAN.md` has no progress entry for the current day. |
| `hooks/three-strike-gate.sh` | Warns after repeated `fix` or `retry` commits so the operator can step up an abstraction level. |

## Installation

Hook installs and wiring changes are publish/change cycles. Before copying or
enabling a hook in a target repo, update that repo's owning `PLAN.md` and emit
an `--event publish` row (via your configured ledger emitter — see SKILL.md §
Push authorization; `scripts/lib/ledger-emit.sh` is a sourced-only function
library, not this CLI) with:

- `--repo-path` — the target repo.
- `--summary` — non-empty, naming the hook install/change.
- `--task-id` — owning plan row/task id, matching a checkbox/FSM row in `--plan-path`.
- `--plan-path` — the target repo's existing owning `PLAN.md`.
- `--proof` — the syntax check, dry-run, or install verification.
- `--handoff-status` — `done` for a complete install, `needs_review` when copied but not yet verified.
- `--resume` — next command, repo, or blocker for the next agent.
- `--file` — each changed path; path-like values that exist or are git-known deletions. Pre-copy packet: the updated `PLAN.md` is the changed file. Final `done` packets can name `.git/hooks/...` paths after they exist.
- `--claim` — every `--file` entry plus any owning plan or hook wiring file the next agent must inspect; path-like, resolving to existing paths or git-known deletions.

```bash
# "$LEDGER_EMIT" is your own configured ledger-emit executable (wired via
# `vidux-release.sh --ledger-emit <path>` or the LEDGER_EMIT env var) --
# scripts/lib/ledger-emit.sh is a sourced-only function library, not a
# --event-flag CLI.
"$LEDGER_EMIT" \
  --event publish \
  --repo-path /path/to/your/project \
  --lane hook-install \
  --task-id hook-install \
  --plan-path /path/to/your/project/PLAN.md \
  --proof "hook install dry-run / shell syntax passed" \
  --handoff-status needs_review \
  --resume "copy hooks, verify installed hook paths exist, then emit final done row" \
  --file /path/to/your/project/PLAN.md \
  --claim /path/to/your/project/PLAN.md \
  --skills vidux \
  --summary "Planned Vidux planning hook install"

cp hooks/pre-commit-plan-check.sh /path/to/your/project/.git/hooks/pre-commit
cp hooks/post-commit-checkpoint.sh /path/to/your/project/.git/hooks/post-commit
cp hooks/three-strike-gate.sh /path/to/your/project/.git/hooks/
```

## Hook manifest

`hooks/hooks-reference.json` is the repo's checked-in example for app-level hook wiring. It currently declares five entries:

| Manifest entry | Event | Script |
|---|---|---|
| `vidux-pre-commit` | `pre-commit` | `hooks/pre-commit-plan-check.sh` |
| `vidux-checkpoint` | `post-commit` | `hooks/post-commit-checkpoint.sh` |
| `vidux-three-strike` | `post-build-failure` | `hooks/three-strike-gate.sh` |
| `vidux-before-task` | `beforeTask` | `scripts/vidux-doctor.sh --json` |
| `vidux-after-task` | `afterTask` | `scripts/vidux-checkpoint.sh` |

These are examples, not auto-installed defaults. In the shipped manifest, `vidux-before-task` is a non-blocking runtime health check that runs `scripts/vidux-doctor.sh --json`, not `vidux doctor`. The runtime doctor is read-only by default and JSON-friendly for hook probes; `vidux doctor` is the terminal install/readiness doctor and may be slow when it runs `npm test`. `vidux-after-task` is illustrative, not plug-and-play: raw `scripts/vidux-checkpoint.sh` exits with usage unless it receives `--archive` or `<plan-path> <task> <summary>` (plus optional flags), so a real app hook needs a wrapper that supplies those arguments.

## Behavior notes

- `pre-commit-plan-check.sh` allows doc-only and plan-only commits through.
- `post-commit-checkpoint.sh` is advisory. It prints a reminder and does not block.
- `three-strike-gate.sh` is also advisory. It prints escalation guidance and exits cleanly.
- `hooks/hooks-reference.json` is a source-grounded example manifest, not an auto-installer or full hook runner.

## Runtime attribution

Runtime attribution for spawned workers comes from `VIDUX_RUNTIME` when set,
otherwise from local session environment variables such as `CLAUDE_SESSION_ID`,
`CURSOR_SESSION_ID`, and `CODEX_SESSION_ID`. Use `VIDUX_RUNTIME=claude` or
`VIDUX_RUNTIME=cursor` for spawned workers that inherit an ambient Codex thread
environment.

## When to use hooks

Hooks fit when you want a local nudge without running a scheduled lane:

- Use the pre-commit hook to catch planless code changes.
- Use the post-commit hook to keep progress logging from drifting.
- Use the three-strike helper when a surface is attracting repeated low-confidence retries.

## Related references

- Read [PLAN.md Field Reference](/reference/plan-fields) to understand what the pre-commit hook is looking for.
- Read [Scripts](/reference/scripts) for the heavier command-line helpers that complement these hooks.
- Read `ENFORCEMENT.md` when you need the prompt-hook examples for Claude Code session wiring.
