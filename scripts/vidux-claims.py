#!/usr/bin/env python3
"""Provider-neutral claim, heartbeat, checkpoint, and handoff CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BROWSER_DIR = ROOT / "browser"
if str(BROWSER_DIR) not in sys.path:
    sys.path.insert(0, str(BROWSER_DIR))

from coordination_claims import (  # noqa: E402
    ALLOWED_RELEASE_STATUSES,
    DEFAULT_HANDOFF_LIMIT,
    DEFAULT_TTL_HOURS,
    ClaimsConflictError,
    ClaimsError,
    ClaimsJournalError,
    CoordinationClaims,
    utc_now,
    utc_stamp,
)


def _default_claims_file() -> Path:
    override = os.environ.get("VIDUX_CLAIMS_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".agent-ledger" / "claims.jsonl"


_FALLBACK_OWNER: str | None = None


def _default_owner() -> str:
    for key in (
        "VIDUX_OWNER",
        "CODEX_THREAD_ID",
        "CODEX_AGENT_ID",
        "CLAUDE_SESSION_ID",
        "CLAUDE_AUTOMATION_NAME",
    ):
        value = os.environ.get(key)
        if value:
            return value
    # Never collapse unrelated interactive chats onto the account-wide USER
    # label, and never embed the raw process id: this owner string is surfaced
    # verbatim on the loopback /api/coordination panel, which guarantees no PID
    # crosses that HTTP boundary. A random per-process
    # token fails safe across separate invocations without leaking the PID; real
    # loop adapters supply a stable task/thread identity explicitly. Memoized so
    # one process keeps one stable fallback owner across its own subcommands.
    global _FALLBACK_OWNER
    if _FALLBACK_OWNER is None:
        _FALLBACK_OWNER = f"manual-{secrets.token_hex(4)}"
    return _FALLBACK_OWNER


def _claim_id(*, repo: str, claim: str, owner: str) -> str:
    now = utc_stamp(utc_now())
    seed = f"{repo}\0{claim}\0{owner}\0{now}\0{os.getpid()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"clm_{digest}"


def _print(payload: dict) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _store(args: argparse.Namespace) -> CoordinationClaims:
    return CoordinationClaims(Path(args.claims_file).expanduser())


def _claim(args: argparse.Namespace) -> int:
    result = _store(args).claim(
        claim_id=_claim_id(repo=args.repo, claim=args.claim, owner=args.owner),
        repo=args.repo,
        claim=args.claim,
        owner=args.owner,
        lane=args.lane,
        plan_path=args.plan_path,
        task_id=args.task_id,
        ttl_hours=args.ttl_hours,
    )
    _print(result)
    return 0


def _heartbeat(args: argparse.Namespace) -> int:
    result = _store(args).heartbeat(
        claim_id=args.claim_id,
        owner=args.owner,
        ttl_hours=args.ttl_hours,
    )
    _print(result)
    return 0


def _checkpoint(args: argparse.Namespace) -> int:
    result = _store(args).checkpoint(
        claim_id=args.claim_id,
        owner=args.owner,
        summary=args.summary,
        resume=args.resume,
        proof=args.proof,
        ttl_hours=args.ttl_hours,
    )
    _print(result)
    return 0


def _release(args: argparse.Namespace) -> int:
    result = _store(args).release(
        claim_id=args.claim_id,
        repo=args.repo,
        claim=args.claim,
        owner=args.owner,
        status=args.status,
        summary=args.summary,
        resume=args.resume,
        proof=args.proof,
    )
    _print(result)
    return 0


def _active(args: argparse.Namespace) -> int:
    snapshot = _store(args).snapshot(repo=args.repo, claim=args.claim, handoff_limit=0)
    _print({"ok": True, "claims": snapshot["claims"]})
    return 0


def _snapshot(args: argparse.Namespace) -> int:
    _print(
        _store(args).snapshot(
            repo=args.repo,
            claim=args.claim,
            handoff_limit=args.handoff_limit,
        )
    )
    return 0


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return parsed


def _bounded_count(value: str) -> int:
    parsed = int(value)
    if parsed < 0 or parsed > 256:
        raise argparse.ArgumentTypeError("must be between 0 and 256")
    return parsed


def _add_claims_file_argument(
    parser: argparse.ArgumentParser,
    *,
    default: str = argparse.SUPPRESS,
) -> None:
    parser.add_argument(
        "--claims-file",
        default=default,
        help=(
            "Claims JSONL path. Defaults to VIDUX_CLAIMS_FILE or "
            "~/.agent-ledger/claims.jsonl."
        ),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provider-neutral Vidux work-surface lease bus."
    )
    _add_claims_file_argument(parser, default=str(_default_claims_file()))
    sub = parser.add_subparsers(dest="command", required=True)

    claim = sub.add_parser("claim", help="Claim a work surface or resume an available handoff.")
    _add_claims_file_argument(claim)
    claim.add_argument("--repo", required=True)
    claim.add_argument("--claim", required=True, help="Work surface, file path, or plan row.")
    claim.add_argument("--owner", default=_default_owner())
    claim.add_argument("--lane", required=True)
    claim.add_argument("--plan-path", required=True)
    claim.add_argument("--task-id", required=True)
    claim.add_argument("--ttl-hours", type=_positive_float, default=DEFAULT_TTL_HOURS)
    claim.set_defaults(func=_claim)

    heartbeat = sub.add_parser("heartbeat", help="Renew an active lease held by this owner.")
    _add_claims_file_argument(heartbeat)
    heartbeat.add_argument("--claim-id", required=True)
    heartbeat.add_argument("--owner", default=_default_owner())
    heartbeat.add_argument("--ttl-hours", type=_positive_float)
    heartbeat.set_defaults(func=_heartbeat)

    checkpoint = sub.add_parser(
        "checkpoint", help="Persist bounded resume state and renew an active lease."
    )
    _add_claims_file_argument(checkpoint)
    checkpoint.add_argument("--claim-id", required=True)
    checkpoint.add_argument("--owner", default=_default_owner())
    checkpoint.add_argument("--summary", required=True)
    checkpoint.add_argument("--resume", required=True)
    checkpoint.add_argument("--proof", default="")
    checkpoint.add_argument("--ttl-hours", type=_positive_float)
    checkpoint.set_defaults(func=_checkpoint)

    release = sub.add_parser("release", help="Release a lease by id or repo and work surface.")
    _add_claims_file_argument(release)
    release.add_argument("--claim-id")
    release.add_argument("--repo")
    release.add_argument("--claim")
    release.add_argument("--owner", default=_default_owner())
    release.add_argument(
        "--status",
        choices=sorted(ALLOWED_RELEASE_STATUSES),
        default="",
        help="release outcome; omitted for a plain completed release",
    )
    release.add_argument("--summary", default="")
    release.add_argument("--resume", default="")
    release.add_argument("--proof", default="")
    release.set_defaults(func=_release)

    active = sub.add_parser("active", help="List live, unexpired leases.")
    _add_claims_file_argument(active)
    active.add_argument("--repo")
    active.add_argument("--claim")
    active.set_defaults(func=_active)

    snapshot = sub.add_parser(
        "snapshot", help="Project live leases plus resumable handoffs without host or pid."
    )
    _add_claims_file_argument(snapshot)
    snapshot.add_argument("--repo")
    snapshot.add_argument("--claim")
    snapshot.add_argument(
        "--handoff-limit", type=_bounded_count, default=DEFAULT_HANDOFF_LIMIT
    )
    snapshot.set_defaults(func=_snapshot)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        return int(args.func(args))
    except ClaimsConflictError as exc:
        payload: dict = {"ok": False, "status": "conflict", "error": str(exc)}
        if exc.active:
            payload["active"] = exc.active
        _print(payload)
        return 3
    except (ClaimsError, OSError, ValueError) as exc:
        sys.stderr.write(f"vidux-claims: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
