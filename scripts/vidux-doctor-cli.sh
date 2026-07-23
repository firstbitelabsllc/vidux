#!/usr/bin/env bash
# vidux-doctor-cli — installation + toolchain diagnostics for the `vidux` CLI.
#
# This complements scripts/vidux-doctor.sh (which inspects runtime state across
# plans, automations, browsers, and codex threads). This script checks both
# source checkouts and installable release packages:
#
#   1. python3 >= 3.9
#   2. gh installed + logged in (optional integration; warning when absent)
#   3. ~/.config/vidux/*.token files (if any) are chmod 600
#   4. development/install truth (source, cached freshness, CLI + skill links)
#   5. No stale ${TMPDIR:-/tmp}/vidux-browser.pid residue (warning only)
#   6. 'scripts/vidux-config.py check --json' passes
#   7. `npm test` passes in a source checkout (warning in a packaged install)
#
# Each check prints `[PASS]`, `[WARN]`, or `[FAIL]`. Exit 0 when no hard check
# fails, exit 1 on a hard failure. `--json` exposes the same seven-check
# contract plus structured install identity/link details. The freshness probe
# reads only cached Git refs: it never fetches, pulls, rewrites refs, or repairs
# links. Pure Bash, stdlib + system tools — no extra dependencies beyond the
# system shell, python3, and the repo scripts.
#
set -euo pipefail

VIDUX_ROOT="${VIDUX_ROOT:-$HOME/Development/vidux}"
SKIP_NPM_TEST="${VIDUX_DOCTOR_SKIP_NPM_TEST:-0}"
OUTPUT_JSON=0

