#!/usr/bin/env bash
# vidux-init.sh — scaffold a cockpit-ready PLAN.md from the canonical template.
#
set -euo pipefail

VIDUX_ROOT="${VIDUX_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

usage() {
  cat <<'USAGE'
vidux init — bootstrap a new plan.

usage: vidux init <slug>
       vidux init <slug> --plan-store <path>
       vidux init --here
       vidux init --help|-h

With --here, creates PLAN.md in the current project directory. This is the
canonical first-run path. The legacy <slug> form creates <store>/<slug>/PLAN.md
only when a persistent plan store is selected explicitly with --plan-store,
VIDUX_PLAN_STORE, or a live config. It never writes into the Vidux install.
The slug must be lowercase letters, digits, and hyphens only (matching
^[a-z0-9-]+$). Refuses to overwrite an existing PLAN.md.

The template includes plan authority, a starter Operator Brief, an honest
unproven scorecard, and the canonical task/decision/progress sections.

exit codes:
  0   plan created
  1   target PLAN.md already exists
  2   invalid usage (no slug, bad slug, unknown flag)
USAGE
}

absolute_path() {
  python3 - "$1" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).expanduser().resolve())
PY
}

default_config_path() {
  local config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
  printf '%s/vidux/vidux.config.json' "${config_home%/}"
}

plan_store_from_config() {
  local config_path="$1"
  python3 - "${config_path}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1]).expanduser().resolve()
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    print(f"vidux init: cannot read plan store from {path}: {exc}", file=sys.stderr)
    raise SystemExit(2)

plan_store = payload.get("plan_store")
if not isinstance(plan_store, dict):
    print(f"vidux init: {path} has no plan_store object", file=sys.stderr)
    raise SystemExit(2)
mode = plan_store.get("mode", "local")
if mode not in {"local", "external"}:
    print(f"vidux init: plan_store.mode {mode!r} cannot host a central slug plan", file=sys.stderr)
    raise SystemExit(2)
raw = plan_store.get("path")
if not isinstance(raw, str) or not raw.strip():
    print(f"vidux init: {path} has no persistent plan_store.path", file=sys.stderr)
    raise SystemExit(2)

store = pathlib.Path(raw).expanduser()
if not store.is_absolute():
    store = path.parent / store
print(store.resolve())
PY
}

