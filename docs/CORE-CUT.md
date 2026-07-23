# Vidux core cut — handoff

**Date:** 2026-07-22  
**Branch:** `docs/root-readme-cut` (checkout: `vidux-main-active`)  
**Repo:** `firstbitelabsllc/vidux` (public)  
**Hard rail:** **no public push/PR without Leo yes.** Local commit OK. Private `ai-leo` dossier wording may push separately.

## One product, not two

Vidux **is** the public core. There is **no** second “public cut” product, no overlay package inside this repo, and no “thin fork” story.

| Concept | Where it lives |
|---|---|
| **Vidux (this repo)** | Plan/proof/resume control plane: CLI, browser, SKILL, doctrine essays, guides |
| **Private overlay** | **Pilot-Leo** and `*-leo` skills beside Pilot — **private `ai-leo`**, not a folder under Vidux |
| **Missions / PLANs** | e.g. recognition-mission, bakeoffs — **private `ai-leo/vidux/`**, not shipped with Vidux |
| **Legacy** | `vidux-legacy-private` — out of scope |

Kill language: “private monorepo with thin public cut,” “overlay product,” “cruft fork.”

---

## Keep / move / kill table

### KEEP at package root (agent + install surface)

| Path | Why |
|---|---|
| `bin/` (`vidux`, `vidux-browse`) | CLI entry |
| `browser/` (server + static needed to run) | Cockpit |
| `SKILL.md` | Agent entry (stays root) |
| `LICENSE` | Legal |
| `CHANGELOG.md`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md` | Community |
| `VERSION`, `vidux.config.example.json` | Runtime contract |
| `package.json` / `files` | Publish surface |
| `scripts/` needed by CLI doctor/init/status/browse | Runtime |
| `hooks/` | Optional enforcement wiring |
| `guides/` needed for init/status/browse/doctor | Operator |
| `docs/**` (incl. doctrine essays + CORE-CUT) | Docs site + long form |
| `references/` | JIT deep docs |
| `examples/` | Init templates |
| `.claude-plugin/`, `.claude/settings.json` | Plugin install |

### MOVE (this cut — done on branch)

| From root | To |
|---|---|
| `ARCHITECTURE.md` | `docs/doctrine/ARCHITECTURE.md` |
| `DOCTRINE.md` | `docs/doctrine/DOCTRINE.md` |
| `LOOP.md` | `docs/doctrine/LOOP.md` |
| `ENFORCEMENT.md` | `docs/doctrine/ENFORCEMENT.md` |
| `INGREDIENTS.md` | `docs/doctrine/INGREDIENTS.md` |
| `WRITING-STYLE.md` | `docs/doctrine/WRITING-STYLE.md` |

Essays **stay in-tree**; they leave the **root agent path** so install + SKILL stay short.

### KEEP (call) — root `PLAN.md`

| Path | Call |
|---|---|
| `PLAN.md` | **Stay at root** as *this repo’s* internal authority queue (contributors/agents working on Vidux itself). **Not** required for consumers who only `vidux init` in their app. Do not ship as “user product surface” in README primary path. |

### KILL (language / non-goals — not necessarily delete from disk elsewhere)

| Item | Action |
|---|---|
| “Public cut” / “thin cut of private monorepo” | **Kill wording** in dossier/market (private ai-leo) |
| Pilot-Leo / `*-leo` inside Vidux | **Never land here** — private only |
| ai-leo recognition/bakeoff PLANs | **Never land here** |
| Second product name for the same core | **Do not invent** |
| Root doctrine files in `package.json` `files` | **Removed** (covered by `docs/**/*.md`) |

### OUT OF SCOPE this PR

| Item | Notes |
|---|---|
| Deleting guides cruft beyond link fixups | Later diet PR |
| npm publish / GitHub Release | Separate |
| History rewrite / public force-push | Hard rail |
| Moving SKILL.md under docs/ | No — agents expect root skill |

---

## What this branch changes (finish list)

- [x] `git mv` six doctrine essays → `docs/doctrine/`
- [x] README install-first; docs table points at `docs/doctrine/*`
- [x] `package.json` `files`: drop root doctrine filenames; keep `docs/**/*.md` + LICENSE
- [x] `SKILL.md` JIT list → `docs/doctrine/…`
- [x] Link fixups: installation, hooks, CONTRIBUTING, ARCHITECTURE layout
- [x] This handoff: `docs/CORE-CUT.md`
- [ ] **Leo:** open PR / push to public `origin` when ready

---

## Verify commands (run from repo root)

```bash
# 1) Root is not a doctrine landfill
test ! -f DOCTRINE.md && test ! -f LOOP.md && test ! -f ARCHITECTURE.md
test -f docs/doctrine/DOCTRINE.md && test -f docs/doctrine/LOOP.md

# 2) package.json does not list root doctrine files
! grep -E '"(ARCHITECTURE|DOCTRINE|ENFORCEMENT|INGREDIENTS|LOOP|WRITING-STYLE)\.md"' package.json

# 3) SKILL JIT points under docs/doctrine
grep -q 'docs/doctrine/DOCTRINE.md' SKILL.md

# 4) README points at doctrine paths
grep -q 'docs/doctrine/ARCHITECTURE.md' README.md

# 5) Public-ready + unit gates (local)
npm run public-ready:grep
npm test   # or: npm run test:py && npm run test:js

# 6) Optional full verify
npm run verify
```

Expected: all path tests pass; public-ready/grep and unit tests green on a clean tree.

---

## Suggested PR title / body (for Leo)

**Title:** `docs: root install cut — doctrine essays under docs/doctrine`

**Body:**  
Vidux remains one product (the core). Root is install + SKILL + community. Long doctrine essays move to `docs/doctrine/`. `package.json` `files` no longer lists root doctrine names. No Pilot-Leo, no private missions. See `docs/CORE-CUT.md`.

---

## Private follow-ups (ai-leo, not this repo)

- Patch DOSSIER/market lines that still say “vidux public cut / private monorepo extract”
- Recognition/bakeoff language: Vidux = public control plane; private work lives in ai-leo

---

## Resume

| If | Then |
|---|---|
| Branch uncommitted | commit on `docs/root-readme-cut` locally |
| Leo says ship | push branch + open PR to `firstbitelabsllc/vidux` main |
| Links still break | `rg -n 'DOCTRINE\.md|ENFORCEMENT\.md' --glob '!docs/doctrine/**'` and fix |
