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

## Claim discipline

One agent per row. Claim by editing the row to
`[claimed: <agent-seat> <iso8601>]` in a pushed commit BEFORE doing the work;
never rewrite another lane's claimed row; re-read this file from `origin/main`
before every write. Receipts (PR numbers, refs, test counts) go in the row when
it completes.
