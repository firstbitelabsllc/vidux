# No external integrations

Vidux is markdown + git, and that's the whole store. There is **no** external-board
or issue-tracker integration, no sync path, and no adapter layer.

`PLAN.md` in git is the only queue/planning authority. You read it, update it, and
checkpoint it as files. If your team lives on a kanban board, mirror vidux's plan
state there by hand — vidux will not round-trip to one.

Why plan-native: the store *is* the discipline. A second synced surface is a second
source of truth, and the failure mode of every board integration is silent drift
between the board and the plan. Keeping `PLAN.md` as the sole authority removes that
drift by construction.

## FAQ

### What if my team already works from a board?

Keep using it for human communication if you want, but treat it as a mirror.
Vidux will not sync tasks, statuses, comments, or ownership back and forth. The
agent-readable source of truth stays `PLAN.md` plus the matching proof ledger.

### Can I build my own bridge?

Yes, outside the core contract. Keep it as a private overlay or downstream tool
that reads `PLAN.md` and writes its own projection. Do not make Vidux depend on
that projection, and do not teach agents that the projection is authoritative.
