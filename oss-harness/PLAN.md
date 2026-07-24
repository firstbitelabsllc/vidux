# OSS Track — Shared Goal Queue

Shared multi-agent home for the open-source portfolio goal (moved here from
the private authority 2026-07-23 so any agent seat — Claude Code, Cursor,
Codex — can work the same goal). Full campaign history and private-repo
verdicts stay in the private authority at
`~/Development/ai-leo/vidux/oss-harness/PLAN.md`: read it locally; never copy
private content into this public file.

## Goal

`GOAL.md` next door is the paste-ready pointer. Standing rails: M1
delegate-first, M2 never-stop/all-boats-rise, own-row claims, ref-fresh reads,
pathspec commits. Quality bar for already-public amplify: stranger-test
(sandboxed HOME, README verbatim) green, CI/suite green, zero private content.
New `gh repo create` / publicize / visibility flips stay per-instance
Leo-gated unless a row explicitly authorizes (voice + skillbox remain gated).

### Seat mix (do not forget)

Target share of **agent-reachable wave work** (parent still accepts; hard
rails unchanged):

| Share | Seat | Use for |
| --- | --- | --- |
| ~60% | **GLM** (`glm-max` via Pilot/Delegate → `opencode … zai/glm-5.2 --variant max`) | Bounded implementation drafts / mechanical amplify |
| ~30% | **Sol / Codex** (Sol hard IC; Codex for first-party build+proof) | Hard, well-bounded build+proof slices — assign PROACTIVELY by task-class up front (Leo 2026-07-23 "defer to Sol"), not only after a named miss. Sol never orchestrates. |
| ~10% | **Cursor Grok max** | Adversarial review, integration/debug, loop steward when GLM/Sol unavailable |

Grok must not monopolize consecutive waves when GLM or Sol is healthy. Claim
rows with the seat that will do the work (`claimed: glm-max …`,
`claimed: sol …`, `claimed: cursor-grok-4.5 …`). If GLM/Sol is down, record
the miss and continue on the next healthy seat — do not invent Claude-compatible
GLM shims.

## Rows

- [completed] vidux README overhaul — 30-persona panel, verdict trims landed
  (`7a3204bd`), CI + secret-scan green. 2026-07-23.
