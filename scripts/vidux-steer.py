#!/usr/bin/env python3
"""CLI for Vidux's local, provider-neutral one-shot steering mailbox."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
BROWSER_DIR = ROOT / "browser"
sys.path.insert(0, str(BROWSER_DIR))

from safe_files import UnsafeFileAliasError  # noqa: E402
from server import has_sensitive_text  # noqa: E402
from steering_mailbox import (  # noqa: E402
    DEFAULT_LEASE_SECONDS,
    DEFAULT_STORE,
    INTENT_MAX_BYTES,
    MAX_LEASE_SECONDS,
    MIN_LEASE_SECONDS,
    SAFE_FAILURE_CODES,
    MailboxError,
    MailboxValidationError,
    SteeringMailbox,
)


STDIN_JSON_ENVELOPE_BYTES = 4 * 1024
STDIN_JSON_MAX_BYTES = INTENT_MAX_BYTES * 6 + STDIN_JSON_ENVELOPE_BYTES


def _default_store() -> Path:
    return Path(os.environ.get("VIDUX_BROWSER_STEERING_FILE", DEFAULT_STORE)).expanduser()


def _default_root() -> Path:
    return Path(os.environ.get("VIDUX_DEV_ROOT", Path.home() / "Development")).expanduser()


def _add_runtime_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store",
        default=str(_default_store()),
        help=(
            "local steering JSONL path (default: VIDUX_BROWSER_STEERING_FILE "
            "or ~/.vidux-browser/steering.jsonl)"
        ),
    )
    parser.add_argument(
        "--root",
        default=str(_default_root()),
        help="allowed development root (default: VIDUX_DEV_ROOT or ~/Development)",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")


def _add_stdin_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--stdin-json",
        action="store_true",
        help=(
            "read missing request fields as one JSON object from stdin; "
            "preferred for lease tokens"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vidux-steer.py",
        description=(
            "Queue and lease one-shot intent at an Authority PLAN boundary. "
            "This command never invokes a provider, shell, goal, loop, or scheduler."
        ),
    )
    actions = parser.add_subparsers(dest="action", required=True)

    enqueue = actions.add_parser("enqueue", help="queue local intent for one PLAN.md")
    enqueue.add_argument("--plan", help="Authority PLAN.md")
    enqueue.add_argument("--message", help="intent text, maximum 8 KiB")
    enqueue.add_argument("--source", help="optional non-secret source label")
    _add_stdin_json_flag(enqueue)
    _add_runtime_flags(enqueue)

    list_parser = actions.add_parser("list", help="list active intent for one PLAN.md")
    list_parser.add_argument("--plan", required=True, help="Authority PLAN.md")
    list_parser.add_argument(
        "--all",
        action="store_true",
        help="include bounded bodyless acknowledged/dismissed tombstones",
    )
    _add_runtime_flags(list_parser)

    lease = actions.add_parser(
        "lease",
        help="lease the oldest queued item for one PLAN.md; requires --json",
    )
    lease.add_argument("--plan", help="Authority PLAN.md")
    lease.add_argument("--consumer", help="local non-secret consumer label")
    lease.add_argument(
        "--lease-seconds",
        type=int,
        default=None,
        help=(
            f"lease lifetime ({MIN_LEASE_SECONDS}-{MAX_LEASE_SECONDS}; "
            f"default {DEFAULT_LEASE_SECONDS})"
        ),
    )
    _add_stdin_json_flag(lease)
    _add_runtime_flags(lease)

    ack = actions.add_parser("ack", help="acknowledge only after the host accepted the response")
    ack.add_argument("--id", help="leased item UUID")
    ack.add_argument(
        "--lease-token",
        help="opaque lease token; --stdin-json avoids exposing it in argv",
    )
    _add_stdin_json_flag(ack)
    _add_runtime_flags(ack)

    fail = actions.add_parser("fail", help="record a safe retryable or terminal failure code")
    fail.add_argument("--id", help="leased item UUID")
    fail.add_argument(
        "--lease-token",
        help="opaque lease token; --stdin-json avoids exposing it in argv",
    )
    fail.add_argument("--code", choices=sorted(SAFE_FAILURE_CODES), help="safe public failure code")
    _add_stdin_json_flag(fail)
    _add_runtime_flags(fail)

    retry = actions.add_parser(
        "retry",
        help="return one retryable item to its original FIFO position",
    )
    retry.add_argument("--id", help="retryable item UUID")
    _add_stdin_json_flag(retry)
    _add_runtime_flags(retry)

    dismiss = actions.add_parser("dismiss", help="remove one unclaimed active item")
    dismiss.add_argument("--id", help="active item UUID")
    _add_stdin_json_flag(dismiss)
    _add_runtime_flags(dismiss)

    return parser


def _stdin_payload(enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {}
    raw = sys.stdin.buffer.read(STDIN_JSON_MAX_BYTES + 1)
    if len(raw) > STDIN_JSON_MAX_BYTES:
        raise MailboxValidationError(f"stdin JSON exceeds {STDIN_JSON_MAX_BYTES} bytes")
    if not raw.strip():
        raise MailboxValidationError("--stdin-json requires one JSON object")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        detail = exc.msg if isinstance(exc, json.JSONDecodeError) else "invalid UTF-8"
        raise MailboxValidationError(f"stdin JSON is malformed: {detail}") from exc
    if not isinstance(payload, dict):
        raise MailboxValidationError("stdin JSON must be an object")
    return payload


def _value(args: argparse.Namespace, payload: dict[str, Any], name: str, *, required: bool) -> Any:
    value = getattr(args, name, None)
    if value is None:
        value = payload.get(name)
    if required and (value is None or value == ""):
        raise MailboxValidationError(f"{name.replace('_', '-')} is required")
    return value


def _mailbox(args: argparse.Namespace) -> SteeringMailbox:
    return SteeringMailbox(
        args.store,
        dev_root=args.root,
        sensitive_check=has_sensitive_text,
    )


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _terminal_safe(value: object) -> str:
    safe: list[str] = []
    for character in str(value):
        code = ord(character)
        safe.append(
            f"\\x{code:02x}" if code < 32 or 127 <= code <= 159 else character
        )
    return "".join(safe)


def _print_human(action: str, payload: dict[str, Any]) -> None:
    if action == "list":
        items = payload.get("items", [])
        if not items:
            print("No active steering intent.")
        for item in items:
            body = " ".join(_terminal_safe(item.get("body", "")).split())
            if len(body) > 120:
                body = body[:117] + "..."
            failure = f" ({item['failure_code']})" if item.get("failure_code") else ""
            print(f"{item['state']}{failure}  {item['id']}  {body}")
        tombstones = payload.get("tombstones", [])
        for row in tombstones:
            print(f"{row['final_state']}  {row['id']}")
        if payload.get("journal_error"):
            print(
                f"warning: {_terminal_safe(payload['journal_error'])}",
                file=sys.stderr,
            )
        return

    item = payload.get("item")
    tombstone = payload.get("tombstone")
    if action == "enqueue" and item:
        print(f"queued {item['id']} for {_terminal_safe(item['plan_path'])}")
    elif action == "lease":
        if item is None:
            print("No queued steering intent.")
        else:
            print(
                f"claimed {item['id']}; lease token intentionally hidden "
                "(use --json for a local host handoff)"
            )
    elif action == "ack" and tombstone:
        print(f"acknowledged {tombstone['id']}")
    elif action == "dismiss" and tombstone:
        print(f"dismissed {tombstone['id']}")
    elif action in {"fail", "retry"} and item:
        suffix = f" ({item['failure_code']})" if item.get("failure_code") else ""
        print(f"{item['state']}{suffix} {item['id']}")


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    payload = _stdin_payload(getattr(args, "stdin_json", False))
    mailbox = _mailbox(args)

    if args.action == "enqueue":
        item = mailbox.enqueue_intent(
            _value(args, payload, "plan", required=True),
            _value(args, payload, "message", required=True),
            source=_value(args, payload, "source", required=False) or "",
        )
        return 0, {"ok": True, "item": item}

    if args.action == "list":
        result = mailbox.read_mailbox(
            plan_path=args.plan,
            include_tombstones=args.all,
        )
        return (0 if result["ok"] else 1), result

    if args.action == "lease":
        if not args.json:
            raise MailboxValidationError(
                "lease requires --json so the one-time lease token is not discarded"
            )
        raw_seconds = _value(args, payload, "lease_seconds", required=False)
        lease_seconds = DEFAULT_LEASE_SECONDS if raw_seconds is None else raw_seconds
        if isinstance(lease_seconds, bool):
            raise MailboxValidationError("lease-seconds must be an integer")
        try:
            lease_seconds = int(lease_seconds)
        except (TypeError, ValueError) as exc:
            raise MailboxValidationError("lease-seconds must be an integer") from exc
        item = mailbox.lease_next_intent(
            _value(args, payload, "plan", required=True),
            _value(args, payload, "consumer", required=True),
            lease_seconds=lease_seconds,
        )
        return 0, {"ok": True, "item": item}

    if args.action == "ack":
        tombstone = mailbox.acknowledge_intent(
            _value(args, payload, "id", required=True),
            _value(args, payload, "lease_token", required=True),
        )
        return 0, {"ok": True, "tombstone": tombstone}

    if args.action == "fail":
        item = mailbox.fail_intent(
            _value(args, payload, "id", required=True),
            _value(args, payload, "lease_token", required=True),
            _value(args, payload, "code", required=True),
        )
        return 0, {"ok": True, "item": item}

    if args.action == "retry":
        item = mailbox.retry_intent(_value(args, payload, "id", required=True))
        return 0, {"ok": True, "item": item}

    if args.action == "dismiss":
        tombstone = mailbox.dismiss_intent(_value(args, payload, "id", required=True))
        return 0, {"ok": True, "tombstone": tombstone}

    raise MailboxValidationError("unknown steering action")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code, payload = run(args)
    except (MailboxError, UnsafeFileAliasError, OSError) as exc:
        payload = {"ok": False, "error": str(exc)}
        if args.json:
            _print_json(payload)
        else:
            print(f"vidux-steer.py: {_terminal_safe(exc)}", file=sys.stderr)
        return 1

    if args.json:
        _print_json(payload)
    else:
        _print_human(args.action, payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
