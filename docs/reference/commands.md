# Entrypoints and CLI Reference

Vidux ships one discoverable skill surface: root `SKILL.md`. Loading `/vidux`
activates that plan/proof/resume contract. Historical `commands/` wrappers were
removed because recursive plugin discovery exposed them as competing skills.

The read-only status board remains available as `vidux status`; it is a shell
CLI subcommand, not a second `/vidux-status` skill.

## Root `/vidux` skill

Root `SKILL.md` owns the plan-first cycle. On activation it should:

1. Read repo instructions, the selected planning authority, current git state,
   and the smallest relevant proof surface.
2. Resolve config with `python3 scripts/vidux-config.py check --json`, keeping
   a missing live config distinct from the checked-in example fallback.
3. Resume `in_progress` work before choosing the highest-impact reachable row.
4. Verify mechanically, then record the plan and publish-ledger breadcrumbs
   needed for another session or agent to resume.

## Shell CLI

`bin/vidux` exposes helper subcommands that back the discipline:

- `vidux status [--root <path>] [--focus <repo>...] [--all] [--json]` renders
  task counts, progress, remaining `[ETA: Xh]` hours, and last activity across
  operational plans. Default output hides empty and fully shipped plans.
- `vidux init --here` is the canonical first-run path and creates a
  cockpit-ready `PLAN.md` in the current project. The compatibility form
  `vidux init <slug>` requires `--plan-store <path>`, `VIDUX_PLAN_STORE`, or a
  live config with a persistent plan-store path outside the Vidux install.
  Both refuse to overwrite and start with an explicit unproven result.
- `vidux browse` starts the local cockpit (see [Browser](/reference/browser)).
- `python3 scripts/vidux-config.py path|check|show|init` resolves and validates
  the local XDG user config, falling back to the package's read-only
  `vidux.config.example.json` unless `--strict` is used. A checkout-local config
  is read only when selected with `--config` or `VIDUX_CONFIG`. JSON output
  preserves the redacted source, path, plan-store, external-root, and issue
  projection used by operator checks.
- `vidux doctor` runs local toolchain, optional auth, stale pidfile, config,
  and source-test checks as an install/readiness gate. Packaged installs warn
  when source-only or optional capabilities are unavailable. Use `scripts/vidux-doctor.sh --json`
  for hook-safe runtime checks across plans, worktrees, automations, browser
  processes, and Codex state. Exit codes are `0` when no hard check fails,
  `1` for hard failures, and `2` for invalid usage.

Signposts are local smoke/profiler events, not product analytics.

## Related references

- Read [PLAN.md Field Reference](/reference/plan-fields) for the state that root `/vidux` consumes.
- Read [Prompt Template](/reference/prompt-template) for the prompt shape a lane uses each fire.
- Read [Configuration](/reference/config) for the plan-store settings consumed by the root skill and CLI.
