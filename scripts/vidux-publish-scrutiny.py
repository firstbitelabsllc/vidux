#!/usr/bin/env python3
"""Read-only preflight for Vidux publish self-scrutiny packets."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HANDOFF_STATUSES = {"done", "in_progress", "blocked", "needs_review"}
REVIEW_STATUSES = {"pass", "fail"}
REQUIRED_REVIEW_PASSES = ("invariant", "regression", "adversarial")
TASK_ROW_STATUS_RE = r"(?: |x|pending|in_progress|completed|blocked)"
LEDGER_EID_RE = re.compile(r"^evt_[A-Za-z0-9][A-Za-z0-9_.:-]*$")
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


@dataclass(frozen=True)
class ReviewPass:
    name: str
    status: str
    evidence: str


def _clean(value: str, *, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be empty")
    return cleaned


def _clean_many(values: list[str], *, field: str) -> list[str]:
    cleaned = [_clean(value, field=field) for value in values]
    if not cleaned:
        raise ValueError(f"at least one --{field.replace('_', '-')} entry is required")
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


def _non_pathish(values: list[str]) -> list[str]:
    return [value for value in values if not _looks_like_path(value)]


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
    if path.is_absolute():
        try:
            git_path = str(path.relative_to(root))
        except ValueError:
            return False
    else:
        git_path = value

    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", git_path],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _unresolved_paths(values: list[str], *, cwd: Path | None = None) -> list[str]:
    unresolved: list[str] = []
    for value in values:
        if _resolve_path(value, cwd=cwd).exists():
            continue
        if _git_knows_path(value, cwd=cwd):
            continue
        unresolved.append(value)
    return unresolved


def _normalized_path_set(values: list[str], *, cwd: Path | None = None) -> set[str]:
    return {str(_resolve_path(value, cwd=cwd)) for value in values}


def _normalize_review_name(value: str) -> str:
    key = value.strip().lower().replace("_", "-").replace(" ", "-")
    try:
        return REVIEW_ALIASES[key]
    except KeyError as exc:
        allowed = ", ".join(REQUIRED_REVIEW_PASSES)
        raise ValueError(f"unknown review pass '{value}' (want one of: {allowed})") from exc


def parse_review_pass(value: str) -> ReviewPass:
    """Parse NAME:STATUS:EVIDENCE into a normalized review pass."""
    parts = value.split(":", 2)
    if len(parts) != 3:
        raise ValueError("--review-pass must use NAME:STATUS:EVIDENCE")

    name = _normalize_review_name(parts[0])
    status = parts[1].strip().lower()
    if status not in REVIEW_STATUSES:
        allowed = ", ".join(sorted(REVIEW_STATUSES))
        raise ValueError(f"review pass '{name}' status must be one of: {allowed}")

    return ReviewPass(
        name=name,
        status=status,
        evidence=_clean(parts[2], field=f"{name} evidence"),
    )


def _review_map(review_passes: list[ReviewPass]) -> tuple[dict[str, ReviewPass], list[str]]:
    reviews: dict[str, ReviewPass] = {}
    duplicates: list[str] = []
    for review in review_passes:
        if review.name in reviews:
            duplicates.append(review.name)
        reviews[review.name] = review
    return reviews, sorted(set(duplicates))


def _resolve_plan(plan_path: str, *, cwd: Path | None = None) -> Path:
    path = Path(plan_path).expanduser()
    if path.is_absolute():
        return path
    return (cwd or Path.cwd()) / path


def _plan_contains_task_row(plan_path: Path, task: str) -> bool:
    text = plan_path.read_text(encoding="utf-8")
    task_row_re = re.compile(
        rf"^\s*[-*]\s+\[{TASK_ROW_STATUS_RE}\]\s+{re.escape(task)}(?=$|[\s:])",
        re.MULTILINE,
    )
    return task_row_re.search(text) is not None


def scrutinize_publish(
    *,
    lane: str,
    task: str,
    summary: str,
    plan_path: str,
    proof: str,
    ledger: str,
    handoff_status: str,
    files_claimed: list[str],
    claims: list[str],
    resume: str,
    review_passes: list[ReviewPass],
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Return a machine-readable publish readiness verdict."""
    report: dict[str, Any] = {
        "ready": False,
        "required_fields": [
            "lane",
            "task",
            "summary",
            "plan_path",
            "proof",
            "ledger",
            "handoff_status",
            "files_claimed",
            "claims",
            "resume",
        ],
        "missing_fields": [],
        "invalid_fields": [],
        "missing_review_passes": [],
        "failed_review_passes": [],
        "duplicate_review_passes": [],
        "checks": {},
        "review_passes": {},
    }

    cleaned: dict[str, Any] = {}
    scalar_fields = {
        "lane": lane,
        "task": task,
        "summary": summary,
        "plan_path": plan_path,
        "proof": proof,
        "ledger": ledger,
        "handoff_status": handoff_status,
        "resume": resume,
    }
    for field, value in scalar_fields.items():
        try:
            cleaned[field] = _clean(value, field=field)
        except ValueError:
            report["missing_fields"].append(field)

    for field, values in (("files_claimed", files_claimed), ("claims", claims)):
        try:
            cleaned[field] = _clean_many(values, field=field)
        except ValueError:
            report["missing_fields"].append(field)
            continue

        invalid_paths = _non_pathish(cleaned[field])
        if invalid_paths:
            report["invalid_fields"].append(
                {
                    "field": field,
                    "reason": (
                        "entries must be file/path-like, not prose summaries: "
                        + ", ".join(invalid_paths)
                    ),
                }
            )
            continue

        unresolved_paths = _unresolved_paths(cleaned[field], cwd=cwd)
        report["checks"][f"{field}_unresolved"] = unresolved_paths
        if unresolved_paths:
            report["invalid_fields"].append(
                {
                    "field": field,
                    "reason": (
                        "entries must resolve to existing paths or git-known deleted paths: "
                        + ", ".join(unresolved_paths)
                    ),
                }
            )

    if "files_claimed" in cleaned and "claims" in cleaned:
        missing_claims = sorted(
            _normalized_path_set(cleaned["files_claimed"], cwd=cwd)
            - _normalized_path_set(cleaned["claims"], cwd=cwd)
        )
        report["checks"]["claims_missing_files_claimed"] = missing_claims
        if missing_claims:
            report["invalid_fields"].append(
                {
                    "field": "claims",
                    "reason": (
                        "claims must include every --file-claimed entry: "
                        + ", ".join(missing_claims)
                    ),
                }
            )

    if "handoff_status" in cleaned and cleaned["handoff_status"] not in HANDOFF_STATUSES:
        allowed = ", ".join(sorted(HANDOFF_STATUSES))
        report["invalid_fields"].append(
            {
                "field": "handoff_status",
                "reason": f"must be one of: {allowed}",
            }
        )

    if "ledger" in cleaned and not LEDGER_EID_RE.match(cleaned["ledger"]):
        report["invalid_fields"].append(
            {
                "field": "ledger",
                "reason": "must be a publish ledger eid starting with evt_",
            }
        )

    if "plan_path" in cleaned:
        resolved_plan = _resolve_plan(cleaned["plan_path"], cwd=cwd)
        plan_exists = resolved_plan.is_file()
        report["checks"]["plan_exists"] = plan_exists
        report["checks"]["resolved_plan_path"] = str(resolved_plan)
        if not plan_exists:
            report["invalid_fields"].append(
                {"field": "plan_path", "reason": f"not a file: {resolved_plan}"}
            )
        elif "task" in cleaned:
            task_in_plan = _plan_contains_task_row(resolved_plan, cleaned["task"])
            report["checks"]["task_in_plan"] = task_in_plan
            if not task_in_plan:
                report["invalid_fields"].append(
                    {
                        "field": "task",
                        "reason": (
                            f"task '{cleaned['task']}' not found as task row in "
                            f"{resolved_plan}"
                        ),
                    }
                )

    reviews, duplicates = _review_map(review_passes)
    report["duplicate_review_passes"] = duplicates
    for name, review in reviews.items():
        report["review_passes"][name] = {
            "status": review.status,
            "evidence": review.evidence,
        }
    if duplicates:
        report["invalid_fields"].append(
            {
                "field": "review_pass",
                "reason": f"duplicate review pass: {', '.join(duplicates)}",
            }
        )

    missing_reviews = [name for name in REQUIRED_REVIEW_PASSES if name not in reviews]
    report["missing_review_passes"] = missing_reviews
    report["failed_review_passes"] = [
        {
            "name": review.name,
            "status": review.status,
            "evidence": review.evidence,
        }
        for review in reviews.values()
        if review.status != "pass"
    ]

    report["ready"] = not (
        report["missing_fields"]
        or report["invalid_fields"]
        or report["missing_review_passes"]
        or report["failed_review_passes"]
        or report["duplicate_review_passes"]
    )
    return report


