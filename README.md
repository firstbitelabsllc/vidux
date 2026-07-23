<p align="center">
  <img src="assets/vidux-banner.svg" alt="Vidux — plan first, code second" width="100%" />
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/firstbitelabsllc/vidux?style=flat" alt="MIT license" /></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9 or newer" />
</p>

# Vidux

A coding agent loses everything when its session ends. Vidux keeps the
recovery packet in plain repository files — a `PLAN.md` holding priorities and
decisions, evidence stored next to the work, and a checkpoint naming the exact
next action — so the next run resumes where the last one stopped, whether
that's the same agent, a different tool, or you a week later.

Reach for it when the work will outlive one session. Skip it for a quick fix.

## Quick start

Vidux is an agent skill — your agent drives it; you rarely type vidux commands
yourself.

```bash
git clone https://github.com/firstbitelabsllc/vidux.git ~/Development/vidux  # any path works
mkdir -p "$HOME/.claude/skills"
ln -sfn "$HOME/Development/vidux" "$HOME/.claude/skills/vidux"               # point at your clone
```

Claude Code is the tested host. Any agent that can read [SKILL.md](SKILL.md)
and plain files can follow the same contract; other hosts are untested.

Then, in any project, two entry points:

- **`/vidux "what you're working on"`** — the first cycle scaffolds `PLAN.md`,
  gathers evidence, and fills it in. No code until the plan is ready.
- **"open the vidux dashboard"** — starts the local cockpit at
  `http://127.0.0.1:7191`.

Requirements: Bash, Git, Python 3.9 or newer. No service, database, account,
or API key. Details: [Installation](docs/guide/installation.md) ·
[Quickstart](docs/guide/quickstart.md).

Inside a project Vidux writes plain files only — `PLAN.md` and the evidence
next to the work — yours to commit or gitignore. Deleting the symlink
uninstalls the skill. Here is what a run leaves behind:

```markdown
## Tasks
- [completed]   Extract auth middleware   [Evidence: PR #41]
- [in_progress] Migrate sessions table    [Evidence: migrations/012]
- [blocked]     Cut over login route      [Blocker: sessions backfill]

## Progress
- [2026-07-22] Backfill at 80%. Next: verify row counts, then unblock cutover.
```

Kill that session mid-migration and nothing is lost: the next run — any tool —
reads `PLAN.md` and starts at "verify row counts".

<p align="center">
  <img src="assets/vidux-dashboard.png" alt="The vidux dashboard showing a demo plan: goal, next step, a scorecard measure marked in progress with proof still missing, and cross-project resume queues" width="900" />
</p>

The board refuses to trust prose: a measure without an attached artifact shows
`PROOF MISSING` until one exists. It scans your dev root (default
`~/Development`, configurable) for plans, and it binds to loopback only by
default — read [the browser reference](docs/reference/browser.md) before
binding wider.

## How it works

Every run is the same loop — READ → ASSESS → ACT → VERIFY → CHECKPOINT — and
the state lives in files git already tracks, committed like any other change;
chat history is never the authority. The depth lives in the docs:
[the cycle](docs/concepts/cycle.md) ·
[plan structure](docs/concepts/plan-structure.md) ·
[CLI](docs/reference/commands.md).

The skill shells out to a small CLI (`init`, `status`, `browse`, `doctor`) you
can also run directly — [Installation](docs/guide/installation.md) covers
putting it on PATH.

## Where Vidux stops

Vidux does not schedule agents, route models, execute workers, or hold
provider credentials — your coding host does all of that. Vidux can record
provider-neutral claims for concurrent work, but it never launches a provider
or selects a model. The dashboard is a local view, not a hosted service. The
value is durable recovery, not raw speed.

## Release truth and contributing

Vidux installs from source; there is no npm package on the registry, though
[Installation](docs/guide/installation.md) covers an optional locally-built
tarball. The Node toolchain is only used by the test suite. Start with
[ARCHITECTURE.md](ARCHITECTURE.md) and [CONTRIBUTING.md](CONTRIBUTING.md).
MIT licensed.
