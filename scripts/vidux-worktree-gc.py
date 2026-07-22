#!/usr/bin/env python3
"""Classify and optionally remove safe Vidux automation worktrees.

Default mode is read-only. `--apply --yes` removes only clean, non-primary
worktrees whose branch is already merged into the base or whose PR is merged.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SAFE_BUCKET = "merged_clean"
OWNER_REVIEW_BUCKETS = {
    "closed_unmerged",
    "dirty",
    "open_pr",
    "unknown",
    "unmerged_no_pr",
}

# `git status --porcelain` (used by dirty_file_count below) never reports
# gitignored paths -- that's correct default git behavior, but it means a
# worktree with real uncommitted content sitting under a gitignored path
# (a stray .env, a scratch note, anything not git-added) reads as clean and
# gets silently destroyed by `git worktree remove` (which has the same
# blind spot, so it doesn't even require --force). Only content matching
# these well-known regenerable-artifact patterns is safe to ignore for this
# check; anything else gitignored-but-present blocks auto-removal.
#
# Trusting an ENTIRE directory by name is only safe for names no human would
# ever pick to store real content in -- and getting this wrong is real,
# permanent data loss via the `--apply --yes` path. "dist"/"build"/"target"/
# "vendor" are common English/business words as well as build-tool
# conventions, so blanket-trusting them was never actually safe. An earlier
# attempt (an allowlist of "human-authored" suffixes that override the
# directory trust) just moved the same failure mode one layer down: it
# missed extensionless files (Path('AUTHORS').suffix == '') and
# case-variant extensions (.PDF vs .pdf), both of which caused permanent
# deletion. No suffix-based denylist of "things that look human" can ever be
# exhaustive -- the only durable fix is to stop blanket-trusting ambiguous
# directory names at all. UNAMBIGUOUS_REGENERABLE_DIR_NAMES (dirs no human
# ever hand-populates with real content -- exclusively package-manager/tool
# managed) keep full-directory trust with no per-file check, same as
# before. Everything else -- including former members dist/build/target/
# vendor -- gets zero directory-based trust; a file there is only skipped
# if it individually matches REGENERABLE_IGNORED_FILE_SUFFIXES/NAMES below.
# This trades some manual-review false positives (a real dist/ full of
# genuine build output now needs owner review instead of auto-cleanup) for
# eliminating the false-negative/data-loss direction entirely -- the correct
# trade for a tool whose failure mode is irreversible deletion.
# "no human
# ever hand-populates" above is not literally true for node_modules under
# the common `patch-package` workflow, where a developer DOES hand-edit a
# file inside node_modules/ and commits the resulting .patch alongside it.
# The design still deletes that content on --apply: node_modules is
# regenerable by `npm install` from the committed .patch + package.json, so
# the underlying intent (the patch itself) survives even though the
# ephemeral worktree copy doesn't. This is consistent with the tier's
# purpose -- these are the directories a package manager fully owns and can
# reproduce -- but is worth knowing before adding a new name here.
#
# ACCEPTED RESIDUAL RISK (P0, reproduced, no code fix exists): on a
# case-insensitive-but-case-preserving filesystem (APFS/macOS default, also
# Windows), `mkdir("Node_Modules/x")` when `node_modules/` already exists
# does not create a second directory -- it silently succeeds by resolving
# into the SAME existing inode, with no error. Reproduced: after `mkdir
# node_modules; mkdir -p Node_Modules/nested; echo x >
# Node_Modules/nested/human-note.txt`, both `ls`/`find` AND `git status
# --porcelain --ignored` report the human file at
# `node_modules/nested/human-note.txt` -- the TRUE, correctly-cased, on-disk
# path. This means `rel_path.parts[0]` here is not lying and is not
# case-folded; it faithfully reports "node_modules", so the directory-trust
# check below is not buggy in isolation. The obvious proposed fix ("verify
# the real on-disk directory name via os.scandir instead of trusting git's
# output") was tested against this exact repro and does nothing: `os.scandir`
# reports the identical single "node_modules" entry git already reported,
# because there never was a second, differently-cased directory to
# distinguish -- the filesystem merged them before either tool ever looked.
# Once merged, there is no remaining filesystem metadata recording which path
# a given file was originally created through, so no introspection-based
# check (this script or any other) can tell a human-deposited file in this
# state apart from genuine package-manager output after the fact. The only
# mitigations that would actually close this are (a) disable directory-level
# blanket trust entirely whenever the worktree's filesystem is
# case-insensitive -- which would force manual review of every
# node_modules/__pycache__/.venv/etc. on every macOS/Windows machine,
# defeating this tier's purpose on its primary runtime platform, or (b) a
# content-heuristic denylist -- already established above as never
# exhaustive. Neither is a clean fix; this is left as a documented, narrow,
# accepted residual risk (it requires a coincidental case-varied write into a
# name that ALSO exact-matches an UNAMBIGUOUS_REGENERABLE_DIR_NAMES entry)
# pending an explicit maintainer call on whether the manual-review cost of
# option (a) is worth paying.
UNAMBIGUOUS_REGENERABLE_DIR_NAMES = {
    "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv",
    ".next", ".turbo", ".mypy_cache", ".ruff_cache",
}
# Only the compiled-bytecode suffixes: never a plausible hand-authored
# filename regardless of location. `.log` was once trusted here too, but a
# hand-authored `cache/diary.log` (a diary, meeting notes) is an entirely
# plausible real filename inside a directory that isn't one of the
# unambiguous names above -- and was reproduced causing permanent deletion.
# `.log` files are still trusted when they sit inside an unambiguous directory
# (via the directory check below), same as any other file there; this only
# removes the blanket trust for `.log` OUTSIDE one.
REGENERABLE_IGNORED_FILE_SUFFIXES = {".pyc", ".pyo"}
REGENERABLE_IGNORED_FILE_NAMES = {".DS_Store"}


class CommandError(RuntimeError):
    def __init__(self, command: List[str], returncode: int, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"{' '.join(command)} exited {returncode}: {self.stderr}")


@dataclass
class PullRequestInfo:
    number: int
    state: str
    head_ref_name: str
    head_ref_oid: Optional[str]
    title: str
    is_draft: bool
    url: str
    merged_at: Optional[str]
    closed_at: Optional[str]


@dataclass
class WorktreeInfo:
    path: str
    branch: Optional[str]
    head: Optional[str]
    bucket: str
    dirty_files: int
    ignored_risk_files: List[str]
    commits_not_in_base: Optional[int]
    last_commit_subject: Optional[str]
    last_commit_date: Optional[str]
    last_commit_age_days: Optional[int]
    is_primary: bool
    in_base: bool
    removable: bool
    pr_number: Optional[int]
    pr_state: Optional[str]
    pr_url: Optional[str]
    reason: str
    next_owner_action: str
    review_command: str


def run(command: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        # load_prs() shells out to `gh` unconditionally
        # and only guarded against non-zero exit codes -- a missing `gh`
        # executable raised FileNotFoundError here, uncaught, before any
        # classification was attempted. This script is documented for direct
        # invocation with zero mention that `gh` is a prerequisite. 127
        # ("command not found") lets existing `check=False` callers handle
        # it via their normal returncode!=0 path with no call-site changes.
        result = subprocess.CompletedProcess(
            command, 127, stdout="", stderr=f"{command[0]}: command not found ({exc})",
        )
    if check and result.returncode != 0:
        raise CommandError(command, result.returncode, result.stderr)
    return result


def repo_root(repo: Path) -> Path:
    result = run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"])
    return Path(result.stdout.strip()).resolve()


def parse_worktree_list(text: str) -> List[Dict[str, Any]]:
    worktrees: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}

    def flush() -> None:
        nonlocal current
        if current:
            worktrees.append(current)
            current = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            flush()
            current["path"] = value
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = short_branch(value)
        elif key == "detached":
            current["detached"] = True
        elif key == "bare":
            current["bare"] = True
    flush()
    return worktrees


def short_branch(ref: str) -> str:
    prefix = "refs/heads/"
    if ref.startswith(prefix):
        return ref[len(prefix) :]
    return ref


def load_worktrees(repo: Path) -> List[Dict[str, Any]]:
    result = run(["git", "-C", str(repo), "worktree", "list", "--porcelain"])
    return parse_worktree_list(result.stdout)


def dirty_file_count(path: Path) -> int:
    result = run(["git", "-C", str(path), "status", "--porcelain"], check=True)
    return len([line for line in result.stdout.splitlines() if line.strip()])


def non_regenerable_ignored_paths(path: Path) -> List[str]:
    """Gitignored-but-present paths NOT matching a known regenerable-artifact
    pattern. Non-empty means real content `git status --porcelain` and git's
    own worktree-remove dirty-check both silently miss -- see the module-level
    comment on UNAMBIGUOUS_REGENERABLE_DIR_NAMES for why this exists and why
    directory-name trust is now tiered rather than a single denylist-overridable
    allowlist.

    Uses `-z --ignored --untracked-files=all` rather than the plain
    `--ignored` default for two reasons:
    (1) `-z` emits NUL-terminated, unquoted paths -- the default mode
    C-style-quotes any path with a space or special character, which would
    silently defeat exact-match suffix/name checks; (2) without
    `--untracked-files=all`, git collapses a wholly-ignored directory into
    one summary line instead of listing its contents (confirmed empirically
    -- `--ignored=matching` alone does NOT fix this for a directory-pattern
    ignore rule like `build/`; `--untracked-files=all` is the flag that
    actually forces per-file recursion).

    Directory-name trust checks ONLY `rel_path.parts[0]` (the outermost
    path segment relative to the worktree root), not any ancestor segment.
    Reproduced causing permanent deletion: checking
    `any(part in UNAMBIGUOUS_REGENERABLE_DIR_NAMES for part in
    rel_path.parts[:-1])` matches a trusted name ANYWHERE in the path, so
    `stuff/node_modules/IMPORTANT.txt` -- where `stuff/` is itself
    gitignored and is NOT an unambiguous name -- was fully trusted purely
    because "node_modules" appears somewhere in its ancestry, even though
    the actual ignored boundary is `stuff/`, an untrusted name. Restricting
    to parts[0] means a file is only trusted when the outermost gitignored
    container itself is one of the unambiguous names -- a legitimate
    deeply-nested node_modules (e.g. `packages/foo/node_modules/bar.js` in
    a monorepo) now requires manual review instead of auto-cleanup, which
    is the accepted trade (more false-positive manual review, zero
    false-negative data loss) already established for the ambiguous tier."""
    result = run(
        [
            "git", "-C", str(path), "status", "--porcelain", "-z",
            "--ignored", "--untracked-files=all",
        ],
        check=True,
    )
    risky: List[str] = []
    for entry in result.stdout.split("\0"):
        if not entry or not entry.startswith("!!"):
            continue
        rel = entry[3:]
        rel_path = Path(rel)
        if rel_path.name in REGENERABLE_IGNORED_FILE_NAMES:
            continue
        if rel_path.suffix in REGENERABLE_IGNORED_FILE_SUFFIXES:
            continue
        if rel_path.parts[0] in UNAMBIGUOUS_REGENERABLE_DIR_NAMES:
            continue
        risky.append(rel)
    return risky


def is_ancestor(repo: Path, head: Optional[str], base: str) -> bool:
    if not head:
        return False
    result = run(["git", "-C", str(repo), "merge-base", "--is-ancestor", head, base], check=False)
    return result.returncode == 0


def commit_count_not_in_base(repo: Path, head: Optional[str], base: str, warnings: List[str]) -> Optional[int]:
    if not head:
        return None
    result = run(["git", "-C", str(repo), "rev-list", "--count", f"{base}..{head}"], check=False)
    if result.returncode != 0:
        warnings.append(
            "could not count commits not in "
            f"{base} for {head[:12]}: {result.stderr.strip() or 'git rev-list failed'}"
        )
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        warnings.append(f"could not parse commit count for {head[:12]}: {result.stdout.strip()}")
        return None


def last_commit_subject(repo: Path, head: Optional[str], warnings: List[str]) -> Optional[str]:
    if not head:
        return None
    result = run(["git", "-C", str(repo), "log", "-1", "--format=%s", head], check=False)
    if result.returncode != 0:
        warnings.append(
            f"could not read last commit subject for {head[:12]}: "
            f"{result.stderr.strip() or 'git log failed'}"
        )
        return None
    return result.stdout.strip() or None


def last_commit_date(repo: Path, head: Optional[str], warnings: List[str]) -> Optional[str]:
    if not head:
        return None
    result = run(["git", "-C", str(repo), "log", "-1", "--format=%cI", head], check=False)
    if result.returncode != 0:
        warnings.append(
            f"could not read last commit date for {head[:12]}: "
            f"{result.stderr.strip() or 'git log failed'}"
        )
        return None
    return result.stdout.strip() or None


def commit_age_days(commit_date: Optional[str], warnings: List[str], head: Optional[str]) -> Optional[int]:
    if not commit_date:
        return None
    try:
        parsed = datetime.fromisoformat(commit_date.replace("Z", "+00:00"))
    except ValueError:
        label = head[:12] if head else "unknown"
        warnings.append(f"could not parse last commit date for {label}: {commit_date}")
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    return max(0, int(delta.total_seconds() // 86400))


def next_owner_action_for_bucket(bucket: str) -> str:
    actions = {
        "primary": "skip; primary and invocation checkouts are protected",
        SAFE_BUCKET: "eligible for guarded removal after owner approval with --apply --yes",
        "open_pr": "review the PR; merge or close it before cleanup",
        "dirty": "preserve WIP; ask the owner to commit, stash, or abandon it before cleanup",
        "closed_unmerged": "owner review required; archive, revive, or manually remove the abandoned branch",
        "unmerged_no_pr": "owner review required; open a PR, merge, or archive the branch",
        "unknown": "repair classifier warnings before cleanup",
    }
    return actions.get(bucket, "owner review required before cleanup")


def review_command_for_worktree(path: Path, repo: Path, bucket: str, base: str, pr: Optional[PullRequestInfo]) -> str:
    """Return a read-only command that helps the owner decide a non-removable row."""
    if pr and bucket in {"open_pr", "closed_unmerged"}:
        return shlex.join(
            [
                "gh",
                "pr",
                "view",
                str(pr.number),
                "--json",
                "number,state,isDraft,mergeStateStatus,mergedAt,closedAt,headRefName,url,title",
            ]
        )
    if bucket == "dirty":
        return shlex.join(["git", "-C", str(path), "status", "--short"])
    if bucket == "unmerged_no_pr":
        return shlex.join(["git", "-C", str(path), "log", "--oneline", "--decorate", "--max-count=20", f"{base}..HEAD"])
    if bucket == "unknown":
        return shlex.join(["git", "-C", str(path), "status", "--short"])
    if bucket == SAFE_BUCKET:
        return shlex.join(["python3", "scripts/vidux-worktree-gc.py", "--base", base, "--apply", "--yes", str(repo)])
    return "no read-only review command available"


def select_best_pr(prs_by_key: Dict[str, List[PullRequestInfo]]) -> Dict[str, PullRequestInfo]:
    priority = {"OPEN": 0, "MERGED": 1, "CLOSED": 2}
    selected: Dict[str, PullRequestInfo] = {}
    for key, prs in prs_by_key.items():
        prs.sort(key=lambda pr: (priority.get(pr.state, 9), -pr.number))
        selected[key] = prs[0]
    return selected


def load_prs(
    repo: Path,
    limit: int,
) -> Tuple[Dict[str, PullRequestInfo], Dict[str, PullRequestInfo], Optional[str]]:
    command = [
        "gh",
        "pr",
        "list",
        "--state",
        "all",
        "--limit",
        str(limit),
        "--json",
        "number,state,title,headRefName,headRefOid,isDraft,url,mergedAt,closedAt",
    ]
    result = run(command, cwd=repo, check=False)
    if result.returncode != 0:
        return {}, {}, result.stderr.strip() or "gh pr list failed"

    try:
        raw_prs = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        return {}, {}, f"could not parse gh pr list JSON: {exc}"

    prs_by_branch: Dict[str, List[PullRequestInfo]] = {}
    prs_by_head: Dict[str, List[PullRequestInfo]] = {}
    for raw in raw_prs:
        head_ref = raw.get("headRefName") or ""
        head_ref_oid = raw.get("headRefOid") or ""
        if not head_ref and not head_ref_oid:
            continue
        pr = PullRequestInfo(
            number=int(raw.get("number") or 0),
            state=str(raw.get("state") or "").upper(),
            head_ref_name=head_ref,
            head_ref_oid=head_ref_oid or None,
            title=str(raw.get("title") or ""),
            is_draft=bool(raw.get("isDraft")),
            url=str(raw.get("url") or ""),
            merged_at=raw.get("mergedAt"),
            closed_at=raw.get("closedAt"),
        )
        if head_ref:
            prs_by_branch.setdefault(head_ref, []).append(pr)
        if head_ref_oid:
            prs_by_head.setdefault(head_ref_oid, []).append(pr)

    return select_best_pr(prs_by_branch), select_best_pr(prs_by_head), None


def classify_worktree(
    repo: Path,
    raw: Dict[str, Any],
    protected_paths: set[Path],
    prs_by_branch: Dict[str, PullRequestInfo],
    prs_by_head: Dict[str, PullRequestInfo],
    base: str,
    warnings: List[str],
) -> WorktreeInfo:
    path = Path(raw["path"]).resolve()
    branch = raw.get("branch")
    head = raw.get("head")
    is_primary = path in protected_paths

    try:
        dirty_count = dirty_file_count(path)
    except CommandError as exc:
        warnings.append(f"could not read status for {path}: {exc.stderr}")
        dirty_count = -1

    try:
        ignored_risk = [] if is_primary else non_regenerable_ignored_paths(path)
    except CommandError as exc:
        warnings.append(f"could not read ignored status for {path}: {exc.stderr}")
        ignored_risk = []

    in_base = is_ancestor(repo, head, base)
    commits_not_in_base = commit_count_not_in_base(repo, head, base, warnings)
    subject = last_commit_subject(repo, head, warnings)
    commit_date = last_commit_date(repo, head, warnings)
    age_days = commit_age_days(commit_date, warnings, head)
    # Branch names are reusable, so a MERGED or CLOSED PR found by branch name
    # only classifies this worktree when the PR's head OID still equals the
    # worktree's HEAD — otherwise a reused name (or local commits made after
    # the merge) would mark genuinely-unmerged work `merged_clean`, the
    # guarded-removal bucket, and --apply would delete it. An OPEN PR is safe
    # to attribute by name alone: its bucket is never removable, and its head
    # advances with the branch.
    pr = None
    if branch:
        branch_pr = prs_by_branch.get(branch)
        if branch_pr and (
            branch_pr.state == "OPEN"
            or (branch_pr.head_ref_oid and head and branch_pr.head_ref_oid == head)
        ):
            pr = branch_pr
        elif head:
            # The branch-name slot can be claimed by a stale PR from an
            # earlier life of the name while a different non-OPEN PR matches
            # this worktree's exact HEAD; the OID equality is the proof of
            # attribution. OPEN PRs stay name-only so a coincident tip cannot
            # capture unrelated branches.
            head_pr = prs_by_head.get(head)
            if head_pr and head_pr.state != "OPEN":
                pr = head_pr
    elif head:
        pr = prs_by_head.get(head)

    bucket = "unknown"
    reason = "could not classify"

    if is_primary:
        bucket = "primary"
        reason = "primary or invocation checkout is never removed"
    elif dirty_count < 0:
        bucket = "unknown"
        reason = "git status failed"
    elif dirty_count > 0:
        bucket = "dirty"
        reason = f"{dirty_count} uncommitted file(s)"
    elif ignored_risk:
        bucket = "dirty"
        reason = (
            f"{len(ignored_risk)} gitignored file(s) present that `git status` "
            f"can't see but removal would still delete, e.g. {ignored_risk[0]!r}"
        )
    elif pr and pr.state == "OPEN":
        bucket = "open_pr"
        reason = f"open PR #{pr.number}"
    elif pr and pr.state == "MERGED":
        bucket = SAFE_BUCKET
        reason = f"merged PR #{pr.number}"
    elif in_base:
        bucket = SAFE_BUCKET
        reason = f"HEAD is contained in {base}"
    elif pr and pr.state == "CLOSED":
        bucket = "closed_unmerged"
        reason = f"closed unmerged PR #{pr.number}"
    elif branch:
        bucket = "unmerged_no_pr"
        reason = "branch has commits not in base and no PR"

    removable = (
        bucket == SAFE_BUCKET
        and not is_primary
        and dirty_count == 0
        and not ignored_risk
    )
    return WorktreeInfo(
        path=str(path),
        branch=branch,
        head=head,
        bucket=bucket,
        dirty_files=dirty_count,
        ignored_risk_files=ignored_risk,
        commits_not_in_base=commits_not_in_base,
        last_commit_subject=subject,
        last_commit_date=commit_date,
        last_commit_age_days=age_days,
        is_primary=is_primary,
        in_base=in_base,
        removable=removable,
        pr_number=pr.number if pr else None,
        pr_state=pr.state if pr else None,
        pr_url=pr.url if pr else None,
        reason=reason,
        next_owner_action=next_owner_action_for_bucket(bucket),
        review_command=review_command_for_worktree(path, repo, bucket, base, pr),
    )


def summarize(worktrees: Iterable[WorktreeInfo]) -> Dict[str, int]:
    worktree_list = list(worktrees)
    summary: Dict[str, int] = {}
    for worktree in worktree_list:
        summary[worktree.bucket] = summary.get(worktree.bucket, 0) + 1
    summary["total"] = sum(summary.values())
    summary["removable"] = sum(1 for worktree in worktree_list if worktree.removable)
    return summary


def cleanup_decision(worktrees: List[WorktreeInfo]) -> Dict[str, Any]:
    summary = summarize(worktrees)
    removable_count = summary.get("removable", 0)
    blocked_by_buckets = {
        bucket: summary[bucket]
        for bucket in sorted(OWNER_REVIEW_BUCKETS)
        if summary.get(bucket, 0)
    }
    owner_review_required_count = sum(blocked_by_buckets.values())

    cleanup_approval_required = removable_count > 0
    cleanup_approval_status = "required_before_apply" if cleanup_approval_required else "not_required"
    guarded_removal_available = removable_count > 0
    owner_approval_required_before_apply = removable_count > 0

    if removable_count:
        next_action = "owner_approval_required_before_apply"
        if owner_review_required_count:
            next_action += "; owner review required for non-removable buckets"
    elif owner_review_required_count:
        next_action = "owner_review_required_before_cleanup"
    else:
        next_action = "no_cleanup_needed"

    return {
        "automated_removal_allowed": removable_count > 0,
        "guarded_removal_available": guarded_removal_available,
        "owner_approval_required_before_apply": owner_approval_required_before_apply,
        "removable_count": removable_count,
        "owner_review_required_count": owner_review_required_count,
        "blocked_by_buckets": blocked_by_buckets,
        "cleanup_approval_required": cleanup_approval_required,
        "cleanup_approval_status": cleanup_approval_status,
        "next_action": next_action,
    }


def owner_review_items(worktrees: List[WorktreeInfo]) -> List[Dict[str, Any]]:
    items = [
        {
            "bucket": worktree.bucket,
            "branch": worktree.branch,
            "path": worktree.path,
            "pr_number": worktree.pr_number,
            "pr_url": worktree.pr_url,
            "reason": worktree.reason,
            "commits_not_in_base": worktree.commits_not_in_base,
            "last_commit_subject": worktree.last_commit_subject,
            "last_commit_date": worktree.last_commit_date,
            "last_commit_age_days": worktree.last_commit_age_days,
            "next_owner_action": worktree.next_owner_action,
            "review_command": worktree.review_command,
        }
        for worktree in worktrees
        if not worktree.is_primary and worktree.bucket in OWNER_REVIEW_BUCKETS
    ]
    return sorted(items, key=lambda item: (item["bucket"], item["path"] or ""))


def safe_cleanup_items(worktrees: List[WorktreeInfo]) -> List[Dict[str, Any]]:
    items = [
        {
            "bucket": worktree.bucket,
            "branch": worktree.branch,
            "path": worktree.path,
            "reason": worktree.reason,
            "commits_not_in_base": worktree.commits_not_in_base,
            "last_commit_subject": worktree.last_commit_subject,
            "last_commit_date": worktree.last_commit_date,
            "last_commit_age_days": worktree.last_commit_age_days,
            "next_owner_action": worktree.next_owner_action,
            "cleanup_approval_required": True,
            "cleanup_approval_status": "required_before_apply",
        }
        for worktree in worktrees
        if worktree.removable
    ]
    return sorted(items, key=lambda item: item["path"] or "")


def format_cleanup_decision(decision: Dict[str, Any]) -> str:
    if decision["removable_count"]:
        text = (
            "cleanup decision: owner approval required before applying "
            f"{decision['removable_count']} merged_clean worktree(s)"
        )
        if decision["owner_review_required_count"]:
            text += (
                "; owner review required for "
                f"{decision['owner_review_required_count']} non-removable worktree(s)"
            )
        return text
    if decision["owner_review_required_count"]:
        return (
            "cleanup decision: owner_review_required_before_cleanup; "
            "automated removal not allowed "
            f"({decision['owner_review_required_count']} non-removable worktree(s))"
        )
    return "cleanup decision: no_cleanup_needed; automated removal not allowed"


def markdown_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def last_activity_label(item: Dict[str, Any]) -> str:
    if item["last_commit_date"] is None:
        return "unknown"
    age = "unknown" if item["last_commit_age_days"] is None else item["last_commit_age_days"]
    return f"{item['last_commit_date']} ({age}d)"


def format_owner_review_markdown(repo: Path, base: str, worktrees: List[WorktreeInfo], warnings: List[str]) -> str:
    summary = summarize(worktrees)
    decision = cleanup_decision(worktrees)
    review_items = owner_review_items(worktrees)
    cleanup_items = safe_cleanup_items(worktrees)
    lines = [
        "# Worktree Owner Review",
        "",
        f"- Repo: `{repo}`",
        f"- Base: `{base}`",
        f"- Cleanup decision: `{decision['next_action']}`",
        f"- Guarded removal available: `{str(decision['guarded_removal_available']).lower()}`",
        f"- Owner approval required before apply: `{str(decision['owner_approval_required_before_apply']).lower()}`",
        f"- Cleanup approval status: `{decision['cleanup_approval_status']}`",
        f"- Removable `merged_clean` worktrees: `{decision['removable_count']}`",
        f"- Owner-review worktrees: `{decision['owner_review_required_count']}`",
        "",
        "## Summary",
        "",
    ]
    for key in sorted(summary):
        lines.append(f"- `{key}`: `{summary[key]}`")

    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")

    lines.extend(["", "## Owner Review Required", ""])
    if review_items:
        lines.append(
            "| Bucket | Branch | PR | Commits not in base | Last activity | Last commit | Path | Reason | Next owner action | Review command |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for item in review_items:
            pr = f"#{item['pr_number']}"
            if item.get("pr_url"):
                pr = f"[#{item['pr_number']}]({item['pr_url']})"
            elif not item.get("pr_number"):
                pr = ""
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_cell(item["bucket"]),
                        markdown_cell(item["branch"] or "(detached)"),
                        markdown_cell(pr),
                        markdown_cell(
                            "unknown"
                            if item["commits_not_in_base"] is None
                            else item["commits_not_in_base"]
                        ),
                        markdown_cell(last_activity_label(item)),
                        markdown_cell(item["last_commit_subject"] or "unknown"),
                        markdown_cell(item["path"]),
                        markdown_cell(item["reason"]),
                        markdown_cell(item["next_owner_action"]),
                        markdown_cell(item["review_command"]),
                    ]
                )
                + " |"
            )
    else:
        lines.append("No owner-review worktrees.")

    if decision["removable_count"]:
        lines.extend(
            [
                "",
                "## Guarded Cleanup Candidates",
                "",
                "Only `merged_clean` worktrees are eligible for guarded removal after owner approval:",
                "",
                "These rows are read-only evidence; run the apply command only after owner approval for these concrete paths.",
                "",
                "| Branch | Approval | Commits not in base | Last activity | Last commit | Path | Reason |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for item in cleanup_items:
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_cell(item["branch"] or "(detached)"),
                        markdown_cell("required before apply"),
                        markdown_cell(
                            "unknown"
                            if item["commits_not_in_base"] is None
                            else item["commits_not_in_base"]
                        ),
                        markdown_cell(last_activity_label(item)),
                        markdown_cell(item["last_commit_subject"] or "unknown"),
                        markdown_cell(item["path"]),
                        markdown_cell(item["reason"]),
                    ]
                )
                + " |"
            )
        lines.extend(
            [
                "",
                f"```bash\n{shlex.join(['python3', 'scripts/vidux-worktree-gc.py', '--base', base, '--apply', '--yes', str(repo)])}\n```",
            ]
        )
    return "\n".join(lines)


def format_text(repo: Path, base: str, worktrees: List[WorktreeInfo], warnings: List[str]) -> str:
    summary = summarize(worktrees)
    decision = cleanup_decision(worktrees)
    lines = [
        f"vidux-worktree-gc: {repo}",
        f"base: {base}",
        "summary: "
        + ", ".join(f"{key}={summary[key]}" for key in sorted(summary.keys()) if key != "total")
        + f", total={summary.get('total', 0)}",
        format_cleanup_decision(decision),
    ]

    if warnings:
        lines.append("")
        lines.append("warnings:")
        for warning in warnings:
            lines.append(f"  - {warning}")

    lines.append("")
    lines.append("worktrees:")
    for worktree in sorted(worktrees, key=lambda item: (item.bucket, item.path)):
        branch = worktree.branch or "(detached)"
        pr = f" PR#{worktree.pr_number}" if worktree.pr_number else ""
        marker = " removable" if worktree.removable else ""
        lines.append(f"  - [{worktree.bucket}{marker}] {branch}{pr} :: {worktree.path}")
        lines.append(f"    {worktree.reason}")
        commits = "unknown" if worktree.commits_not_in_base is None else str(worktree.commits_not_in_base)
        subject = worktree.last_commit_subject or "unknown"
        last_date = worktree.last_commit_date or "unknown"
        age_days = "unknown" if worktree.last_commit_age_days is None else str(worktree.last_commit_age_days)
        lines.append(
            "    evidence: "
            f"commits_not_in_base={commits}; "
            f"last_commit_date={last_date}; "
            f"last_commit_age_days={age_days}; "
            f"last_commit={subject}"
        )
        lines.append(f"    next: {worktree.next_owner_action}")
        lines.append(f"    review: {worktree.review_command}")

    if summary.get("removable", 0):
        lines.append("")
        lines.append("to remove safe local worktrees:")
        lines.append("  " + shlex.join(["python3", "scripts/vidux-worktree-gc.py", "--base", base, "--apply", "--yes", str(repo)]))
    return "\n".join(lines)


def remove_worktrees(
    repo: Path,
    worktrees: List[WorktreeInfo],
    delete_branches: bool,
    warnings: List[str],
) -> List[str]:
    removed: List[str] = []
    for worktree in worktrees:
        if not worktree.removable:
            continue
        # Re-check right before the destructive call, not just at classify
        # time -- cheap, and closes any window where content appeared between
        # classification and removal in the same run.
        try:
            recheck = non_regenerable_ignored_paths(Path(worktree.path))
        except CommandError as exc:
            warnings.append(f"skipped removal for {worktree.path}: re-check failed: {exc.stderr}")
            continue
        if recheck:
            warnings.append(
                f"skipped removal for {worktree.path}: gitignored content appeared "
                f"since classification (e.g. {recheck[0]!r}) -- re-run to reclassify"
            )
            continue
        try:
            run(["git", "-C", str(repo), "worktree", "remove", worktree.path])
        except CommandError as error:
            warnings.append(f"skipped removal for {worktree.path}: {error.stderr}")
            continue
        removed.append(worktree.path)
        if delete_branches and worktree.branch:
            result = run(["git", "-C", str(repo), "branch", "-d", worktree.branch], check=False)
            if result.returncode != 0:
                warnings.append(f"could not delete branch {worktree.branch}: {result.stderr.strip()}")
    return removed


def build_payload(
    repo: Path,
    base: str,
    worktrees: List[WorktreeInfo],
    warnings: List[str],
    removed: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "repo": str(repo),
        "base": base,
        "summary": summarize(worktrees),
        "cleanup_decision": cleanup_decision(worktrees),
        "owner_review_items": owner_review_items(worktrees),
        "safe_cleanup_items": safe_cleanup_items(worktrees),
        "warnings": warnings,
        "removed": removed or [],
        "worktrees": [asdict(worktree) for worktree in worktrees],
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", help="Repository or worktree path to inspect.")
    parser.add_argument("--base", default="origin/main", help="Base ref used to detect already-merged commits.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--owner-review-markdown", action="store_true", help="Print a Markdown owner-review packet.")
    parser.add_argument("--apply", action="store_true", help="Remove only safe merged_clean worktrees.")
    parser.add_argument("--yes", action="store_true", help="Required with --apply.")
    parser.add_argument(
        "--delete-branches",
        action="store_true",
        help="After removing safe worktrees, run git branch -d for their local branches.",
    )
    parser.add_argument("--pr-limit", type=int, default=300, help="Maximum PRs to load from gh.")
    parser.add_argument("--gate", action="store_true", help="Exit 2 when the worktree count exceeds --max-worktrees.")
    parser.add_argument("--max-worktrees", type=int, default=None, help="Gate threshold for total worktrees.")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    if args.apply and not args.yes:
        print("--apply requires --yes", file=sys.stderr)
        return 1

    try:
        repo = repo_root(Path(args.repo))
    except CommandError as exc:
        print(f"vidux-worktree-gc: {args.repo}: not a git repository ({exc.stderr or 'git rev-parse failed'})", file=sys.stderr)
        return 1
    warnings: List[str] = []
    raw_worktrees = load_worktrees(repo)
    if not raw_worktrees:
        print("no worktrees found", file=sys.stderr)
        return 1

    protected_paths = {Path(raw_worktrees[0]["path"]).resolve(), repo}
    prs_by_branch, prs_by_head, pr_warning = load_prs(repo, args.pr_limit)
    if pr_warning:
        warnings.append(pr_warning)

    worktrees = [
        classify_worktree(repo, raw, protected_paths, prs_by_branch, prs_by_head, args.base, warnings)
        for raw in raw_worktrees
    ]

    removed: List[str] = []
    if args.apply:
        removed = remove_worktrees(repo, worktrees, args.delete_branches, warnings)
        if removed:
            raw_worktrees = load_worktrees(repo)
            worktrees = [
                classify_worktree(repo, raw, protected_paths, prs_by_branch, prs_by_head, args.base, warnings)
                for raw in raw_worktrees
            ]

    payload = build_payload(repo, args.base, worktrees, warnings, removed)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.owner_review_markdown:
        print(format_owner_review_markdown(repo, args.base, worktrees, warnings))
    else:
        print(format_text(repo, args.base, worktrees, warnings))
        if removed:
            print("")
            print("removed:")
            for path in removed:
                print(f"  - {path}")

    if args.gate and args.max_worktrees is not None and payload["summary"]["total"] > args.max_worktrees:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
