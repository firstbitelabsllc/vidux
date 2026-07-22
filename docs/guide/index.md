# What is Vidux?

Vidux keeps AI coding work recoverable across sessions, agents, or days by making the plan, proof, decisions, and resume point explicit on disk.

## The Core Problem

Most agent failures are state failures:

- The plan lived in chat instead of files
- Code was written before evidence existed
- A later session could not tell what was intentional
- The same bug got "fixed" three different ways

When a session ends, its context is gone. A new session has no idea what the previous one was doing, why decisions were made, or what not to touch. That is agent drift: each session makes slightly different decisions and the codebase loses coherence.

## The Solution

Vidux makes repo-local plan/proof files the recovery packet. The owning `PLAN.md`
carries the queue, decisions, evidence, and progress. Matching publish ledger
rows carry the shipped-cycle proof packet: proof, handoff status, claimed files,
resume metadata. Git stores docs and transport history; it does not replace the
plan-plus-ledger packet.

```
PLAN.md - queue/planning authority
├── What to build (tasks with status tags)
├── Why it was decided (Decision Log)
├── What happened (Progress log)
└── What we know (Evidence citations)

publish ledger rows - shipped-cycle proof packet
├── What shipped (summary + task id)
├── How it was proved (proof command or artifact)
├── What changed (files claimed + path-like claims)
└── Where to resume (handoff status + next-agent resume)
```

## How It Works

Every change flows through a four-stage loop:

```
Doc Tree → Work Queue → Fresh Agent → Code Change → Doc Tree
```

Inside each agent run, five steps execute in order — none skippable. Canonical loop: READ → ASSESS → ACT → VERIFY → CHECKPOINT.

1. **READ** — Load PLAN.md, check git log, scan for uncommitted work
2. **ASSESS** — Does the next task have evidence? Code or refine?
3. **ACT** — Execute tasks until queue empty, blocker, or context budget
4. **VERIFY** — Build, test, visual proof
5. **CHECKPOINT** — Plan/progress update plus publish ledger row; git transport only after propagation

Code wrong = plan wrong. Fix the plan first. The owning plan plus publish ledger
row persists across sessions; each run dies. Any fresh agent rehydrates from repo
docs and ledger proof, then continues.

## How Vidux Compares

|  | Vidux | Raw Claude Code / Cursor | Aider / OpenCode |
|---|---|---|---|
| **State** | `PLAN.md` in git — survives sessions, agents, days | Chat history — dies when the window closes | Session-scoped context |
| **Multi-agent** | Any agent reads the same files and picks up | Single agent per session | Single agent |
| **Verification** | Evidence → plan → execute → verify → checkpoint | Trust the output | Trust the output |
| **Automation (opt-in)** | Scheduled lanes read the same plan/proof packet | N/A | N/A |
| **Agent agnostic** | Claude, Cursor, Codex — anything that reads markdown | Tool-specific | OpenAI / Anthropic |

Vidux doesn't replace your coding agent — it gives it a memory that outlasts the session.

## Core Invariants

Hard rules that prevent the most common stateless-agent failures:

**One project, one `PLAN.md`** — course corrections update the existing plan's Decision Log; NEVER spawn a sibling plan. The Decision Log records why a pivot happened.

**Compound tasks + L2 investigations** — messy surfaces get a compound task linking to an `investigations/<slug>.md` sub-plan. The L2 investigation is the work until the Fix Spec is filled.

**Progress is code change** — a PR touching only `PLAN.md` / `investigations/` / `evidence/` / `INBOX.md` is bookkeeping, not progress. Bundle plan updates into the code PR that ships the fix, or keep notes local. Codified in the 2026-04-17 doctrine update.

**Append-only logs** — `## Progress` in `PLAN.md` and each lane's `memory.md` are strictly append-only. Corrections go in new entries, never rewrites. Core vidux does not require a separate `PROGRESS.md`.

**3x stuck rule** — same task in 3+ consecutive progress entries while still in-progress → force a surface switch.

## Next Steps

- [Install Vidux](/guide/installation) — set up the skill in Claude Code
- [Quick Start](/guide/quickstart) — run your first cycle
- [Five Principles](/concepts/principles) — understand the doctrine