reject_install_root_store() {
  local plan_store="$1"
  local install_root
  install_root="$(absolute_path "${VIDUX_ROOT}")"
  case "${plan_store}" in
    "${install_root}"|"${install_root}"/*)
      echo "vidux init: central plan store must be outside the Vidux install: ${install_root}" >&2
      echo "use 'vidux init --here' (recommended) or select a persistent external --plan-store" >&2
      return 2
      ;;
  esac
}

# Title-case helper: turn "my-cool-slug" into "My Cool Slug".
slug_to_title() {
  local slug="$1"
  local out=""
  local part
  local IFS='-'
  # shellcheck disable=SC2206
  local parts=( $slug )
  for part in "${parts[@]}"; do
    [[ -z "${part}" ]] && continue
    local head="${part:0:1}"
    local tail="${part:1}"
    out+="$(printf '%s' "${head}" | tr '[:lower:]' '[:upper:]')${tail} "
  done
  # Trim the trailing space.
  printf '%s' "${out% }"
}

emit_template() {
  local title="$1"
  local today="$2"
  cat <<EOF
# ${title}

## Purpose

Keep ${title}'s next work, decisions, and proof resumable across agent sessions.

## Evidence

- [Source: PLAN.md, ${today}] Plan initialized; product evidence is not established yet.

## Constraints

**ALWAYS:**
- Update this plan when the next move or result changes.
- Attach a command result or artifact before marking work complete.

**NEVER:**
- Treat an unverified result as shipped.

## Operator Brief

- Status: watching
- Priority: 50
- Outcome: Ship the first evidence-backed result for ${title}.
- Next: Replace the starter task with the first concrete deliverable.
- Why: This plan is new and its first result is not defined yet.
- Validation: Attach one command result or artifact to the completed task.
- Cost: Keep the first cycle under 30 minutes.
- Evidence: evidence/first-result.md
- Updated: ${today}

## Outcome Scorecard

| Metric | Baseline | Current | Target | Status | Proof |
|---|---|---|---|---|---|
| First evidence-backed result | Not defined | Not started | One completed task with proof | unproven | evidence/first-result.md |

## Tasks

- [pending] T-1: Define and ship the first evidence-backed result [ETA: 0.5h]

## Decision Log

- [DIRECTION] [${today}] Start with one bounded, evidence-backed deliverable. Reason: make the first resume point concrete.

## Progress

- [${today}] Plan initialized with an unproven starter outcome.
EOF
}

main() {
  if [[ $# -eq 0 ]]; then
    echo "vidux init: missing <slug>" >&2
    echo >&2
    usage >&2
    exit 2
  fi

  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --here)
      if [[ $# -gt 1 ]]; then
        echo "vidux init: --here does not accept additional arguments" >&2
        exit 2
      fi
      ;;
    --*|-*)
      echo "vidux init: unknown flag: $1" >&2
      echo >&2
      usage >&2
      exit 2
      ;;
  esac

  local slug
  local target_dir
  if [[ "$1" == "--here" ]]; then
    target_dir="$(pwd -P)"
    slug="$(basename "${target_dir}")"
  else
    slug="$1"
    if ! [[ "${slug}" =~ ^[a-z0-9-]+$ ]]; then
      echo "vidux init: invalid slug: ${slug}" >&2
      echo "slug must match ^[a-z0-9-]+\$ (lowercase letters, digits, hyphens)" >&2
      exit 2
    fi
    shift
    local requested_store=""
    if [[ $# -gt 0 ]]; then
      if [[ "$1" != "--plan-store" || $# -ne 2 ]]; then
        echo "vidux init: expected '<slug> --plan-store <path>'" >&2
        echo >&2
        usage >&2
        exit 2
      fi
      requested_store="$2"
    elif [[ -n "${VIDUX_PLAN_STORE:-}" ]]; then
      requested_store="${VIDUX_PLAN_STORE}"
    else
      local config_path="${VIDUX_CONFIG:-$(default_config_path)}"
      config_path="$(absolute_path "${config_path}")"
      if [[ ! -f "${config_path}" ]]; then
        echo "vidux init: central <slug> mode requires an explicit persistent plan store" >&2
        echo "use 'vidux init --here' (recommended), --plan-store <path>, VIDUX_PLAN_STORE, or a live config at ${config_path}" >&2
        exit 2
      fi
      if ! requested_store="$(plan_store_from_config "${config_path}")"; then
        exit 2
      fi
    fi
    if [[ -z "${requested_store}" ]]; then
      echo "vidux init: plan store path must not be empty" >&2
      exit 2
    fi
    target_dir="$(absolute_path "${requested_store}")"
    reject_install_root_store "${target_dir}"
    target_dir="${target_dir}/${slug}"
  fi
  local target_file="${target_dir}/PLAN.md"

  if [[ -e "${target_file}" || -L "${target_file}" ]]; then
    echo "vidux init: ${target_file} already exists — refusing to overwrite" >&2
    exit 1
  fi

  mkdir -p "${target_dir}"

  local title
  title="$(slug_to_title "${slug}")"
  emit_template "${title}" "$(date -u +%F)" > "${target_file}"

  # Print the real absolute path, not a bare "projects/<slug>/PLAN.md" --
  # that reads as relative to $PWD but it's actually relative to VIDUX_ROOT
  # (this vidux checkout), which is the exact confusion this once caused: a
  # user running this from their own project directory saw a misleading
  # message and no file where they expected one.
  echo "created ${target_file}"
}

main "$@"
