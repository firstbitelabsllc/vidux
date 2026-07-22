# Vidux Recipes

Opt-in tactics and patterns. Core vidux (`SKILL.md`) is the opinionated machinery — the five principles, the cycle, PLAN.md, investigations. These recipes are everything else: customizations, tool-specific setups, prompt patterns, workflows.

Load a specific recipe on demand. Don't load them all upfront.

## How to use

- Read a recipe when its trigger matches your current work
- Copy patterns or rules directly into your own files
- Recipes are versioned with the repo; they evolve

## Catalog

### Tacit knowledge (general)

- [claude-md-rules.md](claude-md-rules.md) — Rules to drop into your `CLAUDE.md` / `AGENTS.md`
- [lane-prompt-patterns.md](lane-prompt-patterns.md) — 8-block structure for automation lane prompts

### Delegation

- [subagent-delegation.md](subagent-delegation.md) — Same-tool Mode A / Mode B via `Agent()`
- [codex-runtime.md](codex-runtime.md) — Running vidux natively on Codex Desktop

### Workflow friction (from /insights findings)

- [user-value-triage.md](user-value-triage.md) — Stop shipping audit PRs when user bugs exist
- [evidence-discipline.md](evidence-discipline.md) — No attribution without evidence
- [env-var-forensics.md](env-var-forensics.md) — Systematic env-var source hunt
- [webfetch-fallback.md](webfetch-fallback.md) — Recognize and route around JS-rendered / auth-gated pages
- [proactive-surfacing.md](proactive-surfacing.md) — Scan for work before declaring idle; surface stale intents
- [lightweight-first.md](lightweight-first.md) — Direct answers for simple creative asks
- [visual-proof-required.md](visual-proof-required.md) — UI work needs a screenshot, not a green test
- [the-rip-pattern.md](the-rip-pattern.md) — When a surface gets bloated, rip the default route and re-promote features only when they are actually requested
- [lane-prompt-mirror.md](lane-prompt-mirror.md) — Mirror live `~/.vidux/lanes/<lane>/prompt.md` directives into the consuming repo so they survive rebuilds and cross-machine installs

## Adding a recipe

A recipe earns its place when:

1. The problem is recurring (not a one-off)
2. The solution is non-obvious (not "read the docs")
3. Copy-pasting the recipe saves re-discovery time

Recipes that fail these criteria belong in a skill, a doc, or nowhere.