print_help() {
  cat <<EOF
vidux doctor — install/readiness doctor for the local CLI.

usage: vidux doctor [--json] [--help|-h]

This is the terminal user doctor for a checkout/fresh clone. For hook-safe
runtime state checks, use: scripts/vidux-doctor.sh --json

Runs the following checks in order, printing [PASS] / [WARN] / [FAIL]:
  1. python3 >= 3.9
  2. gh installed + authenticated (optional integration)
  3. ~/.config/vidux/*.token files have chmod 600 (if any exist)
  4. development/install truth: source identity, cached upstream freshness,
     PATH target, and optional skill-mount parity
  5. No stale browser pidfile residue at \${TMPDIR:-/tmp}/vidux-browser.pid
  6. 'scripts/vidux-config.py check --json' validates the selected config
  7. 'npm test' passes in source checkouts; packaged installs report a warning

Exit codes:
  0   no hard check failed (optional warnings may remain)
  1   one or more checks failed
  2   invalid usage, such as an unknown flag

output:
  --json                           Emit one structured JSON object. Install
                                   details include kind/root/version/SHA/branch,
                                   cached upstream distance, PATH parity, and
                                   per-mount state. No network or repair runs.

environment:
  VIDUX_ROOT                       Override vidux checkout root
                                   (default: \$HOME/Development/vidux)
  VIDUX_DOCTOR_SKIP_NPM_TEST=1     Skip the npm-test gate (check 7);
                                   useful in fast loops because full doctor
                                   can be slow when it runs npm test
EOF
}

# Parse flags. The doctor takes no positional args.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      OUTPUT_JSON=1
      shift ;;
    --help|-h)
      print_help
      exit 0 ;;
    *)
      echo "vidux doctor: unknown flag: $1" >&2
      print_help >&2
      exit 2 ;;
  esac
done

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0
TOTAL=0

# Bash 3.2-compatible indexed arrays (macOS system Bash has no associative
# arrays). These back --json without temporary files or helper processes.
CHECK_STATUSES=()
CHECK_MESSAGES=()

_record_check() {
  CHECK_STATUSES[${#CHECK_STATUSES[@]}]="$1"
  CHECK_MESSAGES[${#CHECK_MESSAGES[@]}]="$2"
}

_pass() {
  TOTAL=$((TOTAL + 1))
  PASS_COUNT=$((PASS_COUNT + 1))
  _record_check "pass" "$1"
  if [[ "$OUTPUT_JSON" -eq 0 ]]; then
    printf '[PASS] %s\n' "$1"
  fi
}

_fail() {
  TOTAL=$((TOTAL + 1))
  FAIL_COUNT=$((FAIL_COUNT + 1))
  _record_check "fail" "$1: $2"
  if [[ "$OUTPUT_JSON" -eq 0 ]]; then
    printf '[FAIL] %s: %s\n' "$1" "$2"
  fi
}

_warn() {
  TOTAL=$((TOTAL + 1))
  WARN_COUNT=$((WARN_COUNT + 1))
  _record_check "warn" "$1: $2"
  if [[ "$OUTPUT_JSON" -eq 0 ]]; then
    printf '[WARN] %s: %s\n' "$1" "$2"
  fi
}

_json_quote() {
  # Doctor-generated messages and filesystem paths are line-oriented. Escape
  # the complete JSON string surface without invoking Python (the Python check
  # itself may be the failing result this JSON needs to report).
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '"%s"' "$value"
}

_json_nullable_string() {
  if [[ -n "$1" ]]; then
    _json_quote "$1"
  else
    printf 'null'
  fi
}

# Install-truth fields are initialized even when an early hard check fails, so
# --json remains schema-stable.
INSTALL_STATUS="unknown"
INSTALL_KIND="unknown"
INSTALL_SOURCE_ROOT=""
INSTALL_VERSION="unknown"
INSTALL_SHA=""
INSTALL_BRANCH=""
INSTALL_UPSTREAM_REF=""
INSTALL_UPSTREAM_STATE="unavailable"
INSTALL_AHEAD=""
INSTALL_BEHIND=""
INSTALL_PATH_COMMAND=""
INSTALL_PATH_TARGET=""
INSTALL_PATH_STATE="not_checked"
INSTALL_DEV_ROOT=""
INSTALL_DEV_ROOT_STATE="unknown"
MOUNT_PATHS=()
MOUNT_STATES=()
MOUNT_TARGETS=()

# ----------------------------------------------------------------------------
# Check 1: python3 >= 3.9
# ----------------------------------------------------------------------------
check_python_version() {
  local name="python3 >= 3.9"
  if ! command -v python3 >/dev/null 2>&1; then
    _fail "$name" "python3 not found on PATH"
    return
  fi
  local raw major minor
  if ! raw="$(python3 --version 2>&1)"; then
    _fail "$name" "python3 --version exited non-zero"
    return
  fi
  # Expected format: "Python 3.X.Y" — extract X and Y
  local ver
  ver="${raw#Python }"
  major="${ver%%.*}"
  local rest="${ver#*.}"
  minor="${rest%%.*}"
  if ! [[ "$major" =~ ^[0-9]+$ ]] || ! [[ "$minor" =~ ^[0-9]+$ ]]; then
    _fail "$name" "could not parse version string: $raw"
    return
  fi
  if [[ "$major" -lt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -lt 9 ]]; }; then
    _fail "$name" "found python $major.$minor, need >= 3.9"
    return
  fi
  _pass "$name (found python $major.$minor)"
}

# ----------------------------------------------------------------------------
# Check 2: gh installed + authenticated
# ----------------------------------------------------------------------------
check_gh_auth() {
  local name="gh authenticated"
  if ! command -v gh >/dev/null 2>&1; then
    _warn "$name" "optional GitHub integration unavailable; install gh to use PR/release helpers"
    return
  fi
  # gh auth status prints to stderr and exits non-zero when not logged in.
  local out
  if ! out="$(gh auth status 2>&1)"; then
    _warn "$name" "optional GitHub integration is signed out (run: gh auth login)"
    return
  fi
  # Confirm at least one host shows "Logged in" — older gh versions phrase this
  # differently, so accept either "Logged in" or "✓ Logged in".
  if ! printf '%s\n' "$out" | grep -qi "logged in"; then
    _warn "$name" "optional GitHub integration did not report a logged-in account"
    return
  fi
  _pass "$name"
}

# ----------------------------------------------------------------------------
# Check 3: token files chmod 600
# ----------------------------------------------------------------------------
check_token_perms() {
  # Same config-home resolution as vidux-config.py: XDG_CONFIG_HOME wins,
  # else ~/.config.
  local config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
  local dir="$config_home/vidux"
  local name="$dir/*.token chmod 600"
  if [[ ! -d "$dir" ]]; then
    _pass "$name (no $dir directory; nothing to check)"
    return
  fi
  # Use a glob with nullglob behavior via shopt — fall back if directory
  # has no .token files.
  shopt -s nullglob
  local tokens=( "$dir"/*.token )
  shopt -u nullglob
  if [[ ${#tokens[@]} -eq 0 ]]; then
    _pass "$name (no .token files found)"
    return
  fi
  local bad=()
  local f mode
  for f in "${tokens[@]}"; do
    # Portable stat: macOS uses -f, Linux uses -c. Try macOS form first.
    if mode="$(stat -f '%Lp' "$f" 2>/dev/null)"; then
      :
    elif mode="$(stat -c '%a' "$f" 2>/dev/null)"; then
      :
    else
      bad+=("$(basename "$f"):stat-failed")
      continue
    fi
    if [[ "$mode" != "600" ]]; then
      bad+=("$(basename "$f"):$mode")
    fi
  done
  if [[ ${#bad[@]} -gt 0 ]]; then
    _fail "$name" "non-600 perms: ${bad[*]} (fix: chmod 600 $dir/*.token)"
    return
  fi
  _pass "$name (${#tokens[@]} token file(s) verified)"
}

# ----------------------------------------------------------------------------
# Check 4: development root + observable install truth
# ----------------------------------------------------------------------------
_canonical_dir() {
  (cd -P "$1" 2>/dev/null && pwd)
}

_resolve_path_bounded() {
  # Portable realpath for an executable or skill mount. Keep the traversal
  # bounded so a symlink cycle cannot hang the doctor. This never parses `ls`
  # and does not need Python/pathlib before the Python readiness check.
  local current="$1"
  local parent target depth=0

  case "$current" in
    /*) ;;
    *) current="$(pwd)/$current" ;;
  esac

  while [[ -L "$current" ]]; do
    if [[ "$depth" -ge 40 ]]; then
      return 1
    fi
    parent="$(_canonical_dir "$(dirname "$current")")" || return 1
    target="$(readlink "$current" 2>/dev/null)" || return 1
    case "$target" in
      /*) current="$target" ;;
      *) current="$parent/$target" ;;
    esac
    depth=$((depth + 1))
  done

  parent="$(_canonical_dir "$(dirname "$current")")" || return 1
  printf '%s/%s\n' "$parent" "$(basename "$current")"
}

_read_install_version() {
  local version_file="$1/VERSION"
  local line
  if [[ ! -f "$version_file" ]]; then
    printf 'unknown\n'
    return
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      ''|'#'*) continue ;;
      *) printf '%s\n' "$line"; return ;;
    esac
  done < "$version_file"
  printf 'unknown\n'
}

check_development_dir() {
  local dev_root="${VIDUX_DEV_ROOT:-$HOME/Development}"
  local name="development root exists + install truth"
  local resolved_root git_dir_marker git_available remote_head counts
  local mount_path mount_target mount_state path_command path_target expected_target
  local mount_common mount_head mount_dirty mount_top mount_status mount_sparse
  local source_git_common="" source_head="" source_dirty="" source_sparse="" source_status=""
  local same_mounts=0 missing_mounts=0 different_mounts=0
  local summary joined issue
  local issues=()

  INSTALL_DEV_ROOT="$dev_root"
  if [[ -d "$dev_root" ]]; then
    INSTALL_DEV_ROOT_STATE="present"
  else
    INSTALL_DEV_ROOT_STATE="missing"
    issues[${#issues[@]}]="development root $dev_root not found (create it or set VIDUX_DEV_ROOT before browsing)"
  fi

  if resolved_root="$(_canonical_dir "$VIDUX_ROOT")"; then
    INSTALL_SOURCE_ROOT="$resolved_root"
  else
    INSTALL_SOURCE_ROOT="$VIDUX_ROOT"
    INSTALL_KIND="missing"
    issues[${#issues[@]}]="VIDUX_ROOT $VIDUX_ROOT does not exist"
  fi
  INSTALL_VERSION="$(_read_install_version "$VIDUX_ROOT")"

  git_dir_marker="$VIDUX_ROOT/.git"
  git_available=0
  if command -v git >/dev/null 2>&1; then
    git_available=1
  fi

  if [[ -d "$git_dir_marker" ]]; then
    INSTALL_KIND="source_checkout"
  elif [[ -f "$git_dir_marker" ]]; then
    # A linked worktree stores `gitdir: ...` in a file rather than a directory.
    INSTALL_KIND="git_worktree"
  elif [[ "$INSTALL_KIND" != "missing" ]]; then
    INSTALL_KIND="packaged"
  fi

  if [[ "$INSTALL_KIND" = "source_checkout" || "$INSTALL_KIND" = "git_worktree" ]]; then
    if [[ "$git_available" -ne 1 ]]; then
      INSTALL_UPSTREAM_STATE="unavailable"
      issues[${#issues[@]}]="source install found but git is unavailable on PATH"
    elif [[ "$(git -C "$VIDUX_ROOT" rev-parse --is-inside-work-tree 2>/dev/null || true)" != "true" ]]; then
      INSTALL_UPSTREAM_STATE="unavailable"
      issues[${#issues[@]}]="source install Git metadata is unreadable"
    else
      INSTALL_SHA="$(git -C "$VIDUX_ROOT" rev-parse --short=12 HEAD 2>/dev/null || true)"
      INSTALL_BRANCH="$(git -C "$VIDUX_ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
      if [[ -z "$INSTALL_BRANCH" ]]; then
        INSTALL_BRANCH="detached"
        issues[${#issues[@]}]="checkout is detached/pinned at ${INSTALL_SHA:-unknown}"
      fi

      # Cached-ref only. In particular, never call fetch/pull/remote update:
      # freshness means "relative to what this checkout has already fetched."
      # Prefer the branch's configured upstream, then cached origin/HEAD,
      # then origin/main.
      branch_upstream="$(git -C "$VIDUX_ROOT" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
      remote_head="$(git -C "$VIDUX_ROOT" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
      if [[ -n "$branch_upstream" ]] && git -C "$VIDUX_ROOT" rev-parse --verify --quiet "${branch_upstream}^{commit}" >/dev/null 2>&1; then
        INSTALL_UPSTREAM_REF="$branch_upstream"
      elif [[ -n "$remote_head" ]] && git -C "$VIDUX_ROOT" rev-parse --verify --quiet "${remote_head}^{commit}" >/dev/null 2>&1; then
        INSTALL_UPSTREAM_REF="$remote_head"
      elif git -C "$VIDUX_ROOT" rev-parse --verify --quiet 'origin/main^{commit}' >/dev/null 2>&1; then
        INSTALL_UPSTREAM_REF="origin/main"
      fi

      if [[ -n "$INSTALL_UPSTREAM_REF" && -n "$INSTALL_SHA" ]]; then
        counts="$(git -C "$VIDUX_ROOT" rev-list --left-right --count "HEAD...${INSTALL_UPSTREAM_REF}" 2>/dev/null || true)"
        if [[ "$counts" =~ ^[[:space:]]*([0-9]+)[[:space:]]+([0-9]+)[[:space:]]*$ ]]; then
          INSTALL_AHEAD="${BASH_REMATCH[1]}"
          INSTALL_BEHIND="${BASH_REMATCH[2]}"
          if [[ "$INSTALL_AHEAD" -gt 0 && "$INSTALL_BEHIND" -gt 0 ]]; then
            INSTALL_UPSTREAM_STATE="diverged"
            issues[${#issues[@]}]="checkout diverged from cached $INSTALL_UPSTREAM_REF (ahead=$INSTALL_AHEAD behind=$INSTALL_BEHIND)"
          elif [[ "$INSTALL_BEHIND" -gt 0 ]]; then
            INSTALL_UPSTREAM_STATE="behind"
            issues[${#issues[@]}]="checkout is behind cached $INSTALL_UPSTREAM_REF by $INSTALL_BEHIND commit(s)"
          elif [[ "$INSTALL_AHEAD" -gt 0 ]]; then
            # Ahead is observable but not stale: the local checkout may be the
            # source-under-test before publication. Detached/diverged remains a
            # warning independently.
            INSTALL_UPSTREAM_STATE="ahead"
          else
            INSTALL_UPSTREAM_STATE="same"
          fi
        else
          INSTALL_UPSTREAM_STATE="unavailable"
          issues[${#issues[@]}]="could not compare HEAD with cached $INSTALL_UPSTREAM_REF"
        fi
      else
        INSTALL_UPSTREAM_STATE="unavailable"
        issues[${#issues[@]}]="no upstream, cached origin/HEAD, or origin/main ref; freshness is unknown"
      fi
    fi
  elif [[ "$INSTALL_KIND" = "packaged" ]]; then
    INSTALL_BRANCH="packaged"
    INSTALL_UPSTREAM_STATE="not_applicable"
  fi

  # bin/vidux exports the expected executable path. Direct script invocation
  # intentionally reports not_checked rather than guessing which shell alias
  # or wrapper launched it.
  if [[ -n "${VIDUX_DOCTOR_EXPECTED_CLI:-}" ]]; then
    path_command="$(command -v vidux 2>/dev/null || true)"
    INSTALL_PATH_COMMAND="$path_command"
    if [[ -z "$path_command" ]]; then
      INSTALL_PATH_STATE="missing"
      issues[${#issues[@]}]="vidux is not available on PATH"
    elif [[ "$path_command" != */* ]]; then
      INSTALL_PATH_STATE="different_source"
      issues[${#issues[@]}]="PATH resolves vidux to non-file command $path_command"
    else
      path_target="$(_resolve_path_bounded "$path_command" 2>/dev/null || true)"
      expected_target="$(_resolve_path_bounded "$VIDUX_DOCTOR_EXPECTED_CLI" 2>/dev/null || true)"
      INSTALL_PATH_TARGET="$path_target"
      if [[ -n "$path_target" && -n "$expected_target" && "$path_target" = "$expected_target" ]]; then
        INSTALL_PATH_STATE="same_source"
      else
        INSTALL_PATH_STATE="different_source"
        issues[${#issues[@]}]="PATH vidux target ${path_target:-unresolved} differs from source ${expected_target:-unresolved}"
      fi
    fi
  fi

  # Optional skill mounts. Absence is healthy: a CLI-only/package install need
  # not register every agent surface. A present mount must serve this same
  # source's bytes, or equal version strings can conceal stale bytes. Path
  # equality is only a proxy for that: a linked worktree of this repository
  # (the documented clean-mirror layout) serves identical bytes whenever it
  # sits on the same object store at the same clean HEAD, so compare content
  # identity before declaring a foreign source.
  if [[ "$INSTALL_KIND" = "source_checkout" || "$INSTALL_KIND" = "git_worktree" ]] && [[ "$git_available" -eq 1 ]]; then
    source_git_common="$(git -C "$VIDUX_ROOT" rev-parse --git-common-dir 2>/dev/null || true)"
    if [[ -n "$source_git_common" && "$source_git_common" != /* ]]; then
      source_git_common="$VIDUX_ROOT/$source_git_common"
    fi
    source_git_common="$(_resolve_path_bounded "$source_git_common" 2>/dev/null || true)"
    source_head="$(git -C "$VIDUX_ROOT" rev-parse HEAD 2>/dev/null || true)"
    # Byte-identity needs both sides clean and non-sparse; a status failure is
    # unknown, never clean.
    if source_status="$(git -C "$VIDUX_ROOT" status --porcelain 2>/dev/null)"; then
      source_dirty="$(printf '%s' "$source_status" | head -n 1)"
    else
      source_dirty="__status_unavailable__"
    fi
    source_sparse="$(git -C "$VIDUX_ROOT" config --get core.sparseCheckout 2>/dev/null || true)"
  fi
  local common_mounts=(
    "$HOME/.claude/skills/vidux"
    "$HOME/.codex/skills/vidux"
    "$HOME/.agents/skills/vidux"
    "$HOME/.ai/skills-active/vidux"
    "$HOME/.ai/skills-active-dir/vidux"
  )
  for mount_path in "${common_mounts[@]}"; do
    mount_target=""
    if [[ ! -e "$mount_path" && ! -L "$mount_path" ]]; then
      mount_state="missing"
      missing_mounts=$((missing_mounts + 1))
    else
      mount_target="$(_resolve_path_bounded "$mount_path" 2>/dev/null || true)"
      mount_common=""
      mount_head=""
      mount_dirty=""
      if [[ -n "$mount_target" && "$mount_target" = "$INSTALL_SOURCE_ROOT" ]]; then
        mount_state="same_source"
        same_mounts=$((same_mounts + 1))
      else
        if [[ -n "$mount_target" && -n "$source_git_common" && -d "$mount_target" ]]; then
          mount_common="$(git -C "$mount_target" rev-parse --git-common-dir 2>/dev/null || true)"
          if [[ -n "$mount_common" && "$mount_common" != /* ]]; then
            mount_common="$mount_target/$mount_common"
          fi
          mount_common="$(_resolve_path_bounded "$mount_common" 2>/dev/null || true)"
        fi
        if [[ -n "$mount_common" && "$mount_common" = "$source_git_common" ]]; then
          mount_top="$(git -C "$mount_target" rev-parse --show-toplevel 2>/dev/null || true)"
          mount_top="$(_resolve_path_bounded "$mount_top" 2>/dev/null || true)"
          mount_head="$(git -C "$mount_target" rev-parse HEAD 2>/dev/null || true)"
          if mount_status="$(git -C "$mount_target" status --porcelain 2>/dev/null)"; then
            mount_dirty="$(printf '%s' "$mount_status" | head -n 1)"
          else
            mount_dirty="__status_unavailable__"
          fi
          mount_sparse="$(git -C "$mount_target" config --get core.sparseCheckout 2>/dev/null || true)"
          if [[ -z "$mount_top" || "$mount_top" != "$mount_target" ]]; then
            # A path inside the repository is not the repository: a subtree
            # mount serves only part of the source and stays a foreign source.
            mount_state="different_source"
            different_mounts=$((different_mounts + 1))
            issues[${#issues[@]}]="skill mount $mount_path resolves inside a worktree of this repository (${mount_target}), not a worktree root"
          elif [[ -n "$mount_head" && "$mount_head" = "$source_head" \
              && -z "$mount_dirty" && -z "$source_dirty" \
              && "$mount_sparse" != "true" && "$source_sparse" != "true" ]]; then
            # A linked worktree of this repository at the same HEAD, with both
            # trees clean and non-sparse, is byte-identical to the source:
            # same source, different path.
            mount_state="same_source"
            same_mounts=$((same_mounts + 1))
          else
            mount_state="same_repo_stale"
            different_mounts=$((different_mounts + 1))
            if [[ -n "$mount_head" && "$mount_head" != "$source_head" ]]; then
              issues[${#issues[@]}]="skill mount $mount_path is a worktree of this repository pinned at ${mount_head:0:12}, while the source checkout is at ${source_head:0:12}"
            elif [[ "$mount_dirty" = "__status_unavailable__" || "$source_dirty" = "__status_unavailable__" ]]; then
              issues[${#issues[@]}]="skill mount $mount_path is a worktree of this repository but git status is unreadable, so byte identity cannot be confirmed"
            elif [[ "$mount_sparse" = "true" || "$source_sparse" = "true" ]]; then
              issues[${#issues[@]}]="skill mount $mount_path involves a sparse checkout, so its tree may not match the full source tree"
            elif [[ -n "$source_dirty" ]]; then
              issues[${#issues[@]}]="skill mount $mount_path serves this repository's clean HEAD, but the source checkout has local modifications the mount does not see"
            else
              issues[${#issues[@]}]="skill mount $mount_path is a worktree of this repository with local modifications, so its bytes may differ from the source checkout"
            fi
          fi
        else
          mount_state="different_source"
          different_mounts=$((different_mounts + 1))
          issues[${#issues[@]}]="skill mount $mount_path resolves to ${mount_target:-unresolved}, not $INSTALL_SOURCE_ROOT"
        fi
      fi
    fi
    MOUNT_PATHS[${#MOUNT_PATHS[@]}]="$mount_path"
    MOUNT_STATES[${#MOUNT_STATES[@]}]="$mount_state"
    MOUNT_TARGETS[${#MOUNT_TARGETS[@]}]="$mount_target"
  done

  summary="kind=$INSTALL_KIND source=$INSTALL_SOURCE_ROOT version=$INSTALL_VERSION"
  if [[ -n "$INSTALL_SHA" ]]; then
    summary="$summary sha=$INSTALL_SHA branch=$INSTALL_BRANCH upstream=${INSTALL_UPSTREAM_REF:-none} freshness=$INSTALL_UPSTREAM_STATE ahead=${INSTALL_AHEAD:-n/a} behind=${INSTALL_BEHIND:-n/a}"
  fi
  summary="$summary path=$INSTALL_PATH_STATE mounts=same:$same_mounts,missing:$missing_mounts,different:$different_mounts"

  if [[ ${#issues[@]} -gt 0 ]]; then
    joined=""
    for issue in "${issues[@]}"; do
      if [[ -n "$joined" ]]; then
        joined="$joined; $issue"
      else
        joined="$issue"
      fi
    done
    INSTALL_STATUS="warn"
    _warn "$name" "$joined; $summary"
    return
  fi

  INSTALL_STATUS="pass"
  _pass "$name ($summary)"
}

# ----------------------------------------------------------------------------
# Check 5: stale browser pidfile
# ----------------------------------------------------------------------------
check_stale_browser_pidfile() {
  local name="no stale browser pidfile"
  # macOS TMPDIR has a trailing slash; strip it before joining the basename
  # so the resulting path is clean (e.g. /var/.../T/vidux-browser.pid).
  local tmp="${TMPDIR:-/tmp}"
  tmp="${tmp%/}"
  local pidfile="${tmp}/vidux-browser.pid"
  if [[ ! -f "$pidfile" ]]; then
    _pass "$name (no pidfile at $pidfile)"
    return
  fi
  local pid
  pid="$(tr -d '[:space:]' < "$pidfile" 2>/dev/null || true)"
  if [[ -z "$pid" ]]; then
    _warn "$name" "stale residue: pidfile $pidfile is empty (remove it when safe)"
    return
  fi
  if ! [[ "$pid" =~ ^[0-9]+$ ]]; then
    _warn "$name" "stale residue: pidfile $pidfile contains non-numeric content (remove it when safe)"
    return
  fi
  # `kill -0` returns 0 if the process exists and the caller may signal it.
  # On macOS / Linux it also returns 0 for processes we cannot signal but
  # which exist, so a true 0 is "alive enough".
  if kill -0 "$pid" 2>/dev/null; then
    _pass "$name (pid $pid alive)"
    return
  fi
  _warn "$name" "stale residue: pidfile $pidfile points to dead pid $pid (remove it when safe)"
}

# ----------------------------------------------------------------------------
# Check 6: config check
# ----------------------------------------------------------------------------
check_vidux_config() {
  local name="config check"
  if [[ ! -d "$VIDUX_ROOT" ]]; then
    _fail "$name" "VIDUX_ROOT $VIDUX_ROOT does not exist"
    return
  fi
  if [[ ! -f "$VIDUX_ROOT/scripts/vidux-config.py" ]]; then
    _fail "$name" "$VIDUX_ROOT/scripts/vidux-config.py missing"
    return
  fi
  local out rc
  set +e
  out="$(cd "$VIDUX_ROOT" && python3 "$VIDUX_ROOT/scripts/vidux-config.py" check --json 2>&1)"
  rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    local reason
    reason="$(printf '%s\n' "$out" | python3 -c 'import json,sys
try:
    payload=json.load(sys.stdin)
    issues=payload.get("issues") or []
    if issues:
        first=issues[0]
        code=first.get("code", "error")
        message=first.get("message", "config check failed")
        print(f"{code}: {message}")
    else:
        print(payload.get("status", "config check failed"))
except Exception:
    print("config check failed")
' 2>/dev/null || true)"
    [[ -z "$reason" ]] && reason="config check exited $rc"
    _fail "$name" "$reason"
    return
  fi
  local source live using_example
  source="$(printf '%s\n' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("source", "unknown"))' 2>/dev/null || true)"
  live="$(printf '%s\n' "$out" | python3 -c 'import json,sys; print("yes" if json.load(sys.stdin).get("live_config_present") else "no")' 2>/dev/null || true)"
  using_example="$(printf '%s\n' "$out" | python3 -c 'import json,sys; print("yes" if json.load(sys.stdin).get("using_example") else "no")' 2>/dev/null || true)"
  [[ -z "$source" ]] && source="unknown"
  [[ -z "$live" ]] && live="unknown"
  [[ -z "$using_example" ]] && using_example="unknown"
  _pass "$name (source=$source live=$live example=$using_example)"
}

# ----------------------------------------------------------------------------
# Check 7: npm test (contract suite)
# ----------------------------------------------------------------------------
check_npm_test() {
  local name="npm test (contract suite)"
  if [[ "$SKIP_NPM_TEST" = "1" ]]; then
    _pass "$name (skipped via VIDUX_DOCTOR_SKIP_NPM_TEST=1)"
    return
  fi
  if [[ ! -d "$VIDUX_ROOT" ]]; then
    _fail "$name" "VIDUX_ROOT $VIDUX_ROOT does not exist"
    return
  fi
  if [[ ! -f "$VIDUX_ROOT/package.json" ]]; then
    _fail "$name" "$VIDUX_ROOT/package.json missing"
    return
  fi
  if [[ ! -d "$VIDUX_ROOT/.git" && ! -f "$VIDUX_ROOT/.git" ]]; then
    _warn "$name" "source-only check unavailable in packaged install; release package verification ran before publish"
    return
  fi
  if [[ ! -d "$VIDUX_ROOT/tests" ]]; then
    _fail "$name" "source checkout tests/ directory missing"
    return
  fi
  if [[ ! -d "$VIDUX_ROOT/node_modules" ]]; then
    # A fresh clone before `npm ci` is a normal state, not a broken install.
    _warn "$name" "node_modules missing; run 'npm ci' then re-run doctor to execute the suite"
    return
  fi
  if ! command -v npm >/dev/null 2>&1; then
    _fail "$name" "npm not found on PATH"
    return
  fi
  local out rc
  # Capture output and exit code; on success show test count, on failure
  # surface the first failing line.
  set +e
  # The outer `vidux doctor` exports this path only so this process can verify
  # the installed CLI identity. Do not leak that host-specific expectation into
  # the nested contract suite: its hermetic fixtures intentionally construct
  # different roots and CLI paths.
  out="$(cd "$VIDUX_ROOT" && unset VIDUX_DOCTOR_EXPECTED_CLI && npm test 2>&1)"
  rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    local first_fail
    first_fail="$(printf '%s\n' "$out" | grep -E '^(FAIL|ERROR|FAILED)' | head -1 || true)"
    [[ -z "$first_fail" ]] && first_fail="exit code $rc"
    _fail "$name" "$first_fail"
    return
  fi
  # Look for the unittest summary like "Ran 182 tests in" to surface the count.
  local count
  count="$(printf '%s\n' "$out" | grep -oE 'Ran [0-9]+ tests' | tail -1 || true)"
  if [[ -n "$count" ]]; then
    _pass "$name ($count)"
  else
    _pass "$name"
  fi
}

_emit_json() {
  local overall_status="pass"
  local ok=true strict_ok=true warning_only=false
  local index
  if [[ "$FAIL_COUNT" -gt 0 ]]; then
    overall_status="fail"
    ok=false
    strict_ok=false
  elif [[ "$WARN_COUNT" -gt 0 ]]; then
    overall_status="warn"
    strict_ok=false
    warning_only=true
  fi

  printf '{'
  printf '"status":'; _json_quote "$overall_status"
  printf ',"ok":%s,"strict_ok":%s,"warning_only":%s' "$ok" "$strict_ok" "$warning_only"
  printf ',"summary":{"total":%d,"passed":%d,"warnings":%d,"failures":%d}' \
    "$TOTAL" "$PASS_COUNT" "$WARN_COUNT" "$FAIL_COUNT"
  printf ',"install":{'
  printf '"status":'; _json_quote "$INSTALL_STATUS"
  printf ',"kind":'; _json_quote "$INSTALL_KIND"
  printf ',"source_root":'; _json_nullable_string "$INSTALL_SOURCE_ROOT"
  printf ',"version":'; _json_quote "$INSTALL_VERSION"
  printf ',"sha":'; _json_nullable_string "$INSTALL_SHA"
  printf ',"branch":'; _json_nullable_string "$INSTALL_BRANCH"
  printf ',"development_root":{"path":'; _json_nullable_string "$INSTALL_DEV_ROOT"
  printf ',"state":'; _json_quote "$INSTALL_DEV_ROOT_STATE"
  printf '}'
  printf ',"cached_upstream":{"ref":'; _json_nullable_string "$INSTALL_UPSTREAM_REF"
  printf ',"state":'; _json_quote "$INSTALL_UPSTREAM_STATE"
  printf ',"ahead":'
  if [[ -n "$INSTALL_AHEAD" ]]; then printf '%d' "$INSTALL_AHEAD"; else printf 'null'; fi
  printf ',"behind":'
  if [[ -n "$INSTALL_BEHIND" ]]; then printf '%d' "$INSTALL_BEHIND"; else printf 'null'; fi
  printf '}'
  printf ',"path":{"command":'; _json_nullable_string "$INSTALL_PATH_COMMAND"
  printf ',"target":'; _json_nullable_string "$INSTALL_PATH_TARGET"
  printf ',"state":'; _json_quote "$INSTALL_PATH_STATE"
  printf '}'
  printf ',"skill_mounts":['
  for ((index = 0; index < ${#MOUNT_PATHS[@]}; index++)); do
    if [[ "$index" -gt 0 ]]; then printf ','; fi
    printf '{"path":'; _json_quote "${MOUNT_PATHS[$index]}"
    printf ',"state":'; _json_quote "${MOUNT_STATES[$index]}"
    printf ',"target":'; _json_nullable_string "${MOUNT_TARGETS[$index]}"
    printf '}'
  done
  printf ']}'
  printf ',"checks":['
  for ((index = 0; index < ${#CHECK_STATUSES[@]}; index++)); do
    if [[ "$index" -gt 0 ]]; then printf ','; fi
    printf '{"status":'; _json_quote "${CHECK_STATUSES[$index]}"
    printf ',"message":'; _json_quote "${CHECK_MESSAGES[$index]}"
    printf '}'
  done
  printf ']}\n'
}

# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
check_python_version
check_gh_auth
check_token_perms
check_development_dir
check_stale_browser_pidfile
check_vidux_config
check_npm_test

if [[ "$OUTPUT_JSON" -eq 1 ]]; then
  _emit_json
else
  echo ""
  # Report every non-pass tally, not warnings only. Omitting the failure count
  # let a hard [FAIL] hide behind a "N/M checks passed, K warning(s)" line whose
  # bottom-line glance read as clean even though the exit code was 1.
  summary_line="${PASS_COUNT}/${TOTAL} checks passed"
  if [[ "$WARN_COUNT" -gt 0 ]]; then
    summary_line="${summary_line}, ${WARN_COUNT} warning(s)"
  fi
  if [[ "$FAIL_COUNT" -gt 0 ]]; then
    summary_line="${summary_line}, ${FAIL_COUNT} failure(s)"
  fi
  echo "$summary_line"
fi

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  exit 1
fi
exit 0
