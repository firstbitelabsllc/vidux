# Configuration

Vidux stores live user defaults outside the installed package:

- `$XDG_CONFIG_HOME/vidux/vidux.config.json` when `XDG_CONFIG_HOME` is set.
- `~/.config/vidux/vidux.config.json` otherwise.

This keeps configuration persistent when an npm package is upgraded or removed
and keeps machine-specific paths and tokens out of shared source.

The checked-in shape is `vidux.config.example.json`. When no live config exists,
`python3 scripts/vidux-config.py check` and the doctor use the example as a validation fallback.

## Resolution order

1. `--config <path>` selects an explicit file.
2. `VIDUX_CONFIG=<path>` selects an explicit file for scripts and automation.
3. The XDG user config path above is the default live file.
4. The package's checked-in `vidux.config.example.json` is a read-only shape
   fallback when no live file exists.

A checkout-local `vidux.config.json` remains compatible only through
`--config` or `VIDUX_CONFIG`; it is never discovered implicitly. This prevents
a global npm install from treating its own `node_modules` directory as durable
user state.

The example includes these top-level areas:

- `version`
- `plan_store`
- `defaults`
- `external_plan_roots`
- `pruning`
- `backpressure`

## CLI checks

Use the shell CLI before changing config-dependent scripts:

```bash
python3 scripts/vidux-config.py path
python3 scripts/vidux-config.py check
python3 scripts/vidux-config.py show --json
python3 scripts/vidux-config.py init
```

`python3 scripts/vidux-config.py init` writes the XDG user path by default. `--path <path>` is an
explicit source-checkout compatibility override; destinations inside a
`node_modules` package root are rejected. Default setup never needs write
access to the source checkout or npm package root.

`check --strict` fails when only the example file is available — useful for
machine-readiness gates that require a real local config. `show` is redacted: it
reports source, path, plan-store summary, expanded external root paths,
and issues.

The JSON report keeps compatibility field `external_plan_roots`, plus detail
fields:

- `external_plan_roots_detail` expands each configured root relative to the
  config file and reports whether the path exists.

## `plan_store`

The README and config files describe three plan-store modes:

- `inline` - use `PLAN.md` in the current repo.
- `local` - use a configured persistent machine-local path.
- `external` - use a configured path outside the repo root.

For new projects, prefer `vidux init --here`; the owning repository's `PLAN.md`
stays beside the work it governs. The legacy `vidux init <slug>` form requires
an explicit plan store from `--plan-store`, `VIDUX_PLAN_STORE`, or the live
config and refuses a path inside the Vidux install.

## Example minimal config

This is the smallest documented shape from the README:

```json
{
  "plan_store": {
    "mode": "local",
    "path": "~/.local/share/vidux/plans"
  }
}
```

## Operational defaults

Sections that guide scripts and automation behavior when copied into a live config:

- `defaults` covers archive thresholds, context warnings, worktree limits, and system pressure limits.
- `pruning` covers stale blocked-task age, worktree age thresholds, and plan size warnings.
- `backpressure` defines warning and critical thresholds for bimodal pressure plus circuit-breaker windows.

## External plan roots

`external_plan_roots` lists additional plan roots. External intake, labels, and
board sync are out of core scope; keep that logic in a private overlay instead
of the shared config reference.

Treat the example file as one minimal shape, not an exhaustive mirror of every production config.

## Where config is used

- Root `SKILL.md` startup intake runs `python3 scripts/vidux-config.py check --json` and reads the
  selected plan-store settings before plan work.
- `scripts/vidux-config.py` resolves, validates, initializes, and redacts local config.
- `vidux doctor` runs `python3 scripts/vidux-config.py check --json` as part of local readiness.
- `vidux-loop.sh` reads defaults such as archive thresholds and context warning lines.
- `vidux-doctor.sh` reads runtime thresholds such as max worktrees, browser-process caps, Codex automation caps, and the minimum `memory_pressure -Q` free percentage. Runtime doctor JSON also includes source-specific `vm_stat` page counters so raw page-derived MB values are not mistaken for the same metric.
- `resolve-plan-store.sh` resolves the active plan root for scripts.

## Related references

- Read [Commands](/reference/commands) for the CLI contracts that inspect and
  initialize this file.
- Read [Scripts](/reference/scripts) for the executables that read config defaults directly.
