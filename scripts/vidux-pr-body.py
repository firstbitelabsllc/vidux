#!/usr/bin/env python3
"""Build the canonical ready-PR body for vidux automation lanes."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


HANDOFF_STATUSES = {"done", "in_progress", "blocked", "needs_review"}
REQUIRED_REVIEW_PASSES = ("invariant", "regression", "adversarial")
TASK_ROW_STATUS_RE = r"(?: |x|pending|in_progress|completed|blocked)"
LEDGER_EID_RE = re.compile(r"^evt_[A-Za-z0-9][A-Za-z0-9_.:-]*$")
EXTENSIONLESS_PATH_NAMES = {
    "Dockerfile",
    "Gemfile",
    "LICENSE",
    "Makefile",
    "PLAN",
    "RALPH",
    "README",
    "SKILL",
}
PATH_SUFFIX_RE = re.compile(r"\.[A-Za-z0-9][A-Za-z0-9_.-]*$")
REVIEW_ALIASES = {
    "invariant": "invariant",
    "invariant-audit": "invariant",
    "invariant-auditor": "invariant",
    "regression": "regression",
    "regression-runner": "regression",
    "regression-check": "regression",
    "adversarial": "adversarial",
    "adversarial-review": "adversarial",
    "adversarial-reviewer": "adversarial",
}
REVIEW_LABELS = {
    "invariant": "Invariant audit",
    "regression": "Regression runner",
    "adversarial": "Adversarial reviewer",
}


def _clean(value: str, *, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be empty")
    return cleaned


def _looks_like_path(value: str) -> bool:
    if "\n" in value:
        return False
    if value.startswith(("/", "./", "../", "~")):
        return True
    if "/" in value:
        return True
    if PATH_SUFFIX_RE.search(value):
        return True
    return value in EXTENSIONLESS_PATH_NAMES


def _resolve_path(value: str, *, cwd: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (cwd or Path.cwd()) / path
    return path.resolve(strict=False)


def _git_root(*, cwd: Path | None = None) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(cwd or Path.cwd()), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve(strict=False)


def _git_knows_path(value: str, *, cwd: Path | None = None) -> bool:
    root = _git_root(cwd=cwd)
    if root is None:
        return False

    path = _resolve_path(value, cwd=cwd)
    try:
        git_path = str(path.relative_to(root))
    except ValueError:
        return False

    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", git_path],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _clean_path(value: str, *, field: str, cwd: Path | None = None) -> str:
    cleaned = _clean(value, field=field)
    if not _looks_like_path(cleaned):
        raise ValueError(f"{field} must be a file/path-like entry, not prose")
    if not _resolve_path(cleaned, cwd=cwd).exists() and not _git_knows_path(
        cleaned, cwd=cwd
    ):
        raise ValueError(
            f"{field} must resolve to an existing path or git-known deleted path: {cleaned}"
        )
    return cleaned


def _clean_plan_path(value: str, *, cwd: Path | None = None) -> str:
    cleaned = _clean(value, field="plan_path")
    if not _looks_like_path(cleaned):
        raise ValueError("plan_path must be a file/path-like entry, not prose")
    if not _resolve_path(cleaned, cwd=cwd).is_file():
        raise ValueError(
            f"plan_path must resolve to an existing plan file: {cleaned}"
        )
    return cleaned


def _ledger_path_candidates() -> list[Path]:
    env_path = os.environ.get("VIDUX_LEDGER_FILE", "").strip()
    if env_path:
        hot = Path(env_path).expanduser()
        paths = [hot]
    else:
        paths = [Path.home() / ".agent-ledger" / "activity.jsonl"]

    archive_paths = [path.parent / "archive" / "evicted.jsonl" for path in paths]
    candidates: list[Path] = []
    seen: set[Path] = set()
    for path in [*paths, *archive_paths]:
        resolved = path.resolve(strict=False)
        if resolved not in seen:
            candidates.append(resolved)
            seen.add(resolved)
    return candidates


def _ledger_row_for_eid(
    eid: str, *, ledger_paths: list[Path] | None = None
) -> dict[str, object] | None:
    for path in ledger_paths or _ledger_path_candidates():
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if eid not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("eid") == eid:
                    return row
    return None


def _normalized_path_set(values: object, *, cwd: Path | None = None) -> set[str]:
    if not isinstance(values, list):
        return set()
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        normalized.add(str(_resolve_path(value.strip(), cwd=cwd)))
    return normalized


def _clean_ledger(
    value: str,
    *,
    lane: str,
    task: str,
    summary: str,
    plan_path: str,
    proof: str,
    handoff_status: str,
    files_claimed: list[str],
    resume: str,
    cwd: Path | None = None,
    ledger_paths: list[Path] | None = None,
) -> str:
    cleaned = _clean(value, field="ledger")
    if not LEDGER_EID_RE.match(cleaned):
        raise ValueError("ledger must be a publish ledger eid starting with evt_")
    row = _ledger_row_for_eid(cleaned, ledger_paths=ledger_paths)
    if row is None:
        raise ValueError(f"ledger must exist in the hot/archive ledger: {cleaned}")
    if row.get("event") != "publish":
        raise ValueError("ledger event must be publish")

    expected_plan = str(_resolve_path(plan_path, cwd=cwd))
    actual_plan = row.get("plan_path")
    if actual_plan is None or str(_resolve_path(str(actual_plan), cwd=cwd)) != expected_plan:
        raise ValueError("ledger plan_path must match the ready-PR plan_path")

    expected_files = {str(_resolve_path(path, cwd=cwd)) for path in files_claimed}
    actual_files = _normalized_path_set(row.get("files_claimed"), cwd=cwd)
    missing_files = sorted(expected_files - actual_files)
    if missing_files:
        raise ValueError(
            "ledger files_claimed must include ready-PR file claims: "
            + ", ".join(missing_files)
        )
    actual_changed_files = _normalized_path_set(row.get("files"), cwd=cwd)
    missing_changed_files = sorted(expected_files - actual_changed_files)
    if missing_changed_files:
        raise ValueError(
            "ledger files must include ready-PR file claims: "
            + ", ".join(missing_changed_files)
        )

    expected_scalars = {
        "lane": lane,
        "task_id": task,
        "summary": summary,
        "proof": proof,
        "handoff_status": handoff_status,
        "next_agent_resume": resume,
    }
    for field, expected in expected_scalars.items():
        if row.get(field) != expected:
            raise ValueError(f"ledger {field} must match the ready-PR {field}")

    return cleaned


def _plan_contains_task_row(
    plan_path: str, task: str, *, cwd: Path | None = None
) -> bool:
    text = _resolve_path(plan_path, cwd=cwd).read_text(encoding="utf-8")
    task_row_re = re.compile(
        rf"^\s*[-*]\s+\[{TASK_ROW_STATUS_RE}\]\s+{re.escape(task)}(?=$|[\s:])",
        re.MULTILINE,
    )
    return task_row_re.search(text) is not None


def _validate_plan_task(plan_path: str, task: str, *, cwd: Path | None = None) -> None:
    if not _plan_contains_task_row(plan_path, task, cwd=cwd):
        raise ValueError(f"task must appear in plan_path as a task row: {task}")


def _normalize_review_name(value: str) -> str:
    key = value.strip().lower().replace("_", "-").replace(" ", "-")
    try:
        return REVIEW_ALIASES[key]
    except KeyError as exc:
        allowed = ", ".join(REQUIRED_REVIEW_PASSES)
        raise ValueError(f"unknown review pass '{value}' (want one of: {allowed})") from exc


def _parse_review_pass(value: str) -> tuple[str, str]:
    parts = value.split(":", 2)
    if len(parts) != 3:
        raise ValueError("--review-pass must use NAME:STATUS:EVIDENCE")

    name = _normalize_review_name(parts[0])
    status = parts[1].strip().lower()
    if status != "pass":
        raise ValueError(f"review pass '{name}' must be pass before building a PR body")
    evidence = _clean(parts[2], field=f"{name} evidence")
    return name, evidence


def _review_passes(values: list[str]) -> dict[str, str]:
    reviews: dict[str, str] = {}
    duplicates: set[str] = set()
    for value in values:
        name, evidence = _parse_review_pass(value)
        if name in reviews:
            duplicates.add(name)
        reviews[name] = evidence

    if duplicates:
        raise ValueError(f"duplicate review pass: {', '.join(sorted(duplicates))}")

    missing = [name for name in REQUIRED_REVIEW_PASSES if name not in reviews]
    if missing:
        raise ValueError(f"missing review pass: {', '.join(missing)}")
    return reviews


def build_pr_body(
    *,
    lane: str,
    task: str,
    summary: str,
    plan_path: str,
    proof: str,
    handoff_status: str,
    ledger: str,
    files_claimed: list[str],
    resume: str,
    changes: list[str],
    review_passes: list[str],
    cwd: Path | None = None,
    ledger_paths: list[Path] | None = None,
) -> str:
    """Return the durable PR body every automation lane can resume from."""
    lane = _clean(lane, field="lane")
    task = _clean(task, field="task")
    summary = _clean(summary, field="summary")
    plan_path = _clean_plan_path(plan_path, cwd=cwd)
    _validate_plan_task(plan_path, task, cwd=cwd)
    proof = _clean(proof, field="proof")
    handoff_status = _clean(handoff_status, field="handoff_status")
    if handoff_status not in HANDOFF_STATUSES:
        allowed = ", ".join(sorted(HANDOFF_STATUSES))
        raise ValueError(f"handoff_status must be one of: {allowed}")
    resume = _clean(resume, field="resume")

    cleaned_changes = [_clean(change, field="change") for change in changes]
    if not cleaned_changes:
        raise ValueError("at least one --change entry is required")
    cleaned_files = [
        _clean_path(path, field="file_claimed", cwd=cwd) for path in files_claimed
    ]
    if not cleaned_files:
        raise ValueError("at least one --file-claimed entry is required")
    reviews = _review_passes(review_passes)
    ledger = _clean_ledger(
        ledger,
        lane=lane,
        task=task,
        summary=summary,
        plan_path=plan_path,
        proof=proof,
        handoff_status=handoff_status,
        files_claimed=cleaned_files,
        resume=resume,
        cwd=cwd,
        ledger_paths=ledger_paths,
    )

    body = [
        "## Automation",
        f"Lane: {lane}",
        f"Plan task: {task}",
    ]

    body.extend(
        [
            "",
            "## Publish Propagation",
            f"Summary: {summary}",
            f"Plan path: {plan_path}",
            f"Proof: {proof}",
            f"Ledger: {ledger}",
            f"Handoff status: {handoff_status}",
            "Files claimed:",
        ]
    )

    for path in cleaned_files:
        body.append(path if path.startswith("- ") else f"- {path}")

    body.extend(["", "## Self-Scrutiny", "Review passes:"])

    for name in REQUIRED_REVIEW_PASSES:
        body.append(f"- {REVIEW_LABELS[name]}: pass - {reviews[name]}")

    body.extend(
        [
            "",
            f"Resume point: {resume}",
            "",
            "## Changes",
        ]
    )

    for change in cleaned_changes:
        body.append(change if change.startswith("- ") else f"- {change}")

    return "\n".join(body) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a canonical vidux automation PR body."
    )
    parser.add_argument("--lane", required=True, help="Lane id, e.g. codex/acme-web")
    parser.add_argument("--task", required=True, help="PLAN.md task id, e.g. BD-68")
    parser.add_argument("--summary", required=True, help="Concise publish summary.")
    parser.add_argument("--plan-path", required=True, help="Owning PLAN.md path.")
    parser.add_argument("--proof", required=True, help="Command or artifact proving the PR state.")
    parser.add_argument(
        "--handoff-status",
        required=True,
        choices=sorted(HANDOFF_STATUSES),
        help="Current resume status for the PR handoff.",
    )
    parser.add_argument(
        "--ledger",
        required=True,
        help="Matching publish ledger eid present in the hot/archive ledger, e.g. evt_...",
    )
    parser.add_argument(
        "--resume",
        required=True,
        help="What the next cycle should do if this PR stalls.",
    )
    parser.add_argument(
        "--file-claimed",
        action="append",
        default=[],
        help="File/path claimed by this PR. Repeat for multiple files.",
    )
    parser.add_argument(
        "--review-pass",
        action="append",
        default=[],
        metavar="NAME:STATUS:EVIDENCE",
        help=(
            "Self-scrutiny result. Required names: invariant, regression, "
            "adversarial. Status must be pass."
        ),
    )
    parser.add_argument(
        "--change",
        action="append",
        default=[],
        help="One concise change summary. Repeat for 1-3 bullets.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.write(
            build_pr_body(
                lane=args.lane,
                task=args.task,
                summary=args.summary,
                plan_path=args.plan_path,
                proof=args.proof,
                handoff_status=args.handoff_status,
                ledger=args.ledger,
                files_claimed=args.file_claimed,
                resume=args.resume,
                changes=args.change,
                review_passes=args.review_pass,
            )
        )
    except ValueError as exc:
        sys.stderr.write(f"vidux-pr-body: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
