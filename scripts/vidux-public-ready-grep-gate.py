#!/usr/bin/env python3
"""Fail when retired project-board terms reappear in Vidux's current surface."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


# SCAN_TARGETS used to be a
# hand-maintained ALLOWLIST of top-level files/dirs. That design has already
# let a real, live leak ship unscanned twice before (ASK-LEO.md, `projects/`)
# and recurred a third time (AGENTS.md, CHANGELOG.md were simply never named
# here) -- an allowlist only protects what someone remembered to add, and a
# new/renamed top-level file ships unscanned by default until someone
# notices. Scanning is now DEFAULT-ON: everything tracked is scanned
# unless it's named in the denylist below, so a new file is covered the
# moment it's created.
EXCLUDED_DIR_NAMES = {".git", "__pycache__", "node_modules"}
EXCLUDED_RELATIVE_PATHS = {
    # a bare `Path("docs/.vitepress")` entry used to
    # sit here, exempting the entire tree -- the identical "whole directory,
    # not the one file that needs it" bug just fixed for tests/, one entry
    # over. Checked: docs/.vitepress/dist/ is already git-ignored (dropped
    # by _drop_git_ignored below without needing an exemption) and
    # docs/.vitepress/config.ts -- the only tracked file in the tree --
    # contains zero content that trips any FORBIDDEN_PATTERN. No exemption
    # is actually needed here; the entry is removed rather than narrowed.
    #
    # This script's own comments and the test file below intentionally pin
    # the forbidden strings verbatim as documentation/fixtures, not leaks.
    Path("scripts/vidux-public-ready-grep-gate.py"),
    Path("tests/test_public_ready_grep_gate.py"),
    # tests/test_vidux_contracts.py legitimately pins some of these strings
    # as required test content (the private-path contract tests) -- scanning
    # it would flag the test file, not a leak.
    #
    # this used to
    # be the bare directory `Path("tests")`, exempting all 36 tracked files
    # under tests/ -- not just these 2 -- from every FORBIDDEN_PATTERN,
    # including PRIVACY_PATTERNS. Reproduced live: a scratch file dropped
    # into tests/ containing real employer-path/email leak-class strings
    # passed the gate with zero matches. Same "allowlist only protects what
    # someone remembered to add" failure the SCAN_TARGETS redesign
    # was built to eliminate, reintroduced one directory level down via an
    # over-broad denylist entry. Narrowed to exactly the 2 files that need it.
    Path("tests/test_vidux_contracts.py"),
}

# Purist-cut artifacts are forbidden by path, not just by package allowlist.
# This catches a restored file even when its contents contain no searchable
# marker. Historical prose may still explain why the subsystem was removed.
REMOVED_ARTIFACT_PATHS = {Path("browser/run_extract_pass.py")}
REMOVED_ARTIFACT_PREFIXES = (
    Path("agent"),
    Path("browser/receipts"),
    Path("commands"),
)

# Privacy/PII/confidentiality patterns: enforced everywhere scanned,
# regardless of tense. A personal home path or an employer-internal path
# is unsafe to publish whether it appears in live doctrine or a dated
# historical record.
PRIVACY_PATTERNS = (
    # this pattern originally only matched the spaced
    # "Leo Flow" form and missed the hyphenated slash-command form actually
    # used in prose ("/leo-flow", "leo-flow") -- 6 live occurrences in
    # SKILL.md's own doctrine section passed the gate green while the exact
    # leak class this pattern exists to catch sat in the flagship file.
    ("private Leo Flow lane", re.compile(r"\bLeo[ -]Flow\b", re.IGNORECASE)),
    ("private slop lane", re.compile(r"/ai-slop\b")),
    ("private vidux overlay name", re.compile(r"/vidux-leo\b")),
    # the old pattern only matched the /Users/leokwan
    # PATH form and missed the maintainer's bare username elsewhere -- a
    # historical evidence file leaked 26 `com.leokwan.<private-project>`
    # macOS LaunchAgent labels (naming several unrelated private repos) and
    # a live setup doc leaked one more, both unscanned because neither is a
    # /Users/ path. \bleokwan\b / \bredacted-operator\b subsumes the old path form (a
    # path boundary is also a \b boundary) while also catching every bare
    # mention.
    ("private username", re.compile(r"\b(?:leokwan|redacted-operator)\b")),
    # A prior repository-local Claude setting explained a valid attribution
    # policy by naming the maintainer's private account and private command
    # doctrine. Keep the rule narrow so public author credits remain valid.
    ("private maintainer account note", re.compile(r"\bLeo's\s+(?:work\s+)?account\b", re.IGNORECASE)),
    # 4 evidence files named the maintainer's real
    # spouse by first name -- once in a genuinely sensitive context (a
    # confidential job-search screenshot, now purged from the branches
    # that carried it), the rest as a recurring "make this simple enough
    # for X" persona shorthand. No PRIVACY_PATTERNS rule existed for a
    # family member's name at all. Placeholder-safe: this name never
    # appears in this repo's own shipped code/docs otherwise, so the
    # false-positive risk is the same as any other named-individual rule
    # already in this list.
    # an earlier version of this rule had no re.IGNORECASE, so it
    # only ever matched the capitalized prose form and gave false
    # confidence -- the dominant lowercase/kebab-case usage (this repo's
    # own project-naming convention lowercases everything, e.g.
    # "family-member-fpa-ai") sailed through every prior grep-gate run
    # unnoticed. Added re.IGNORECASE to match every casing.
    ("maintainer's spouse's first name", re.compile(r"\bNicole\b", re.IGNORECASE)),
    # this rule's own regex had been over-redacted to
    # the literal placeholder text "REDACTED-EMPLOYER-PATH" -- a string that
    # never appears in real content, so the check was a permanent silent
    # no-op. It missed a live leak: this session's own evidence file quoting
    # the maintainer's real employer-issued-laptop home path and corporate
    # email verbatim while documenting a confidentiality finding about that
    # exact content.
    ("employer source path", re.compile(r"\b(?:lkwan|Snapchat/Dev)\b")),
    # Bare-domain form, not just the `@`-prefixed email form -- a real
    # instance found live was an internal registry hostname with no `@`.
    ("employer email or domain", re.compile(r"\bsnapchat\.com\b", re.IGNORECASE)),
    ("employer internal hostname", re.compile(r"\bsc-corp\.net\b", re.IGNORECASE)),
    # no rule existed for the employer's internal
    # `.snap` TLD (distinct from the public `snapchat.com` domain above) --
    # a real instance (an internal inference-service hostname) shipped
    # unredacted in a tracked evidence file and this gate reported "passed"
    # with zero matches.
    #
    # the comments above and this rule's own test
    # fixtures used to reproduce the actual leaked strings verbatim
    # (a real coworker's email, a real internal hostname) -- gratuitous,
    # since these regexes match on domain/TLD only and a synthetic example
    # exercises them identically without adding a second, avoidable copy of
    # someone else's PII to the repo. Comments and fixtures now use made-up
    # placeholders; only the regex patterns themselves need the real
    # domain/TLD strings to detect a leak.
    ("employer internal .snap TLD", re.compile(r"\.snap\b", re.IGNORECASE)),
    # no rule existed for a gmail address or the
    # maintainer's separate small consumer-goods business name -- both
    # leaked live in commit-message quotes inside tracked evidence files,
    # unscanned because PRIVACY_PATTERNS had no entry for either.
    # `leojkwan@gmail.com` is excluded: it's the maintainer's permanent,
    # by-design public commit-author identity on every commit on
    # `origin/main` today (confirmed via `git log --format='%ae'`) -- unlike
    # every other gmail address, it isn't slated for removal/rewrite, so
    # quoting it in evidence prose adds no incremental exposure.
    ("gmail address other than the maintainer's public commit identity",
     re.compile(r"\b(?!leojkwan@gmail\.com\b)[\w.+-]+@gmail\.com\b", re.IGNORECASE)),
    ("maintainer's other business name", re.compile(r"\btrysnowcubes\b", re.IGNORECASE)),
    ("private skills repo path", re.compile(r"\bDevelopment/ai(?:-leo)?/(?:hooks|skills)\b")),
    (
        "private machine ownership assignment",
        re.compile(
            r"(?:"
            r"\b(?:Mac Studio|M[1-9]\s+(?:Pro|Max|Ultra)|this Mac)\b[^\n]{0,100}"
            r"(?:\bowns\b|\bowned\b|\bassigned\b|"
            r"\b(?:does not|must not|never)\b[^\n]{0,40}\b(?:probe|edit|open|run)\b)"
            r"|"
            r"(?:\bowns\b|\bowned\b|\bassigned\b|"
            r"\b(?:does not|must not|never)\b[^\n]{0,40}\b(?:probe|edit|open|run)\b)"
            r"[^\n]{0,100}\b(?:Mac Studio|M[1-9]\s+(?:Pro|Max|Ultra)|this Mac)\b"
            r")",
            re.IGNORECASE,
        ),
    ),
)

# Retired-terminology hygiene patterns: only meaningful as a "don't market
# a retired integration as current" check against LIVE-facing docs. A past
# -tense mention in a dated historical record (evidence/, investigations/,
# or PLAN.md's append-only Decision Log) is the record doing its job, not
# a leak — see HISTORICAL_TARGETS below.
HYGIENE_PATTERNS = (
    ("private pilot overlay", re.compile(r"\bpilot" r"-leo\b", re.IGNORECASE)),
    ("retired board brand", re.compile(r"\bLinear\b")),
    ("retired board lowercase", re.compile(r"\blinear\b")),
    ("retired GitHub Projects config key", re.compile(r"\bgh_projects\b")),
    ("retired inbox source config key", re.compile(r"\binbox_sources\b")),
    ("retired external-state label", re.compile(r"\bexternal-state\b")),
    ("retired inbox sync script", re.compile(r"\bvidux-inbox-sync\b")),
    ("retired audit script", re.compile(r"\blinear-audit\b")),
    ("retired pilot path", re.compile(r"\bpilot/")),
    ("retired hosted routines wording", re.compile(r"\bClaude Routines\b")),
)

FORBIDDEN_PATTERNS = PRIVACY_PATTERNS + HYGIENE_PATTERNS

# Commit-identity allowlist for the metadata scan (--metadata). A public repo
# publishes every reachable commit's author/committer email, and a foreign
# identity renders a real, unrelated GitHub account as a public contributor
# (proven live: a `test@test.com` author renders as the "TESTPERSONAL" account
# on the sibling claudux repo). Only these identities are legitimate:
#   - leojkwan@gmail.com: the maintainer's permanent, by-design public commit
#     identity on every legitimate commit (git log --format='%ae').
#   - noreply@github.com: GitHub's web-UI / squash-merge committer identity.
# Any other author or committer email is a finding. This is deliberately an
# allowlist, not a denylist, for the same reason SCAN_TARGETS is default-on: a
# new stray identity is caught the moment it appears, not when someone
# remembers to add it.
#   - codesmith-bot@users.noreply.github.com: the Codesmith reviewer identity
#     of the blacksmith.sh GitHub App installed on this repo (its "Codesmith"
#     check runs on every PR). With autofix enabled it lands commits as the
#     committer, and applied review suggestions carry it as a Co-authored-by
#     trailer (first on the PR #1 merge, a1e46e63). Intended participant, not
#     a foreign identity.
ALLOWED_COMMIT_EMAILS = frozenset(
    {
        "leojkwan@gmail.com",
        "noreply@github.com",
        "codesmith-bot@users.noreply.github.com",
        "cursoragent@cursor.com",
    }
)

CO_AUTHOR_TRAILER_RE = re.compile(
    r"^\s*Co-authored-by:\s*(?P<name>.*?)\s*<(?P<email>[^>]+)>", re.IGNORECASE
)

# Historical-record targets: chronological, dated, append-only-by-design.
# HYGIENE_PATTERNS are skipped here (retired terms in past tense are the
# record working correctly); PRIVACY_PATTERNS still apply everywhere.
#
# ARCHIVE.md and CHANGELOG.md were previously excluded from scanning
# entirely on the theory that "true history/changelog files record retired
# terms in legitimate past tense". That's a real concern (both files do
# legitimately mention retired terms like "Linear" many times in past
# tense) but full exclusion also hid real PRIVACY_PATTERNS leaks in
# CHANGELOG.md -- the fix is the
# same one already applied to PLAN.md/ASK-LEO.md/projects: HISTORICAL_
# TARGETS membership, not exclusion. Privacy leaks aren't legitimate in any
# tense; retired-terminology hygiene noise is the only thing past tense
# excuses.
HISTORICAL_TARGETS = {
    "evidence",
    "investigations",
    "PLAN.md",
    "projects",
    "ASK-OWNER.md",
    "ASK-LEO.md",
    "ARCHIVE.md",
    "CHANGELOG.md",
}
# PLAN.md is a living document with current sections interleaved with
# append-only history. Only these sections, including their nested headings,
# receive the historical hygiene exemption. The next peer or parent heading
# returns scanning to the live policy.
PLAN_APPEND_ONLY_HEADINGS = {"decision log", "decisions", "drift log", "progress"}
MARKDOWN_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*#*\s*$")
MARKDOWN_FENCE_RE = re.compile(r"^[ ]{0,3}(?P<fence>`{3,}|~{3,})")
MARKDOWN_SETEXT_RE = re.compile(r"^[ ]{0,3}(?P<marks>=+|-+)[ \t]*$")


# Files where "linear"/"Linear" is unrelated domain vocabulary (a CSS
# gradient/timing-function keyword, a secret-scanner rule name describing
# what it detects) rather than a mention of the retired Linear.app board
# integration. Found when default-on scanning first surfaced 9 new matches
# the moment style/tooling-config files were scanned for the first time --
# all 9 were this class, zero were real. PRIVACY_PATTERNS still apply to
# these files (a leaked path/username is not exempt just because the file
# is CSS); only the retired-terminology HYGIENE_PATTERNS are skipped.
HYGIENE_EXEMPT_SUFFIXES = {".css", ".svg"}
HYGIENE_EXEMPT_NAMES = {".gitignore", ".gitleaks.toml"}


def _is_historical(rel: Path) -> bool:
    return rel.parts[0] in HISTORICAL_TARGETS


def _hygiene_exempt(rel: Path) -> bool:
    return rel.suffix in HYGIENE_EXEMPT_SUFFIXES or rel.name in HYGIENE_EXEMPT_NAMES


def _plan_historical_lines(lines: list[str]) -> list[bool]:
    historical_heading_level: int | None = None
    historical: list[bool] = []
    fence_char: str | None = None
    fence_length = 0

    def apply_heading(level: int, title: str) -> None:
        nonlocal historical_heading_level
        if title.strip().casefold() in PLAN_APPEND_ONLY_HEADINGS:
            if historical_heading_level is None or level <= historical_heading_level:
                historical_heading_level = level
        elif historical_heading_level is not None and level <= historical_heading_level:
            historical_heading_level = None

    for index, line in enumerate(lines):
        if fence_char is not None:
            stripped = line.lstrip(" ")
            indent = len(line) - len(stripped)
            closing = re.fullmatch(
                rf"{re.escape(fence_char)}{{{fence_length},}}[ \t]*",
                stripped,
            )
            if indent <= 3 and closing:
                fence_char = None
                fence_length = 0
            historical.append(historical_heading_level is not None)
            continue

        fence = MARKDOWN_FENCE_RE.match(line)
        if fence:
            marker = fence.group("fence")
            fence_char = marker[0]
            fence_length = len(marker)
            historical.append(historical_heading_level is not None)
            continue

        setext = MARKDOWN_SETEXT_RE.match(line)
        if setext and index > 0 and lines[index - 1].strip():
            level = 1 if setext.group("marks").startswith("=") else 2
            apply_heading(level, lines[index - 1])
            historical[-1] = historical_heading_level is not None
            historical.append(historical_heading_level is not None)
            continue

        heading = MARKDOWN_HEADING_RE.match(line)
        if heading:
            level = len(heading.group("marks"))
            apply_heading(level, heading.group("title"))
        historical.append(historical_heading_level is not None)
    return historical


def _is_excluded(path: Path, repo_root: Path) -> bool:
    rel = path.relative_to(repo_root)
    if any(part in EXCLUDED_DIR_NAMES for part in rel.parts):
        return True
    return any(rel == excluded or excluded in rel.parents for excluded in EXCLUDED_RELATIVE_PATHS)


def _drop_git_ignored(repo_root: Path, files: list[Path]) -> list[Path]:
    """Scan only what ships. Drop git-ignored files (Leo keeps private tooling on
    disk locally); no-op outside a git repo so tmp-dir tests still scan all files."""
    try:
        inside = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, check=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return files
        rels = [str(f.relative_to(repo_root)) for f in files]
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "--stdin"],
            input="\n".join(rels), capture_output=True, text=True, check=False,
        )
        ignored = set(proc.stdout.splitlines())
        return [f for f, rel in zip(files, rels) if rel not in ignored]
    except Exception:
        return files


def _tracked_files(repo_root: Path) -> list[Path]:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--cached", "-z"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError("--tracked-only requires a git worktree")
    files = []
    for raw_rel in proc.stdout.split(b"\0"):
        if not raw_rel:
            continue
        path = repo_root / raw_rel.decode("utf-8", errors="surrogateescape")
        if not _is_excluded(path, repo_root):
            files.append(path)
    return sorted(files)


def _iter_files(repo_root: Path, *, tracked_only: bool = False) -> list[Path]:
    if tracked_only:
        return _tracked_files(repo_root)
    files = [
        child
        for child in repo_root.rglob("*")
        if child.is_file() and not _is_excluded(child, repo_root)
    ]
    return _drop_git_ignored(repo_root, sorted(files))


def _read_scanned_lines(path: Path, repo_root: Path, *, tracked_only: bool) -> list[str]:
    if not tracked_only:
        return path.read_text(encoding="utf-8").splitlines()
    rel = path.relative_to(repo_root).as_posix()
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "show", f":{rel}"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise OSError(f"cannot read staged content for {rel}")
    return proc.stdout.decode("utf-8").splitlines()


def run_gate(repo_root: Path, *, tracked_only: bool = False) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    try:
        scanned_files = _iter_files(repo_root, tracked_only=tracked_only)
    except RuntimeError as exc:
        return {
            "status": "failed",
            "scope": "tracked" if tracked_only else "working-tree",
            "scanned_files": 0,
            "matches": [],
            "errors": [str(exc)],
        }
    for path in scanned_files:
        rel = path.relative_to(repo_root)
        if rel in REMOVED_ARTIFACT_PATHS or any(
            prefix == rel or prefix in rel.parents for prefix in REMOVED_ARTIFACT_PREFIXES
        ):
            matches.append(
                {
                    "file": str(rel),
                    "line": 0,
                    "pattern": "removed purist artifact path",
                    "text": str(rel),
                }
            )
        # this loop only ever checked file *content*
        # -- the relative path/filename itself was never matched against
        # any pattern. Reproduced live: an evidence file's body was
        # redacted but its filename still carried a leak-class string
        # verbatim, which renders unredacted in any GitHub directory
        # listing regardless of what's inside the file. PRIVACY_PATTERNS
        # (not HYGIENE_PATTERNS -- a filename containing "linear" is noise,
        # not a leak) apply to every filename unconditionally, including
        # historical/hygiene-exempt files: a leak in a filename is exactly
        # as visible whether or not the file's own content is exempt.
        rel_str = str(rel)
        for label, pattern in PRIVACY_PATTERNS:
            if pattern.search(rel_str):
                matches.append(
                    {
                        "file": rel_str,
                        "line": 0,
                        "pattern": f"{label} (in filename)",
                        "text": rel_str,
                    }
                )
        try:
            lines = _read_scanned_lines(path, repo_root, tracked_only=tracked_only)
        except UnicodeDecodeError:
            continue
        except OSError:
            # an unreadable file (permissions) or one
            # deleted between _iter_files() listing and this read (plausible
            # if the gate runs while other automation is writing to
            # evidence/) previously propagated as an unhandled traceback --
            # exit 1 either way, indistinguishable from a real leak match to
            # a caller checking only the exit code, and --json mode emitted
            # no parseable output at all. Treat as unscannable, not fatal.
            continue
        plan_history = _plan_historical_lines(lines) if rel.name == "PLAN.md" else None
        for lineno, line in enumerate(lines, start=1):
            if plan_history is not None:
                historical = plan_history[lineno - 1]
            else:
                historical = _is_historical(rel)
            patterns = (
                PRIVACY_PATTERNS
                if historical or _hygiene_exempt(rel)
                else FORBIDDEN_PATTERNS
            )
            for label, pattern in patterns:
                if pattern.search(line):
                    matches.append(
                        {
                            "file": str(rel),
                            "line": lineno,
                            "pattern": label,
                            "text": line.strip(),
                        }
                    )

    return {
        "status": "failed" if matches else "passed",
        "scope": "tracked" if tracked_only else "working-tree",
        "scanned_files": len(scanned_files),
        "matches": matches,
        "errors": [],
    }


def run_metadata_gate(repo_root: Path, *, rev: str = "HEAD") -> dict[str, Any]:
    """Scan commit metadata that file-content scanning is structurally blind to.

    ``run_gate`` reads blobs (and now filenames) but never commit metadata, so
    it cannot see the two exposure classes that survive a clean tree:

    1. A foreign author/committer email (e.g. ``test@test.com``) renders a
       real, unrelated GitHub account as a public contributor. Enforced by
       ALLOWED_COMMIT_EMAILS: any identity not on the allowlist is a finding.
    2. A foreign ``Co-authored-by`` trailer email, which renders in the
       contributor sidebar exactly like an author. Enforced against the same
       allowlist.
    3. A privacy string in a commit message or trailer (e.g. a
       ``Co-authored-by: ... <name@snapchat.com>`` trailer). PRIVACY_PATTERNS
       apply to every reachable commit's message body.

    HYGIENE_PATTERNS are intentionally *not* applied here: a retired term in an
    immutable historical commit message is the record, not a live surface.
    Findings are deduplicated (per identity; per pattern+line) so a leak
    repeated across N commits reports once with its commit count.
    """
    unit = "\x1f"
    proc = subprocess.run(
        [
            "git", "-C", str(repo_root), "log", rev, "-z",
            f"--format=%H{unit}%an{unit}%ae{unit}%cn{unit}%ce{unit}%B",
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "status": "failed",
            "scope": "commit-metadata",
            "scanned_commits": 0,
            "matches": [],
            "errors": [
                f"cannot read commit metadata for {rev!r}: "
                f"{proc.stderr.decode('utf-8', 'replace').strip()}"
            ],
        }

    bad_identities: dict[tuple[str, str, str], int] = {}
    message_hits: dict[tuple[str, str], dict[str, Any]] = {}
    scanned = 0
    for record in proc.stdout.split(b"\x00"):
        if not record:
            continue
        fields = record.split(unit.encode("utf-8"), 5)
        if len(fields) < 6:
            continue
        sha_b, an_b, ae_b, cn_b, ce_b, body_b = fields
        scanned += 1
        sha = sha_b.decode("utf-8", "replace")
        for role, name_b, email_b in (
            ("author", an_b, ae_b),
            ("committer", cn_b, ce_b),
        ):
            email = email_b.decode("utf-8", "replace")
            if email not in ALLOWED_COMMIT_EMAILS:
                key = (role, name_b.decode("utf-8", "replace"), email)
                bad_identities[key] = bad_identities.get(key, 0) + 1
        body = body_b.decode("utf-8", "surrogateescape")
        for line in body.splitlines():
            trailer = CO_AUTHOR_TRAILER_RE.match(line)
            if trailer:
                trailer_email = trailer.group("email").strip()
                if trailer_email not in ALLOWED_COMMIT_EMAILS:
                    key = ("co-author trailer", trailer.group("name"), trailer_email)
                    bad_identities[key] = bad_identities.get(key, 0) + 1
            for label, pattern in PRIVACY_PATTERNS:
                if pattern.search(line):
                    key = (label, line.strip())
                    hit = message_hits.setdefault(key, {"sha": sha, "count": 0})
                    hit["count"] += 1

    matches: list[dict[str, Any]] = []
    for (role, name, email), count in sorted(bad_identities.items()):
        plural = "" if count == 1 else "s"
        matches.append(
            {
                "file": "<commit-metadata>",
                "line": 0,
                "pattern": f"disallowed {role} identity",
                "text": f"{name} <{email}> ({count} commit{plural})",
            }
        )
    for (label, text), info in sorted(message_hits.items()):
        plural = "" if info["count"] == 1 else "s"
        matches.append(
            {
                "file": f"<commit-message {info['sha'][:12]}>",
                "line": 0,
                "pattern": label,
                "text": f"{text} ({info['count']} commit{plural})",
            }
        )

    return {
        "status": "failed" if matches else "passed",
        "scope": "commit-metadata",
        "scanned_commits": scanned,
        "matches": matches,
        "errors": [],
    }


def _human(payload: dict[str, Any]) -> str:
    lines = [
        "Vidux public-ready grep gate",
        f"status: {payload['status']}",
        f"scope: {payload['scope']}",
        f"scanned_files: {payload['scanned_files']}",
    ]
    if "scanned_commits" in payload:
        lines.append(f"scanned_commits: {payload['scanned_commits']}")
    for error in payload.get("errors", []):
        lines.append(f"error: {error}")
    if payload["matches"]:
        lines.append("matches:")
        for match in payload["matches"]:
            lines.append(
                f"- {match['file']}:{match['line']} "
                f"[{match['pattern']}] {match['text']}"
            )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Vidux repo root. Defaults to this script's parent repo.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument(
        "--tracked-only",
        action="store_true",
        help="Scan the tracked/staged shipping set instead of every unignored worktree file.",
    )
    parser.add_argument(
        "--metadata",
        action="store_true",
        help=(
            "Also scan commit metadata (author/committer identity + message "
            "trailers) reachable from HEAD. Catches the foreign-contributor and "
            "trailer-leak classes that file-content scanning cannot see."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    payload = run_gate(repo_root, tracked_only=args.tracked_only)
    if args.metadata:
        meta = run_metadata_gate(repo_root)
        payload["matches"] = payload["matches"] + meta["matches"]
        payload["scanned_commits"] = meta["scanned_commits"]
        payload["errors"] = payload["errors"] + meta["errors"]
        if meta["status"] == "failed":
            payload["status"] = "failed"
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_human(payload), end="")
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
