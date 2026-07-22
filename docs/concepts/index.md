# Core Concepts

A small set of ideas, each solving a specific failure mode of stateless AI agents.

## The Three Layers

```
┌─────────────────────────────────────────────┐
│                  DOCTRINE                   │
│  5 principles + gate patterns + stuck detect│
└──────────────────────┬──────────────────────┘
                       │ governs
┌──────────────────────▼──────────────────────┐
│                  THE CYCLE                  │
│  Read → Assess → Act → Verify → Checkpoint  │
└──────────────────────┬──────────────────────┘
                       │ reads/writes
┌──────────────────────▼──────────────────────┐
│                  THE STORE                  │
│  PLAN.md + ledger + evidence/ + git         │
└─────────────────────────────────────────────┘
```

- **Doctrine** — the rules. Five principles and gate patterns governing agent behavior.
- **The Cycle** — the loop. Five steps every session follows, in order, without skipping.
- **The Store** — files plus ledger rows. Where queue state, evidence, investigations, shipped-cycle proof, and git transport evidence live.

## Why These Three Layers?

**Without doctrine**, agents make different decisions each session and drift apart. Two agents on the same project eventually contradict each other.

**Without the cycle**, agents skip steps under time pressure: evidence gathering when work looks "obvious," verification when the diff "looks right," checkpointing when the session ends abruptly.

**Without the store**, state lives in chat history or agent memory — both die when the session ends. Repo files plus matching publish ledger rows are the reliable recovery packet; git transports the diff when code changed, but does not replace a missing plan/ledger packet.

## Key Concepts

- [Five Principles](/concepts/principles) — the doctrine that governs agent behavior
- [The Cycle](/concepts/cycle) — READ → ASSESS → ACT → VERIFY → CHECKPOINT mechanics
- [PLAN.md Structure](/concepts/plan-structure) — the full template with all required sections
- [The Store](/concepts/store) — how state persists across sessions and agents
- [No External Integrations](/concepts/extensions) — why Vidux does not sync
  with external boards or issue trackers
