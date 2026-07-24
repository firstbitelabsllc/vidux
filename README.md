# Vidux

Plan-first control plane for AI coding work that spans sessions, agents, or days.

One `PLAN.md` holds the queue, decisions, and progress. Agents read it, do one
task, write proof, and exit. Chat is not the control plane.

## Install

Needs Bash, Git, and Python 3. Node is only for contributor tests and docs.

```bash
git clone https://github.com/firstbitelabsllc/vidux.git
cd vidux
mkdir -p "$HOME/.local/bin"
ln -sfn "$(pwd)/bin/vidux" "$HOME/.local/bin/vidux"
export PATH="$HOME/.local/bin:$PATH"
vidux doctor
```

## Quick start

```bash
cd /path/to/your/project
vidux init --here    # creates PLAN.md only if missing
vidux status
vidux browse         # local cockpit (loopback by default)
```

`vidux status` scans `VIDUX_DEV_ROOT` (default `~/Development`). If that directory is missing, it warns and still shows the `PLAN.md` in your current directory.

`vidux help <command>` for options. Config lives at
`~/.config/vidux/vidux.config.json` — see
[`vidux.config.example.json`](vidux.config.example.json).

The cockpit binds to loopback by default and scans your dev root (default
`~/Development`, configurable) for plans; a measure with no attached artifact
shows `PROOF MISSING` until one exists.

## Agent skill

Root [`SKILL.md`](SKILL.md) is the agent entry. Claude Code:

```bash
ln -sfn /path/to/vidux "$HOME/.claude/skills/vidux"
# or: claude --plugin-dir /path/to/vidux
```

Claude Code is the tested host. Any agent that can read [`SKILL.md`](SKILL.md)
and plain files can follow the same contract; other hosts are untested.

## Where Vidux stops

Vidux does not schedule agents, route models, execute workers, or hold
provider credentials; your coding host does all of that. Vidux can record
provider-neutral claims for concurrent work, but it never launches a provider
or selects a model. The dashboard is a local view, not a hosted service.

## Docs

Root is install + agent entry. Doctrine essays live under `docs/doctrine/` (not a second product).

| Doc | Path |
| --- | --- |
| Architecture | [`docs/doctrine/ARCHITECTURE.md`](docs/doctrine/ARCHITECTURE.md) |
| Doctrine | [`docs/doctrine/DOCTRINE.md`](docs/doctrine/DOCTRINE.md) |
| Loop | [`docs/doctrine/LOOP.md`](docs/doctrine/LOOP.md) |
| Enforcement hooks | [`docs/doctrine/ENFORCEMENT.md`](docs/doctrine/ENFORCEMENT.md) |
| Core-cut handoff | [`docs/CORE-CUT.md`](docs/CORE-CUT.md) |
| Evidence format | [`guides/evidence-format.md`](guides/evidence-format.md) |
| Site / guides | [`docs/`](docs/) |

Community: [CONTRIBUTING](CONTRIBUTING.md) · [SECURITY](SECURITY.md) · [SUPPORT](SUPPORT.md) · [CODE_OF_CONDUCT](CODE_OF_CONDUCT.md)

Repo `PLAN.md` (if present) is **this repo’s** internal queue — not required to use Vidux in your project.

## Release truth

Version `1.0.2` is the current source contract (`VERSION` + matching git tag).
Vidux installs from source — there is no npm registry package. Prefer the
tagged tip:

```bash
git clone https://github.com/firstbitelabsllc/vidux.git
cd vidux && git checkout v1.0.2
```

Or track `main` for the latest. Release notes:
[v1.0.2](https://github.com/firstbitelabsllc/vidux/releases/tag/v1.0.2).
The Node toolchain is only used by contributor tests.

## Contributing

```bash
npm ci
npm run verify
```

MIT licensed.