def _print_human(report: dict[str, Any]) -> None:
    state = "ready" if report["ready"] else "not ready"
    print(f"vidux publish scrutiny: {state}")
    checks = report.get("checks", {})
    if checks.get("resolved_plan_path"):
        print(f"  plan: {checks['resolved_plan_path']}")
    if report["missing_fields"]:
        print(f"  missing fields: {', '.join(report['missing_fields'])}")
    if report["missing_review_passes"]:
        print(f"  missing review passes: {', '.join(report['missing_review_passes'])}")
    if report["duplicate_review_passes"]:
        print(f"  duplicate review passes: {', '.join(report['duplicate_review_passes'])}")
    for item in report["invalid_fields"]:
        print(f"  invalid {item['field']}: {item['reason']}")
    for item in report["failed_review_passes"]:
        print(f"  failed {item['name']}: {item['evidence']}")
    if report["review_passes"]:
        rendered = ", ".join(
            f"{name}={payload['status']}"
            for name, payload in sorted(report["review_passes"].items())
        )
        print(f"  review passes: {rendered}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a publish packet has propagation metadata and self-scrutiny proof."
    )
    parser.add_argument("--lane", required=True, help="Lane id, e.g. vidux-self-improvement")
    parser.add_argument("--task", required=True, help="Owning PLAN.md task id.")
    parser.add_argument(
        "--summary",
        default="",
        help="Concise publish summary matching ledger-emit.sh --summary.",
    )
    parser.add_argument("--plan-path", required=True, help="Owning PLAN.md path.")
    parser.add_argument("--proof", required=True, help="Verification command or artifact.")
    parser.add_argument("--ledger", required=True, help="Publish ledger eid, e.g. evt_...")
    parser.add_argument(
        "--handoff-status",
        required=True,
        choices=sorted(HANDOFF_STATUSES),
        help="done, in_progress, blocked, or needs_review.",
    )
    parser.add_argument(
        "--file-claimed",
        action="append",
        default=[],
        help="Changed or claimed file/path entry. Repeat for multiple files.",
    )
    parser.add_argument(
        "--claim",
        action="append",
        default=[],
        help="Claimed file/path recorded in the publish ledger. Repeat as needed.",
    )
    parser.add_argument("--resume", required=True, help="Next-agent resume point.")
    parser.add_argument(
        "--review-pass",
        action="append",
        default=[],
        metavar="NAME:STATUS:EVIDENCE",
        help=(
            "Self-review result. Required names: invariant, regression, adversarial. "
            "Status is pass or fail."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of human text.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        reviews = [parse_review_pass(value) for value in args.review_pass]
        report = scrutinize_publish(
            lane=args.lane,
            task=args.task,
            summary=args.summary,
            plan_path=args.plan_path,
            proof=args.proof,
            ledger=args.ledger,
            handoff_status=args.handoff_status,
            files_claimed=args.file_claimed,
            claims=args.claim,
            resume=args.resume,
            review_passes=reviews,
        )
    except ValueError as exc:
        sys.stderr.write(f"vidux-publish-scrutiny: {exc}\n")
        return 2

    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        _print_human(report)
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
