# Examples

The repo ships worked example directories under `examples/`. This page maps them into the docs site, including two drift-feedback smoke examples.

## Included examples

### Bug fix lifecycle

`examples/bug-fix-lifecycle/README.md` is a minimal start-to-finish walk-through:

- gather evidence
- write a `PLAN.md`
- execute one task
- verify
- checkpoint

It is the smallest concrete example of the plan-first cycle in this repo.

### Fleet reference

`examples/fleet-reference/README.md` shows a four-automation layout:

- one writer
- two radars
- one coordinator

That directory also includes sample TOML files for each lane role.

### Drift smoke examples

`examples/drift-smoke/api-cli-pivot/README.md` records a drift with a Prevention hint, writes the cache row, then proves a similar task receives a cache-backed suggestion.

`examples/drift-smoke/ui-telemetry-subplan/README.md` emits `drift.record`, summarizes the JSONL signpost log, and shows how parent-plan drift mirrors into a child investigation.

## When to use these examples

- Read the bug-fix example if you are new to vidux and want the smallest possible cycle.
- Read the fleet reference if you already understand the core cycle and want to see a scheduled multi-lane shape.
- The `## Drift Log` section records planned-vs-actual deviations manually (see `docs/reference/plan-fields.md`).

## Related docs

- [Quick Start](/guide/quickstart) explains the first interactive cycle.
- [Fleet Overview](/fleet/) shows where the automation docs fit.