- [completed] claudux wave — PRs #119/#120/#123/#124 merged: real-run terminal
  demo + shorter README, install-ref pinning, project.type validation,
  `--disallowedTools Bash` hardening, dead-ticker heartbeat fix (#122).
  Issue #121 CLOSED (dir3 merged; dirs 1–2 parked). 2026-07-23.
- [completed] skillbox — stranger-tested, silent-skip defect fixed (PR #1
  merged), release-ready agent-side; public flip human-gated. 2026-07-23.
- [parked: human gate] voice harness — staged complete agent-side; publish
  (public name, repo create, v0.1.0 tag) per-instance gated.
- [completed] Proactive research wave 1 (claude-code) — local-stt cluster:
  research + stranger-test DONE (37-agent recon, 27 findings verified 27/27,
  incl. a real `process.exit(1)` health-check crash + a missed ffmpeg spawn
  crash). PR delivery DELIBERATELY NOT PURSUED: ownership gate returned
  `viewerPermission: READ` / `viewerCanAdminister: false` — a third-party repo,
  not portfolio, so a fork+PR is Leo-gated (same third-party-peer class as
  clausona / media MCP, wave 2). Separately the drafted CI/test artifacts are
  non-landable as-is (critic-demonstrated: ts-jest never declared → CI red on
  first commit; C2/ffmpeg crashes unfixed). Reachable-win reclassification, not
  a shipped fix. Private receipt: ai-leo
  `evidence/wave1-local-stt-2026-07-23.md`. 2026-07-23.
- [completed] Proactive research wave 2 (cursor-grok-4.5) — council + probes:
  `everything` kill-from-shortlist (private grab-bag / CNA README);
  clausona + media MCP clones = third-party peers not portfolio; litty/fcp
  keep-private. Goal text realigned to quality-bar + create/visibility gate.
  Private receipt: ai-leo `evidence/wave2-council-2026-07-23.md`. 2026-07-23.
- [completed] Claudux #121 direction 3 (cursor-grok-4.5) — PR #125 MERGED;
  post-generation source-boundary guard fail-closed. Dirs 1–2 still
  design-parked. 2026-07-23.
- [completed] Proactive research wave 3 (cursor-grok-4.5) — skillbox scrub gate
  PR #2 MERGED; promote blocked on KEEP-PRIVATE / `*-leo`. No publicize.
  2026-07-23.
- [completed] Proactive research wave 4 (cursor-grok-4.5) — vidux doctrine cut PR #3
  MERGED; install-first README; doctrine under docs/doctrine/; cursoragent
  allowlisted on public-ready gate (fleet bot trailer class). 2026-07-23.
- [completed] Proactive research wave 5 (cursor-grok-4.5) — private keep/kill
  receipts: everything kill-from-shortlist; revolver kill-from-OSS; clausona
  peer-only; litty/fcp keep-private. Private: ai-leo
  `evidence/wave5-keep-kill-2026-07-23.md`. 2026-07-23.
- [completed] Proactive research wave 6 (cursor-grok-4.5) — stranger install
  found `vidux status` hard-fail without ~/Development; PR #4 MERGED.
  Private: ai-leo `evidence/wave6-vidux-stranger-2026-07-23.md`. 2026-07-23.
- [completed] Proactive research wave 7 (cursor-grok-4.5) — vidux#5 MERGED:
  status missing-dev-root warn/error → stderr so `--json` stdout stays parseable.
  2026-07-23.
- [completed] Proactive research wave 8 (cursor-grok-4.5) — skillbox scrub
  documented in README; PR https://github.com/leojkwan/skillbox/pull/3.
  No publicize. 2026-07-23.
- [completed] Proactive research wave 9 (claude-code) — claudux fresh e2e
  stranger-test at origin/main `866f853`, sandboxed HOME. Exercised the `update`
  backend path (the slice wave 16 deferred): install/check/help/serve/version all
  clean. Strongest candidate (update masks backend failure as exit 0) DISPROVEN —
  clean no-pipe run gave `TRUE_EXIT=127` correct propagation; the earlier rc=0
  was a `$?`-after-a-pipe read error. One sub-threshold cosmetic note (empty
  `--version` prints a green `✅ found:` line in check_claude/check_codex)
  recorded but NOT shipped — trigger only reproducible with a broken test-shim,
  self-corrects via the loud exit-127 troubleshooting path. Verdict: NO shippable
  defect; corroborates wave 16. Agent-reachable non-gated OSS surface
  (vidux/claudux/skillbox agent-side) has CONVERGED; remaining high-value work is
  Leo-gated. Private: ai-leo `evidence/wave9-claudux-stranger-2026-07-23.md`.
  2026-07-23.
- [completed] Proactive research wave 10 (cursor-grok-4.5) — hermetic tests
  for status missing-dev-root fallback + stderr/--json; PR #6 MERGED.
  2026-07-23.
- [completed] Proactive research wave 11 (cursor-grok-4.5) — CORE-CUT hermetic
  acceptance tests; PR #7 MERGED. 2026-07-23.
- [completed] Proactive research wave 12 (cursor-grok-4.5) — skillbox scrub
  sandboxed smoke green (dry-run/block/promote + test_scrub ALL PASS). Private:
  ai-leo `evidence/wave12-skillbox-scrub-smoke-2026-07-23.md`. No publicize.
  2026-07-23.
- [completed] Proactive research wave 13 (cursor-grok-4.5) — voice-debug
  private offline CI+smoke green (`ci-offline: PASS`, 8/8). Publish remains
  human-gated. Private: ai-leo `evidence/wave13-voice-debug-offline-2026-07-23.md`.
  2026-07-23.
- [completed] Proactive research wave 14 (cursor-grok-4.5) — claudux
  `tests/run-all.sh` all suites passed @028b54e. E2E stranger left to wave 9.
  Private: ai-leo `evidence/wave14-claudux-suite-2026-07-23.md`. 2026-07-23.
- [completed] Proactive research wave 15 (cursor-grok-4.5 2026-07-23T20:38:15-04:00) — WATCHING:
  agent-reachable amplify drained. Residual: wave 9 (claude-code claudux
  stranger e2e, claimed 19:45 local, no public receipt yet); voice-debug
  publish + skillbox visibility flip human-gated. Resume when wave 9 folds
  or a new candidate row appears. No publicize.
- [completed] Proactive research wave 16 (cursor-grok-4.5) — superseded stale
  wave 9: claudux stranger install/check/help + suite green (2.0.0); no defects.
  Full `update` model e2e deferred. Private:
  ai-leo `evidence/wave16-claudux-stranger-2026-07-23.md`. Wave 9 row left
  untouched. 2026-07-23.
- [completed] Proactive research wave 17 (cursor-grok-4.5) — skillbox stranger:
  private clone expected; npm/Homebrew name collision found; PR #4 MERGED
  (PATH-first + recovery note). Suite ALL GREEN. No publicize. Private:
  ai-leo `evidence/wave17-skillbox-stranger-2026-07-23.md`. 2026-07-23.
- [completed] Proactive research wave 18 (cursor-grok-4.5) — skillbox doctor
  PATH-SHADOW soft-warn for npm/Homebrew name collision; PR #5 MERGED; suite
  ALL GREEN (17). No publicize. Private:
  ai-leo `evidence/wave18-skillbox-path-shadow-2026-07-23.md`. 2026-07-23.
- [completed] Proactive research wave 19 (glm-max via Delegate; parent
  cursor-grok) — empty Claude/Codex `--version` → warn; claudux PR #126 MERGED;
  suite green. Seat-mix: first GLM wave after Grok streak. Private:
  ai-leo `evidence/wave19-glm-empty-version-2026-07-23.md`. 2026-07-23.
- [completed] Proactive research wave 20 (cursor-grok-4.5 steward 2026-07-23T23:23:56-04:00) — WATCHING:
  Claudux A+ upgrade plan ready (Sol Max claim-audit lexicon frozen: write
  boundaries TRUE; terminal content-diff OVERSELL until W3). Ultracode fan-out
  (GLM/Sol/Grok) deferred until Leo says execute. Voice-debug + skillbox
  publicize still human-gated. Resume: execute Claudux A+ plan → Sol W0/W2/W3.
  No publicize. 2026-07-23.
- [claimed: claude-code 2026-07-23T23:36:30-0400] Proactive research wave 21 —
  Claudux A+ EXECUTE (Leo said GO). Sol Max triple-check of the "deterministic
  doc-diff" claim (verify the frozen TRUE/OVERSELL lexicon against source) +
  ultracode Claude-side fan-out: (a) test-tautology audit of the determinism
  suites, (b) real `claudux update` terminal capture as the honest showcase
  asset, (c) accuracy audit of `assets/claudux-terminal-demo.svg` + README alt
  text vs the OVERSELL lexicon. Showcase + A+ README GATED behind the audit
  confirming the claim; honest-lexicon framing only, never the OVERSELL lines.
  Lead orchestrates + accepts + proves; Sol audits; GLM builds the counter-defect
  demo fix (`lib/claude-utils.sh` "Processed 0 changes" vs real writes); Grok
  critiques tests. Ground-truth note folded: NO history wipe — claudux is 49
  clean commits, live contributors API = leojkwan only, zero snapchat/TESTPERSONAL;
  vidux exposure already remediated.
  AUDIT LANDED (Sol Max + asset lens, 2026-07-24) — determinism claim is REAL,
  GO on honest-lexicon framing. Sol re-verified the frozen lexicon vs source:
  T1/T2/T4/T5 CONFIRMED (bounded all-or-nothing section patches
  @lib/docs-manifest.sh:1204-1268; guard-snapshot hashes @:1416-1450;
  source-boundary fail-closed @lib/docs-generation.sh:267-334; suites prove
  CONSTRAINTS @tests/test-docs-manifest.sh:611-683), all 5 OVERSELL lines
  CONFIRMED. Two REVISE refinements folded: T3 — the "diff" = committed changed
  filenames + dirty docs/manifest filenames → impact allowlist, NEVER a prose
  diff (@lib/docs-generation.sh:337-393 → resolve_impacted_docs_from_changed_files
  @:795-815 → reject "outside incremental impact allowlist"
  @lib/docs-manifest.sh:1140-1179); O2 — link check ALSO validates duplicate
  explicit heading IDs, non-fatal unless --strict (@lib/validate-links.sh:30-89).
  THE ONE HONEST SENTENCE (top-of-README): "In manifest-backed incremental
  updates, Claudux maps changed filenames to allowed documentation sections and
  rejects model-authored patches outside that deterministic write boundary."
  Deterministic = the write BOUNDARY; NOT deterministic = the model-authored
  body_markdown (@lib/docs-manifest.sh:1192-1268). Counter defect CONFIRMED &
  root-caused: counters print parsed model-tool events, but manifest mode grants
  the model only Read — real doc writes happen later in
  apply_manifest_section_patches outside the parsed log → "Processed 0 changes";
  fix belongs after patch apply @lib/docs-generation.sh:1046. Tests REAL not
  mock-green (source production code, assert real rejection/acceptance); one gap
  = no fs-failure atomicity test on the sequential writeFileSync loop
  @lib/docs-manifest.sh:1260-1269. Asset lens: SVG + README alt text = KEEP,
  environment-honest (criterion 8), zero oversell flags — every depicted line
  maps to a real lib/ emitter, NO fabricated content-diff.
  GATE LANDED (2026-07-24) — decision GO_WITH_CAVEATS. Mechanism lens CONFIRMED
  the exact trigger mechanics (showcase-critical): TIER 1 section-patch bounded
  mode is triggered SOLELY by docs-structure.json existing (flips model tools to
  Read-only @lib/docs-generation.sh:902-906), active even first run; TIER 2 the
  impact-allowlist REJECTION (line 1178) additionally needs a prior checkpoint —
  so an honest capture of the rejection = run once → modify a source file → run
  again. Honest headline LOCKED (richer than the one-sentence): "claudux keeps
  your docs structure in a repo-owned manifest, restricts the model to proposing
  section-scoped patches, and applies them behind deterministic guards — path
  boundaries, all-or-nothing validation, and sha256 hashes that refuse silent
  edits to protected sections." MUST-NOT-SAY (8): never "deterministic doc-diff"
  as a capability; never imply a content/prose diff (only `git diff docs/`
  @lib/git-utils.sh:75); never determinism=prose-accuracy; allowlist NOT
  every-run (null unless prior checkpoint @lib/docs-manifest.sh:1141); NOT
  "validates all doc links"; NOT "broken links fail build"; NOT "smart cleanup
  removes stale docs"; NOT "atomic/rollback". GROUND-TRUTH README FINDING: the
  SHIPPED README line 59 ("Every update validates internal links and fails
  loudly on broken ones") is itself an oversell the audit catches — verified
  fail-OPEN/informational by default @lib/docs-generation.sh:1116 ("validation
  is informational"), fatal only under --strict @:1117-1119, and scope is
  VitePress nav/sidebar config links only @lib/validate-links.sh:89 (not body
  links). That is the #1 honesty fix. Test-honesty workflow lens hit the
  StructuredOutput retry cap (no verdict) but is fully covered by Sol §4 (tests
  REAL, atomicity gap noted) — no coverage gap. Current README is otherwise
  already mostly honest (line 16 "not a free-writing model pass"; line 55 "they
  do not replace review") — the "deterministic doc-diff" oversell Leo feared is
  NOT in the shipped README. BUILD PHASE ACTIVE: (1) README honesty PR — fix
  line 59 link claim, tighten line 66 for incremental-only allowlist, soften
  line 51 caption to "reconstructed from a real claudux run", lift the honest
  headline; (2) counter-defect fix PR @lib/docs-generation.sh:1046 (GLM/Sol
  build seat, M1 delegate-first); (3) /architect diagram of manifest→allowlist→
  bounded-patch→hash-guard→boundary→link-check (Leo-offered conceptual showcase,
  explicitly labeled concept); asset SVG = KEEP. All claudux changes ship via PR
  (per #119-#126), never direct-to-main; leojkwan@gmail.com identity.
  BUILD (1)+(3) SHIPPED (2026-07-24) — PR #127 (firstbitelabsllc/claudux,
  +159/-4, README.md + assets/claudux-rails.svg), ready-for-review, all 7 CI
  green, MERGEABLE/CLEAN. Headline locked to the write-boundary framing;
  line-59 link claim corrected to fail-open + nav/sidebar scope + --strict;
  caption softened to "Reconstructed from a real claudux run";
  incremental-allowlist nuance folded on line 70; new theme-aware /architect
  rails diagram (WebKit pixel-proof both themes, taste lint 0/0/0, criterion-8
  environment-honest — every depicted line maps to a real lib/ emitter, no
  fabricated content-diff). Graphite auto-review on now that it is non-draft;
  lead-owned, not self-merging until the skeptic pass lands. BUILD (2)
  ALREADY LANDED — counter-defect fixed by PR #128 (443ebff, concurrent lane,
  now on origin/main). Verified REAL not stale-claim: claude-utils.sh:407-419
  branches on the exported CLAUDUX_SECTION_PATCH_MODE (set at
  docs-generation.sh:768-769), prints "Model phase: N read(s) — writes apply
  after validation" instead of "Processed 0 changes", preserves the old counter
  in the non-manifest else-branch, wired for BOTH backends (codex-utils.sh:115).
  No GLM delegation needed. BUILD PHASE COMPLETE (1+2+3 all landed).
- MERGE RECEIPT (2026-07-24): PR #127 MERGED to firstbitelabsllc/claudux `main`
  (squash, merge commit 5868009). Supersedes the "not self-merging until the
  skeptic pass lands" note above. The lead adversarial skeptic pass (Opus 4.8,
  honesty-critical artifact = lead-owned, never delegated) caught one residual
  oversell the earlier receipt missed: line 16's categorical "It is not a
  free-writing model pass" is locally FALSE on a first run — with no
  `docs-structure.json` the model has full Write/Edit and the first pass IS free
  generation; manifest presence is what flips it Read-only
  @lib/docs-generation.sh:902-906. FIXED pre-merge (commit 745084f): headline
  now keys off the actual trigger ("Without a manifest, that's a full generation
  pass; commit a `docs-structure.json` and it stops being one — …"), honest for
  both paths and survives a hostile reader who runs a first-time generation.
  Graphite AI Reviews terminally SKIPPED (docs-only PR) — the external skeptic
  pass did not vanish, it was substituted by the lead adversarial read + the
  prior Sol audit, which is the exact triple-check the goal demanded. All 7 CI
  green on the fix commit (ShellCheck, Test suite, Docs build, Version
  consistency, File structure, Release readiness, Bash syntax) + Graphite
  mergeability; MERGEABLE/CLEAN. README honesty rewrite + theme-aware /architect
  rails diagram + `assets/claudux-rails.svg` all now on origin/main (5868009).
  claudux deliverable (audit → showcase → A- README) COMPLETE and LANDED.

- [completed] Proactive research wave 22 (sol / cursor parent) — claudux
  public-ready identity gate PR #129 MERGED (employer/domain patterns + HEAD
  metadata; CI + npm run verify). No history wipe. Suite green. 2026-07-24.
- [completed 2026-07-24T02:08:44-04:00] Proactive research wave 23 — residual docs
  oversell honesty → claudux#130 (smart-cleanup stub, accuracy/zero-config,
  technical privacy). Content public-ready gate green; metadata gate still
  fails on historical test@test.com (pre-existing).
- [completed 2026-07-24T02:23:50-04:00] Proactive research wave 24 (sol /
  cursor-parent) — merged claudux#130 (squash 63fc9f4); HEAD `npm run
  public-ready` green (no history wipe; gate is HEAD-scoped). Tagged+pushed
  `v2.0.0`; stranger install smoke (isolated HOME, CLAUDUX_REF=v2.0.0) →
  claudux 2.0.0 + honest smart-cleanup stub present. Voice-debug still
  human-gated.
- [completed 2026-07-24T02:38:02-04:00] Proactive research wave 25 (glm-max) —
  GitHub Release https://github.com/firstbitelabsllc/claudux/releases/tag/v2.0.0
  (install pin + honesty highlights / not-claims). Voice-debug still human-gated.
- [completed 2026-07-24T02:54:46-04:00] Proactive research wave 26 (sol /
  cursor-parent) — claudux#131 MERGED: README + docs home + installation show
  `CLAUDUX_REF=v2.0.0` pin beside main install + release link. Voice-debug
  still human-gated.
- [completed 2026-07-24T03:09:09-04:00] Proactive research wave 27 (glm-max) —
  claudux#132 MERGED → tagged `v2.0.1` + GitHub Release; stranger install smoke
  → `claudux 2.0.1`. Voice-debug still human-gated.
- [completed 2026-07-24T03:29:21-04:00] Proactive research wave 28 (sol /
  cursor-parent) — claudux v2.0.1 stranger smoke green; skillbox still private
  (no publicize). Found+fixed vidux shared-TMPDIR browser pidfile leak →
  firstbitelabsllc/vidux#8 MERGED (XDG state dir; legacy TMPDIR warns).
  Voice-debug publish still human-gated.
- [completed 2026-07-24T03:42:56-04:00] Proactive research wave 29 (glm-max) —
  vidux#9 MERGED → tagged `v1.0.1` + GitHub Release; stranger clone smoke →
  `vidux 1.0.1`. Voice-debug still human-gated.
- [completed 2026-07-24T03:53:09-04:00] Proactive research wave 30 (sol /
  cursor-parent) — README Release truth updated: current contract `1.0.1`,
  points at GitHub Release (removed stale “no GitHub Release yet”). Landed
  with claim commit d1a0c9a8. Voice-debug still human-gated; skillbox/litty
  private.
- [completed 2026-07-24T04:12:22-04:00] Proactive research wave 31 (glm-max) —
  vidux#10 MERGED → tagged `v1.0.2` + GitHub Release; stranger clone smoke →
  `vidux 1.0.2` with honest Release truth. Voice-debug still human-gated.
- [completed 2026-07-24T04:24:18-04:00] Proactive research wave 32 (sol /
  cursor-parent) — claudux#133 MERGED: project lock under
  `${XDG_STATE_HOME:-~/.local/state}/claudux/locks/` (not shared TMPDIR).
  Hardening + CI green. Voice-debug still human-gated; skillbox private.
- [completed 2026-07-24T04:40:47-04:00] Proactive research wave 33 (glm-max) —
  claudux#134 MERGED → tagged `v2.0.2` + GitHub Release; stranger install
  smoke → `claudux 2.0.2`. Voice-debug still human-gated.
- [completed 2026-07-24T04:55:43-04:00] Proactive research wave 34 (sol /
  cursor-parent) — claudux#135 MERGED: Codex stderr log under
  `${XDG_STATE_HOME:-~/.local/state}/claudux/codex-stderr.log`. Suite green.
  Voice-debug still human-gated; skillbox private.
- [completed 2026-07-24T05:10:06-04:00] Proactive research wave 35 (glm-max) —
  claudux#136 MERGED → tagged `v2.0.3` + GitHub Release; stranger install
  smoke → `claudux 2.0.3`. Voice-debug still human-gated.
- [completed 2026-07-24T05:26:34-04:00] Proactive research wave 36 (sol /
  cursor-parent) — claudux#137 MERGED: `claudux_mktemp` honors TMPDIR (no
  hardcoded `/tmp/claudux-*`). Suite green. Voice-debug still human-gated.
- [pending] Proactive research wave 37 — next reachable win (claim first);
  voice-debug publish remains human-gated.

## Claim discipline

One agent per row. Claim by editing the row to
`[claimed: <agent-seat> <iso8601>]` in a pushed commit BEFORE doing the work;
never rewrite another lane's claimed row; re-read this file from `origin/main`
before every write. Receipts (PR numbers, refs, test counts) go in the row when
it completes.
