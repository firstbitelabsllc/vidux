# Installation

Vidux has two compatible install surfaces: a source checkout for contributors
and skill development, or an optional locally-built tarball (`npm pack`) for a
global CLI and local browser. There is no npm package on the registry. Both
surfaces expose the same plan-first runtime.

## Prerequisites

- Bash
- Python 3.9+
- Git for a source checkout
- Node 20+ and npm for a tarball install or maintainer verification
- [Claude Code](https://claude.ai/code) only when using Vidux as a slash-command skill

## Install from a source checkout

```bash
git clone https://github.com/firstbitelabsllc/vidux.git ~/Development/vidux
mkdir -p "$HOME/.local/bin"
ln -sfn "$HOME/Development/vidux/bin/vidux" "$HOME/.local/bin/vidux"
export PATH="$HOME/.local/bin:$PATH"   # add to your shell profile to keep it
vidux --version
```

Any directory on `PATH` works; `~/.local/bin` avoids needing `sudo`. The CLI
self-locates through the symlink, so the checkout can live anywhere.

## Install a verified tarball

From a trusted source checkout:

```bash
npm run release:verify
TARBALL="$(npm pack --ignore-scripts --silent)"
npm install --global "./${TARBALL}"
vidux --version
```

The package root is treated as immutable. Live config belongs at
`$XDG_CONFIG_HOME/vidux/vidux.config.json` (or
`~/.config/vidux/vidux.config.json`), and project plans belong in their owning
repositories. Upgrades therefore cannot erase either one.

The release verifier builds the artifact twice and requires byte-identical
SHA-256 output, exact version agreement, required runtime files, tracked-only
contents, and bounded size. Local plans, evidence, evaluations, tests, and
generated state are excluded.

## Install the Claude Code skill

```bash
ln -sfn /path/to/vidux ~/.claude/skills/vidux
```

Replace `/path/to/vidux` with your clone path. `/vidux` is then a slash command in any Claude Code session.

## Optional: Git Hooks

Vidux ships enforcement hooks that catch planning failures at commit time. Optional; recommended for teams or long-running projects.

Treat installing or rewiring hooks as a publish/change cycle in the **target project**. Before copying or enabling hooks:

1. Update the target repo's owning `PLAN.md` (Progress/Tasks/Drift Log) with what is changing, proof, `handoff_status`, files claimed, next-agent resume.
2. Emit a publish ledger row for the target repo with the summary, task id that matches the plan row, existing owning `PLAN.md` path, proof, handoff status, next-agent resume, path-like existing/git-known changed file, and matching claim coverage. Pre-copy packet: use the updated `PLAN.md` as both `--file` and `--claim`. After copying and verifying hooks, emit the final `done` row with copied hook paths once they exist.

```bash
# "$LEDGER_EMIT" is your own configured ledger-emit executable (wired via
# `vidux-release.sh --ledger-emit <path>` or the LEDGER_EMIT env var) --
# scripts/lib/ledger-emit.sh is a sourced-only function library, not a
# --event-flag CLI. No emitter configured means this row is skipped by
# design, not a failure.
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
```

Then copy the hooks into your **target project's** `.git/hooks/` directory (not the vidux repo itself):

```bash
cp hooks/pre-commit-plan-check.sh /path/to/your/project/.git/hooks/pre-commit
cp hooks/post-commit-checkpoint.sh /path/to/your/project/.git/hooks/post-commit
cp hooks/three-strike-gate.sh /path/to/your/project/.git/hooks/
```

| Hook | What it checks |
|------|---------------|
| `pre-commit-plan-check.sh` | Blocks staged non-markdown code changes when `PLAN.md` has no active or pending task. |
| `post-commit-checkpoint.sh` | Prints a reminder when `PLAN.md` has no progress entry for today. |
| `three-strike-gate.sh` | Warns after 3 recent `fix` / `retry` / `attempt` commits so you step up an abstraction level. |

## Optional: Claude Code Enforcement Hooks

For stronger enforcement within Claude Code sessions, add the hooks from [`enforcement.md`](../reference/enforcement.md) to your `settings.local.json`. They:

- Gate file edits: require a PLAN.md entry before writing code
- Detect drift: flag file changes that don't match the active plan task
- Enforce checkpoints: require the owning plan/progress update and publish-ledger packet before publishable work exits
- Resume protocol: prompt plan re-read on session start

The repo ships `hooks/hooks-reference.json` as a checked-in example manifest: it wraps the three git hooks above plus `beforeTask` / `afterTask` entries pointing at `scripts/vidux-doctor.sh --json` and `scripts/vidux-checkpoint.sh`.

`vidux-before-task` runs as shown. `vidux-after-task` is illustrative, not zero-config: raw `scripts/vidux-checkpoint.sh` expects `<plan-path> <task> <summary>` (plus optional flags) or `--archive`, so an app-level `afterTask` hook needs a wrapper that supplies those arguments.

See [Hooks Reference](/reference/hooks) for the full configuration.

## Verifying Installation

Verify the CLI and browser first:

```bash
vidux --version
vidux doctor
cd /path/to/your/project
vidux init --here
vidux browse --no-open
```

`vidux init --here` is the canonical onboarding path. The older
`vidux init <slug>` form is available only with an explicit persistent plan
store outside the package root; see [Configuration](/reference/config).

`vidux doctor` reports optional GitHub/source-checkout capabilities as warnings
in a packaged install; warnings do not hide hard Python, config, token-permission,
or stale-runtime failures. One check runs the contract self-test (`npm test`): on
a fresh clone that has not run `npm ci`, that line is red because the dev test
environment is unset, not because the install is broken — the runtime is Bash,
Git, and Python only.

For the optional Claude Code skill, open a session and run:

```
/vidux "test project"
```

If installed correctly, the agent reads the skill, loads the XDG user config
when present, resolves the authority plan store, then drafts or resumes the
authoritative `PLAN.md` before executing the stateless cycle.

## Ecosystem Skills

Vidux is a **single entry point** — `/vidux` — covering both planning and automation. As of 2026-04-17, previously separate planning, automation, platform-specific, and fleet companion commands were merged into `/vidux` or pruned.

| Skill | What it does |
|---|---|
| `/vidux` | Full plan-first cycle (Part 1) + automation patterns (Part 2) — one entry point covers planning, lane bootstrap, delegation, session GC |

For deep automation details (session-gc internals, Codex shim registration, PR lifecycle nursing, cross-fleet coordination), `/vidux` reads `references/automation.md` on demand.

See [Commands Reference](/reference/commands).
