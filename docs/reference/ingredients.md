# Vidux Ingredients

> The 10 open-source patterns vidux adopted. Surveyed 26 tools; selected for pattern quality, not stars.

| # | Pattern | Source · stars | Vidux home | Adopt | Skip |
|---|---------|----------------|------------|-------|------|
| 1 | Brainstorm→Plan→Execute→Verify chain | superpowers · 128K | SKILL Five Principles | Plan-as-gate: each phase is a durable artifact before the next | Interactive brainstorm (use MCP evidence fan-out); skill-per-phase (one SKILL.md) |
| 2 | Spec-Plan-Tasks three-doc chain | spec-kit · 84K | PLAN.md template | Purpose+Evidence+Constraints+Decisions+Tasks in one git-tracked file; Constraints = constitution | Per-stack presets (live in companion skills); in-doc revision tracking (git history does it) |
| 3 | Stuck-loop detection + crash recovery | GSD · 46K | LOOP | 3-strike escalation; crash recovery preserves dirty WIP → plan/ledger handoff before any commit | Cost tracking; multi-runtime abstraction (markdown+bash is the runtime) |
| 4 | Execute/Qualify/Unify + escalation statuses | PAUL · 603 | LOOP | 4 statuses (done / concerns / needs-context / blocked); UNIFY reconciles plan vs git diff at checkpoint | Per-task E/Q/U sequencing (cycle is coarser — one task/cycle) |
| 5 | Markdown-native coordination, git-backed state | tick-md · 18 | SKILL Principle 2 | Markdown checkboxes as queue, git as transport, plan + publish ledger survive sessions | Flat task model (vidux adds deps, parallel flags, context sections) |
| 6 | Multi-perspective review gate | claude-code-harness · 383 | SKILL orchestration | Simulate tech-lead / reviewer / PM before ready, grounded in real MCP data | TS guardrail engine + routing DSL (markdown constraints); fixed 4 perspectives (data-driven) |
| 7 | One-agent-per-criterion + judge | opslane/verify · 100 | LOOP fan-out | One agent per concern, synthesizer as judge; readiness = atomic checks | Literal one-agent-per-criterion at code time (cap 4 + hierarchy instead) |
| 8 | Dual-workflow routing (feature vs bugfix) | claude-code-spec-workflow · 3.6K | DOCTRINE | vidux = multi-day features, overlay = quick fixes; activation criteria are the routing rules | MCP dashboard (Progress + ledger); steering docs (signal-based activation) |
| 9 | Research-before-planning, multi-source interview | deep-plan · 80 | SKILL Principle 1 | Every plan entry cites evidence; research-before-code; 4-group fan-out | Multi-LLM review (single-model critic); deep-implement codegen |
| 10 | Adversarial debate for spec hardening | adversarial-spec · 517 | SKILL fan-out | Tier-3 critic challenges assumptions; failure → adversarial five-whys | Multi-provider debate; anti-laziness monitors (gate + evidence enforce) |

## Surveyed but not selected

| Tool | Stars | Why not |
|------|-------|---------|
| anthropics/skills | 107K | SKILL.md frontmatter is the envelope we use, not a pattern we adopt |
| cc-sdd | 3K | Cross-agent compat is a goal, not a pattern — vidux gets it via markdown + env vars |
| smart-ralph | 269 | Queue contract absorbed into PLAN.md's task FSM |
| agent-teams-lite | 1.1K | Fresh-context sub-agents subsumed by the fan-out pattern (7, 9) |
| claude-orchestration | 201 | Workflow DSL conflicts with the markdown-only constraint |
| metaswarm | 169 | Self-improving loop underspecified; the Failure Protocol covers it more concretely |

*Surveyed 26 tools, selected 10. Last updated 2026-06.*
