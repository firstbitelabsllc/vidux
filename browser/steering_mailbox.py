"""Provider-neutral, plan-scoped storage for one-shot steering intent.

The mailbox is deliberately transport-only.  It validates and journals local
intent, leases one FIFO item to a host process, and records the host's
post-response acknowledgement.  It never invokes a provider, shell, goal, or
scheduler.
"""

from __future__ import annotations

import fcntl
import fnmatch
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from glob import glob
from pathlib import Path
from typing import Callable, Iterator

from safe_files import atomic_write_text, open_regular_fd, read_text


SCHEMA_VERSION = 1
DEFAULT_STORE = Path.home() / ".vidux-browser" / "steering.jsonl"
INTENT_MAX_BYTES = 8 * 1024
LABEL_MAX_CHARS = 80
ACTIVE_LIMIT_PER_PLAN = 8
DEFAULT_LEASE_SECONDS = 300
MIN_LEASE_SECONDS = 5
MAX_LEASE_SECONDS = 3600
DEFAULT_TOMBSTONE_LIMIT = 64
COMPACT_EVENT_LIMIT = 512
DISCOVERY_CACHE_TTL_SECONDS = 20.0
DEFAULT_PLAN_GLOBS = (
    "*/ai/plans/*/PLAN.md",
    "*/vidux/*/PLAN.md",
    "*/vidux/**/PLAN.md",
    "*/projects/*/PLAN.md",
    "*/projects/**/PLAN.md",
    "*/.cursor/plans/*.plan.md",
    "*/.cursor/plans/**/*.plan.md",
    "*/PLAN.md",
)

ACTIVE_STATES = frozenset({"queued", "claimed", "retryable", "failed"})
JOURNAL_EVENT_KINDS = frozenset(
    {"enqueue", "snapshot", "tombstone", "lease", "fail", "retry", "ack", "dismiss"}
)
RETRYABLE_FAILURE_CODES = frozenset(
    {
        "usage_exhausted",
        "transport_unavailable",
        "lease_expired",
        "response_unconfirmed",
    }
)
TERMINAL_FAILURE_CODES = frozenset({"invalid_intent", "policy_blocked"})
SAFE_FAILURE_CODES = RETRYABLE_FAILURE_CODES | TERMINAL_FAILURE_CODES

_LABEL_RE = re.compile(r"^[A-Za-z0-9_.:/@' -]+$")
_PROCESS_LOCK = threading.Lock()
_DISCOVERY_CACHE_LOCK = threading.Lock()
_DISCOVERY_CACHE: dict[tuple, tuple[float, frozenset[Path]]] = {}


class MailboxError(RuntimeError):
    """Base error for a refused mailbox operation."""


class MailboxValidationError(MailboxError):
    """Input does not satisfy the public mailbox contract."""


class MailboxConflictError(MailboxError):
    """The requested state transition is stale or not currently allowed."""


class JournalCorruptError(MailboxError):
    """The journal contains a malformed record or invalid transition."""


@dataclass
class _ReducedJournal:
    events: list[dict]
    items: dict[str, dict]
    tombstones: list[dict]
    error: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_stamp(value: datetime | None = None) -> str:
    moment = value or utc_now()
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def parse_stamp(raw: object, field: str = "timestamp") -> datetime:
    if not isinstance(raw, str) or not raw:
        raise MailboxValidationError(f"{field} must be a UTC timestamp")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MailboxValidationError(f"{field} must be a UTC timestamp") from exc
    if value.tzinfo is None:
        raise MailboxValidationError(f"{field} must include a timezone")
    return value.astimezone(timezone.utc)


def is_authority_plan_name(name: str) -> bool:
    """Accept canonical Vidux plans and repo-native named authority plans."""
    return name == "PLAN.md" or (
        name.endswith(".plan.md") and len(name) > len(".plan.md")
    )


def canonical_plan_path(raw: str | Path, dev_root: str | Path) -> Path:
    try:
        candidate = Path(raw).expanduser()
    except (TypeError, ValueError) as exc:
        raise MailboxValidationError("plan must name an existing PLAN.md") from exc
    if not is_authority_plan_name(candidate.name):
        raise MailboxValidationError(
            "plan must name an existing PLAN.md or *.plan.md authority"
        )
    root = Path(dev_root).expanduser().resolve()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise MailboxValidationError("plan must name an existing PLAN.md") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise MailboxValidationError("plan must be inside the configured development root") from exc
    try:
        path_stat = resolved.stat()
    except OSError as exc:
        raise MailboxValidationError("plan must name an existing PLAN.md") from exc
    if not resolved.is_file() or path_stat.st_nlink != 1:
        raise MailboxValidationError("plan must be a regular single-link file")
    return resolved


def _journal_plan_path(raw: object) -> str:
    """Validate immutable identity from storage without touching the filesystem."""
    if not isinstance(raw, str) or not raw:
        raise JournalCorruptError("stored plan path must be an absolute PLAN.md")
    try:
        candidate = Path(raw)
    except (TypeError, ValueError) as exc:
        raise JournalCorruptError("stored plan path must be an absolute PLAN.md") from exc
    if not candidate.is_absolute() or not is_authority_plan_name(candidate.name):
        raise JournalCorruptError(
            "stored plan path must be an absolute PLAN.md or *.plan.md authority"
        )
    if str(candidate) != raw or os.path.normpath(raw) != raw:
        raise JournalCorruptError("stored plan path must be canonical")
    return raw


def _glob_parts_match(path_parts: tuple[str, ...], pattern_parts: tuple[str, ...]) -> bool:
    """Match one DEV_ROOT-relative path with pathlib-style recursive globs."""
    if not pattern_parts:
        return not path_parts
    head, *tail = pattern_parts
    remaining = tuple(tail)
    if head == "**":
        return _glob_parts_match(path_parts, remaining) or bool(path_parts) and (
            _glob_parts_match(path_parts[1:], pattern_parts)
        )
    return bool(path_parts) and fnmatch.fnmatchcase(path_parts[0], head) and (
        _glob_parts_match(path_parts[1:], remaining)
    )


def _clean_label(raw: object, field: str, *, required: bool) -> str:
    if raw is None:
        text = ""
    elif not isinstance(raw, str):
        raise MailboxValidationError(f"{field} must be text")
    else:
        text = raw.strip()
    if not text:
        if required:
            raise MailboxValidationError(f"{field} must be non-empty")
        return ""
    if len(text) > LABEL_MAX_CHARS or not _LABEL_RE.fullmatch(text):
        raise MailboxValidationError(
            f"{field} must be at most {LABEL_MAX_CHARS} safe label characters"
        )
    return text


def _valid_uuid(raw: object) -> str:
    try:
        return str(uuid.UUID(str(raw)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise MailboxValidationError("item id must be a UUID") from exc


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public_item(item: dict) -> dict:
    result = {
        "id": item["id"],
        "plan_path": item["plan_path"],
        "body": item["body"],
        "state": item["state"],
        "created_at": item["created_at"],
        "attempts": item["attempts"],
        "plan_available": item.get("_plan_available", True),
    }
    for field in ("source", "claimed_at", "lease_expires_at", "failure_code", "updated_at"):
        if item.get(field):
            result[field] = item[field]
    return result


def _public_tombstone(tombstone: dict) -> dict:
    return {
        field: tombstone[field]
        for field in (
            "schema",
            "event",
            "id",
            "plan_path",
            "final_state",
            "created_at",
            "completed_at",
        )
    }


class SteeringMailbox:
    """Alias-safe, cross-process mailbox over a compactable JSONL journal."""

    def __init__(
        self,
        store_path: str | Path = DEFAULT_STORE,
        *,
        dev_root: str | Path,
        sensitive_check: Callable[[str], bool],
        active_limit: int = ACTIVE_LIMIT_PER_PLAN,
        tombstone_limit: int = DEFAULT_TOMBSTONE_LIMIT,
        plan_globs: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        if active_limit < 1:
            raise ValueError("active_limit must be positive")
        if tombstone_limit < 0:
            raise ValueError("tombstone_limit must not be negative")
        self.store_path = Path(store_path).expanduser()
        self.dev_root = Path(dev_root).expanduser().resolve()
        self.sensitive_check = sensitive_check
        self.active_limit = active_limit
        self.tombstone_limit = tombstone_limit
        configured_globs = os.environ.get("VIDUX_PLAN_GLOBS", "")
        self.plan_globs = tuple(
            plan_globs
            if plan_globs is not None
            else configured_globs.split(":") if configured_globs else DEFAULT_PLAN_GLOBS
        )
        if not self.plan_globs or any(not pattern for pattern in self.plan_globs):
            raise ValueError("plan_globs must contain non-empty patterns")
        self.repo_aliases = self._parse_repo_aliases(
            os.environ.get("VIDUX_REPO_ALIASES", "")
        )

    @staticmethod
    def _parse_repo_aliases(raw: str) -> dict[str, str]:
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(key): str(value) for key, value in parsed.items()}

    def _plan_matches_discovery_glob(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.dev_root)
        except ValueError:
            return False
        if "node_modules" in relative.parts:
            return False
        return any(
            _glob_parts_match(relative.parts, Path(pattern).parts)
            for pattern in self.plan_globs
        )

    def _discovered_plan_paths(self, *, force_refresh: bool = False) -> set[Path]:
        """Reproduce the cockpit's path discovery and legacy-repo dedupe."""
        cache_key = (
            str(self.dev_root),
            self.plan_globs,
            tuple(sorted(self.repo_aliases.items())),
            id(self.sensitive_check),
        )
        now = time.monotonic()
        with _DISCOVERY_CACHE_LOCK:
            cached = _DISCOVERY_CACHE.get(cache_key)
            if not force_refresh and cached and cached[0] > now:
                return set(cached[1])

        seen: set[Path] = set()
        winners: dict[tuple[str, ...], tuple[Path, int, int]] = {}
        for pattern in self.plan_globs:
            for hit in glob(str(self.dev_root / pattern), recursive=True):
                try:
                    path = Path(hit).resolve(strict=True)
                    relative = path.relative_to(self.dev_root)
                    if path in seen or not path.is_file():
                        continue
                    if "node_modules" in relative.parts:
                        continue
                    if self.sensitive_check(str(path)):
                        continue
                    stat = path.stat()
                    if stat.st_nlink != 1:
                        continue
                except (OSError, ValueError):
                    continue
                seen.add(path)
                repo = relative.parts[0]
                canonical_repo = self.repo_aliases.get(repo, repo)
                key = (canonical_repo, *relative.parts[1:])
                preference = 0 if repo in self.repo_aliases else 1
                candidate = (path, preference, stat.st_mtime_ns)
                current = winners.get(key)
                if current is None or candidate[1:] > current[1:]:
                    winners[key] = candidate
        paths = frozenset(candidate[0] for candidate in winners.values())
        with _DISCOVERY_CACHE_LOCK:
            if len(_DISCOVERY_CACHE) >= 64:
                oldest_key = min(
                    _DISCOVERY_CACHE,
                    key=lambda key: _DISCOVERY_CACHE[key][0],
                )
                _DISCOVERY_CACHE.pop(oldest_key, None)
            _DISCOVERY_CACHE[cache_key] = (
                now + DISCOVERY_CACHE_TTL_SECONDS,
                paths,
            )
        return set(paths)

    def _canonical_discovered_plan(self, raw: str | Path) -> Path:
        path = canonical_plan_path(raw, self.dev_root)
        if not self._plan_matches_discovery_glob(path):
            raise MailboxValidationError(
                "plan must be an authority plan discovered by the Vidux cockpit"
            )
        discovered = self._discovered_plan_paths()
        relative = path.relative_to(self.dev_root)
        if path not in discovered or relative.parts[0] in self.repo_aliases:
            discovered = self._discovered_plan_paths(force_refresh=True)
        if path not in discovered:
            raise MailboxValidationError(
                "plan must be an authority plan discovered by the Vidux cockpit"
            )
        return path

    @property
    def lock_path(self) -> Path:
        return self.store_path.with_suffix(self.store_path.suffix + ".lock")

    @contextmanager
    def _write_guard(self) -> Iterator[None]:
        with _PROCESS_LOCK, ExitStack() as stack:
            lock_fd = stack.enter_context(
                open_regular_fd(
                    self.lock_path,
                    os.O_RDWR | os.O_CREAT,
                    create_parent=True,
                )
            )
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)

    def _read_text(self) -> str:
        try:
            return read_text(self.store_path)
        except FileNotFoundError:
            return ""

    def _read_reduced(self, *, now: datetime | None = None) -> _ReducedJournal:
        try:
            text = self._read_text()
        except UnicodeDecodeError:
            return _ReducedJournal([], {}, [], "journal is not valid UTF-8")
        return self._reduce(text, now=now)

    def _reduce(self, text: str, *, now: datetime | None = None) -> _ReducedJournal:
        events: list[dict] = []
        items: dict[str, dict] = {}
        tombstones: list[dict] = []
        error: str | None = None

        for line_number, raw_line in enumerate(text.splitlines(), 1):
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line)
                self._apply_event(event, items, tombstones, line_number)
            except (
                json.JSONDecodeError,
                MailboxError,
                KeyError,
                OSError,
                TypeError,
                ValueError,
            ) as exc:
                error = self._safe_journal_error(line_number, exc)
                break
            events.append(event)

        self._project_expired(items, now=now or utc_now())
        self._project_plan_availability(items)
        return _ReducedJournal(events, items, tombstones, error)

    def _safe_journal_error(self, line_number: int, exc: BaseException) -> str:
        detail = str(exc) or "journal record is invalid"
        if self.sensitive_check(detail):
            detail = "journal record is invalid"
        detail = "".join(
            character if 32 <= ord(character) < 127 else "?"
            for character in detail
        )
        return f"journal line {line_number}: {detail[:160]}"

    def _apply_event(
        self,
        event: object,
        items: dict[str, dict],
        tombstones: list[dict],
        line_number: int,
    ) -> None:
        if not isinstance(event, dict):
            raise JournalCorruptError("record must be an object")
        if event.get("schema") != SCHEMA_VERSION:
            raise JournalCorruptError("unsupported schema version")
        kind = event.get("event")
        if not isinstance(kind, str) or kind not in JOURNAL_EVENT_KINDS:
            raise JournalCorruptError("unknown event type")
        item_id = _valid_uuid(event.get("id"))

        if kind == "enqueue":
            if item_id in items or any(row.get("id") == item_id for row in tombstones):
                raise JournalCorruptError("duplicate enqueue id")
            plan_path = _journal_plan_path(event.get("plan_path"))
            body = event.get("body")
            if not isinstance(body, str) or not body.strip():
                raise JournalCorruptError("enqueue body must be non-empty")
            if len(body.encode("utf-8")) > INTENT_MAX_BYTES:
                raise JournalCorruptError("enqueue body exceeds byte limit")
            created_at = event.get("created_at")
            parse_stamp(created_at, "created_at")
            source = _clean_label(event.get("source", ""), "source", required=False)
            if self.sensitive_check(f"{plan_path}\n{body}\n{source}"):
                raise JournalCorruptError("enqueue contains sensitive content")
            items[item_id] = {
                "id": item_id,
                "plan_path": plan_path,
                "body": body,
                "source": source,
                "state": "queued",
                "created_at": created_at,
                "attempts": 0,
                "_sequence": line_number,
            }
            return

        if kind == "snapshot":
            if item_id in items or any(row.get("id") == item_id for row in tombstones):
                raise JournalCorruptError("duplicate snapshot id")
            state = event.get("state")
            if state not in ACTIVE_STATES:
                raise JournalCorruptError("snapshot state is invalid")
            plan_path = _journal_plan_path(event.get("plan_path"))
            body = event.get("body")
            if not isinstance(body, str) or not body.strip():
                raise JournalCorruptError("snapshot body must be non-empty")
            if len(body.encode("utf-8")) > INTENT_MAX_BYTES:
                raise JournalCorruptError("snapshot body exceeds byte limit")
            created_at = event.get("created_at")
            parse_stamp(created_at, "created_at")
            attempts = event.get("attempts", 0)
            if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
                raise JournalCorruptError("snapshot attempts is invalid")
            item = {
                "id": item_id,
                "plan_path": plan_path,
                "body": body,
                "source": _clean_label(event.get("source", ""), "source", required=False),
                "state": state,
                "created_at": created_at,
                "attempts": attempts,
                "_sequence": line_number,
            }
            for field in (
                "claimed_at",
                "lease_expires_at",
                "lease_token_hash",
                "failure_code",
                "updated_at",
                "consumer",
                "last_lease_token_hash",
            ):
                if field in event:
                    item[field] = event[field]
            self._validate_snapshot_state(item)
            if self.sensitive_check(
                f"{plan_path}\n{body}\n{item.get('source', '')}\n{item.get('consumer', '')}"
            ):
                raise JournalCorruptError("snapshot contains sensitive content")
            items[item_id] = item
            return

        if kind == "tombstone":
            if item_id in items or any(row.get("id") == item_id for row in tombstones):
                raise JournalCorruptError("duplicate tombstone id")
            final_state = event.get("final_state")
            if final_state not in {"acknowledged", "dismissed"}:
                raise JournalCorruptError("tombstone state is invalid")
            plan_path = _journal_plan_path(event.get("plan_path"))
            completed_at = event.get("completed_at")
            completed_moment = parse_stamp(completed_at, "completed_at")
            created_at = event.get("created_at")
            created_moment = parse_stamp(created_at, "created_at")
            if completed_moment < created_moment:
                raise JournalCorruptError("tombstone completion precedes creation")
            if self.sensitive_check(plan_path):
                raise JournalCorruptError("tombstone contains sensitive content")
            tombstone = {
                "schema": SCHEMA_VERSION,
                "event": "tombstone",
                "id": item_id,
                "plan_path": plan_path,
                "final_state": final_state,
                "created_at": created_at,
                "completed_at": completed_at,
            }
            token_hash = event.get("lease_token_hash")
            if final_state == "acknowledged":
                if not (
                    isinstance(token_hash, str)
                    and re.fullmatch(r"[0-9a-f]{64}", token_hash)
                ):
                    raise JournalCorruptError("tombstone lease token hash is invalid")
                tombstone["lease_token_hash"] = token_hash
            elif token_hash is not None:
                raise JournalCorruptError("dismissed tombstone contains lease data")
            tombstones.append(tombstone)
            return

        item = items.get(item_id)
        if item is None:
            raise JournalCorruptError("journal event references an unknown id")

        if kind == "lease":
            if item["state"] != "queued":
                raise JournalCorruptError("lease requires queued state")
            claimed_at = event.get("claimed_at")
            lease_expires_at = event.get("lease_expires_at")
            claimed_moment = parse_stamp(claimed_at, "claimed_at")
            expires_moment = parse_stamp(lease_expires_at, "lease_expires_at")
            created_moment = parse_stamp(item["created_at"], "created_at")
            if claimed_moment < created_moment:
                raise JournalCorruptError("lease claim precedes creation")
            if expires_moment <= claimed_moment:
                raise JournalCorruptError("lease expiry must follow claim time")
            token_hash = event.get("lease_token_hash")
            if not isinstance(token_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", token_hash):
                raise JournalCorruptError("lease token hash is invalid")
            consumer = _clean_label(event.get("consumer"), "consumer", required=True)
            if self.sensitive_check(consumer):
                raise JournalCorruptError("lease consumer contains sensitive content")
            item.update(
                {
                    "state": "claimed",
                    "claimed_at": claimed_at,
                    "lease_expires_at": lease_expires_at,
                    "lease_token_hash": token_hash,
                    "consumer": consumer,
                    "attempts": item["attempts"] + 1,
                    "failure_code": None,
                    "updated_at": claimed_at,
                }
            )
            return

        if kind == "fail":
            if item["state"] != "claimed":
                raise JournalCorruptError("fail requires claimed state")
            code = event.get("code")
            if code not in SAFE_FAILURE_CODES:
                raise JournalCorruptError("failure code is not allowed")
            failed_at = event.get("failed_at")
            failed_moment = parse_stamp(failed_at, "failed_at")
            claimed_moment = parse_stamp(item["claimed_at"], "claimed_at")
            if failed_moment < claimed_moment:
                raise JournalCorruptError("failure precedes claim")
            item.update(
                {
                    "state": "retryable" if code in RETRYABLE_FAILURE_CODES else "failed",
                    "failure_code": code,
                    "updated_at": failed_at,
                    "last_lease_token_hash": item["lease_token_hash"],
                    "lease_token_hash": None,
                    "lease_expires_at": None,
                    "claimed_at": None,
                    "consumer": None,
                }
            )
            return

        if kind == "retry":
            if item["state"] != "retryable":
                raise JournalCorruptError("retry requires retryable state")
            retried_at = event.get("retried_at")
            retried_moment = parse_stamp(retried_at, "retried_at")
            updated_moment = parse_stamp(item["updated_at"], "updated_at")
            if retried_moment < updated_moment:
                raise JournalCorruptError("retry precedes prior update")
            item.update(
                {
                    "state": "queued",
                    "failure_code": None,
                    "updated_at": retried_at,
                    "last_lease_token_hash": None,
                    "lease_token_hash": None,
                    "lease_expires_at": None,
                    "claimed_at": None,
                    "consumer": None,
                }
            )
            return

        if kind in {"ack", "dismiss"}:
            # Terminal events are normally compacted immediately into a
            # bodyless tombstone, but accepting them makes an interrupted
            # pre-compaction write reducible and keeps the journal format
            # explicit.
            required_state = "claimed" if kind == "ack" else None
            if required_state and item["state"] != required_state:
                raise JournalCorruptError("ack requires claimed state")
            if kind == "dismiss" and item["state"] == "claimed":
                raise JournalCorruptError("claimed intent cannot be dismissed")
            completed_at = event.get("completed_at")
            completed_moment = parse_stamp(completed_at, "completed_at")
            created_moment = parse_stamp(item["created_at"], "created_at")
            if completed_moment < created_moment:
                raise JournalCorruptError("completion precedes creation")
            del items[item_id]
            tombstones.append(
                {
                    "schema": SCHEMA_VERSION,
                    "event": "tombstone",
                    "id": item_id,
                    "plan_path": item["plan_path"],
                    "final_state": "acknowledged" if kind == "ack" else "dismissed",
                    "created_at": item["created_at"],
                    "completed_at": completed_at,
                    "lease_token_hash": item.get("lease_token_hash"),
                }
            )
            return

        raise JournalCorruptError("unknown event type")

    def _validate_snapshot_state(self, item: dict) -> None:
        state = item["state"]
        created_moment = parse_stamp(item["created_at"], "created_at")
        updated_moment: datetime | None = None
        if "updated_at" in item:
            updated_moment = parse_stamp(item["updated_at"], "updated_at")
            if updated_moment < created_moment:
                raise JournalCorruptError("snapshot update precedes creation")

        lease_fields = (
            "claimed_at",
            "lease_expires_at",
            "lease_token_hash",
            "consumer",
        )
        last_token_hash = item.get("last_lease_token_hash")
        if state == "claimed":
            for field in lease_fields:
                if not item.get(field):
                    raise JournalCorruptError(f"claimed snapshot is missing {field}")
            claimed_moment = parse_stamp(item["claimed_at"], "claimed_at")
            expires_moment = parse_stamp(item["lease_expires_at"], "lease_expires_at")
            if claimed_moment < created_moment:
                raise JournalCorruptError("snapshot claim precedes creation")
            if expires_moment <= claimed_moment:
                raise JournalCorruptError("snapshot lease expiry must follow claim")
            if updated_moment is None or updated_moment < claimed_moment:
                raise JournalCorruptError("claimed snapshot has an invalid update time")
            if not re.fullmatch(r"[0-9a-f]{64}", str(item["lease_token_hash"])):
                raise JournalCorruptError("snapshot lease token hash is invalid")
            consumer = _clean_label(item["consumer"], "consumer", required=True)
            if self.sensitive_check(consumer):
                raise JournalCorruptError("snapshot consumer contains sensitive content")
            item["consumer"] = consumer
            if item.get("attempts", 0) < 1:
                raise JournalCorruptError("claimed snapshot has no lease attempt")
        elif any(field in item and item[field] is not None for field in lease_fields):
            raise JournalCorruptError("unclaimed snapshot contains lease data")

        code = item.get("failure_code")
        if state == "retryable":
            if code not in RETRYABLE_FAILURE_CODES:
                raise JournalCorruptError("retryable snapshot has an invalid failure code")
            if updated_moment is None or item.get("attempts", 0) < 1:
                raise JournalCorruptError("retryable snapshot has invalid history")
            if not isinstance(last_token_hash, str) or not re.fullmatch(
                r"[0-9a-f]{64}", last_token_hash
            ):
                raise JournalCorruptError("retryable snapshot has invalid prior lease")
        elif state == "failed":
            if code not in TERMINAL_FAILURE_CODES:
                raise JournalCorruptError("failed snapshot has an invalid failure code")
            if updated_moment is None or item.get("attempts", 0) < 1:
                raise JournalCorruptError("failed snapshot has invalid history")
            if not isinstance(last_token_hash, str) or not re.fullmatch(
                r"[0-9a-f]{64}", last_token_hash
            ):
                raise JournalCorruptError("failed snapshot has invalid prior lease")
        elif code is not None:
            raise JournalCorruptError("snapshot state contains a failure code")

        if state not in {"retryable", "failed"} and last_token_hash is not None:
            raise JournalCorruptError("snapshot state contains prior lease data")

        if state == "queued" and item.get("attempts", 0) > 0 and updated_moment is None:
            raise JournalCorruptError("retried snapshot is missing update time")

    def _project_expired(self, items: dict[str, dict], *, now: datetime) -> None:
        for item in items.values():
            if item["state"] != "claimed":
                continue
            if parse_stamp(item["lease_expires_at"], "lease_expires_at") > now:
                continue
            item.update(
                {
                    "state": "retryable",
                    "failure_code": "lease_expired",
                    "updated_at": utc_stamp(now),
                    "last_lease_token_hash": item["lease_token_hash"],
                    "lease_token_hash": None,
                    "lease_expires_at": None,
                    "claimed_at": None,
                    "consumer": None,
                    "_projected_expired": True,
                }
            )

    def _project_plan_availability(self, items: dict[str, dict]) -> None:
        alias_discovered: set[Path] | None = None
        for item in items.values():
            stored = item["plan_path"]
            try:
                path = Path(stored)
                resolved = path.resolve(strict=True)
                available = (
                    str(resolved) == stored
                    and resolved.is_file()
                    and resolved.stat().st_nlink == 1
                    and self._plan_matches_discovery_glob(resolved)
                )
                if available:
                    relative = resolved.relative_to(self.dev_root)
                    if relative.parts[0] in self.repo_aliases:
                        if alias_discovered is None:
                            alias_discovered = self._discovered_plan_paths(
                                force_refresh=True
                            )
                        available = resolved in alias_discovered
            except (OSError, ValueError):
                available = False
            item["_plan_available"] = available

    def _ensure_clean(self, reduced: _ReducedJournal) -> None:
        if reduced.error:
            raise JournalCorruptError(reduced.error)

    def _serialize_events(self, events: list[dict]) -> str:
        return "".join(
            json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n"
            for event in events
        )

    def _snapshot_event(self, item: dict) -> dict:
        event = {
            "schema": SCHEMA_VERSION,
            "event": "snapshot",
            "id": item["id"],
            "plan_path": item["plan_path"],
            "body": item["body"],
            "source": item.get("source", ""),
            "state": item["state"],
            "created_at": item["created_at"],
            "attempts": item["attempts"],
        }
        for field in (
            "claimed_at",
            "lease_expires_at",
            "lease_token_hash",
            "failure_code",
            "updated_at",
            "consumer",
            "last_lease_token_hash",
        ):
            if item.get(field):
                event[field] = item[field]
        return event

    def _compacted_events(self, reduced: _ReducedJournal) -> list[dict]:
        active = sorted(
            reduced.items.values(),
            key=lambda item: (parse_stamp(item["created_at"]), item["_sequence"]),
        )
        tombstones = reduced.tombstones[-self.tombstone_limit :] if self.tombstone_limit else []
        return [*(self._snapshot_event(item) for item in active), *tombstones]

    def _write_events(self, events: list[dict]) -> None:
        atomic_write_text(self.store_path, self._serialize_events(events), mode=0o600)

    def _append_and_write(self, reduced: _ReducedJournal, event: dict) -> None:
        # Expiry is projected during reads so listing remains side-effect free.
        # Before the next mutation, compact that projected state into snapshots
        # so the appended transition reduces from retryable rather than from the
        # stale on-disk lease event.
        if any(item.get("_projected_expired") for item in reduced.items.values()):
            events = [*self._compacted_events(reduced), event]
        else:
            events = [*reduced.events, event]
        if len(events) > COMPACT_EVENT_LIMIT:
            projected = self._reduce(self._serialize_events(events))
            self._ensure_clean(projected)
            events = self._compacted_events(projected)
        self._write_events(events)

    def read_mailbox(
        self,
        *,
        plan_path: str | Path | None = None,
        include_tombstones: bool = False,
        now: datetime | None = None,
    ) -> dict:
        plan = str(self._canonical_discovered_plan(plan_path)) if plan_path else None
        reduced = self._read_reduced(now=now)
        items = [
            _public_item(item)
            for item in sorted(
                reduced.items.values(),
                key=lambda row: (parse_stamp(row["created_at"]), row["_sequence"]),
            )
            if plan is None or item["plan_path"] == plan
        ]
        payload = {"ok": reduced.error is None, "items": items}
        if include_tombstones:
            payload["tombstones"] = [
                _public_tombstone(row)
                for row in reduced.tombstones
                if plan is None or row["plan_path"] == plan
            ]
        if reduced.error:
            payload["journal_error"] = reduced.error
        return payload

    def enqueue_intent(
        self,
        plan_path: str | Path,
        body: str,
        *,
        source: str = "",
        now: datetime | None = None,
    ) -> dict:
        plan = self._canonical_discovered_plan(plan_path)
        text = body.strip() if isinstance(body, str) else ""
        if not text:
            raise MailboxValidationError("intent must be non-empty")
        if len(text.encode("utf-8")) > INTENT_MAX_BYTES:
            raise MailboxValidationError(f"intent exceeds {INTENT_MAX_BYTES} bytes")
        clean_source = _clean_label(source, "source", required=False)
        if self.sensitive_check(f"{plan}\n{text}\n{clean_source}"):
            raise MailboxValidationError("intent contains sensitive content")

        created_at = utc_stamp(now)
        event = {
            "schema": SCHEMA_VERSION,
            "event": "enqueue",
            "id": str(uuid.uuid4()),
            "plan_path": str(plan),
            "body": text,
            "created_at": created_at,
            "source": clean_source,
        }
        with self._write_guard():
            reduced = self._read_reduced(now=now)
            self._ensure_clean(reduced)
            active_for_plan = sum(
                item["plan_path"] == str(plan) for item in reduced.items.values()
            )
            if active_for_plan >= self.active_limit:
                raise MailboxConflictError(
                    f"plan already has {self.active_limit} active steering items"
                )
            self._append_and_write(reduced, event)
        return {
            "id": event["id"],
            "plan_path": event["plan_path"],
            "body": text,
            "source": clean_source,
            "state": "queued",
            "created_at": created_at,
            "attempts": 0,
        }

    def lease_next_intent(
        self,
        plan_path: str | Path,
        consumer: str,
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now: datetime | None = None,
    ) -> dict | None:
        plan = str(self._canonical_discovered_plan(plan_path))
        clean_consumer = _clean_label(consumer, "consumer", required=True)
        if self.sensitive_check(clean_consumer):
            raise MailboxValidationError("consumer contains sensitive content")
        if not isinstance(lease_seconds, int) or not (
            MIN_LEASE_SECONDS <= lease_seconds <= MAX_LEASE_SECONDS
        ):
            raise MailboxValidationError(
                f"lease seconds must be between {MIN_LEASE_SECONDS} and {MAX_LEASE_SECONDS}"
            )
        moment = now or utc_now()

        with self._write_guard():
            reduced = self._read_reduced(now=moment)
            self._ensure_clean(reduced)
            if any(
                item["plan_path"] == plan
                and item["state"] == "claimed"
                and item.get("consumer") == clean_consumer
                for item in reduced.items.values()
            ):
                raise MailboxConflictError("consumer already holds a lease for this plan")
            eligible = sorted(
                (
                    item
                    for item in reduced.items.values()
                    if item["plan_path"] == plan and item["state"] == "queued"
                ),
                key=lambda item: (parse_stamp(item["created_at"]), item["_sequence"]),
            )
            if not eligible:
                return None
            item = eligible[0]
            token = secrets.token_urlsafe(32)
            claimed_at = utc_stamp(moment)
            expires_at = utc_stamp(moment + timedelta(seconds=lease_seconds))
            event = {
                "schema": SCHEMA_VERSION,
                "event": "lease",
                "id": item["id"],
                "consumer": clean_consumer,
                "claimed_at": claimed_at,
                "lease_expires_at": expires_at,
                "lease_token_hash": _token_hash(token),
            }
            self._append_and_write(reduced, event)

        result = _public_item(
            {
                **item,
                "state": "claimed",
                "claimed_at": claimed_at,
                "lease_expires_at": expires_at,
                "attempts": item["attempts"] + 1,
                "failure_code": None,
                "updated_at": claimed_at,
            }
        )
        result["lease_token"] = token
        return result

    def _require_claimed_token(self, reduced: _ReducedJournal, item_id: str, token: str) -> dict:
        item = reduced.items.get(_valid_uuid(item_id))
        if not item or item["state"] != "claimed":
            raise MailboxConflictError("item is not currently claimed")
        expected = item.get("lease_token_hash", "")
        if not isinstance(token, str) or not token or not hmac.compare_digest(
            expected, _token_hash(token)
        ):
            raise MailboxConflictError("lease token is stale or invalid")
        return item

    def acknowledge_intent(
        self,
        item_id: str,
        lease_token: str,
        *,
        now: datetime | None = None,
    ) -> dict:
        completed_at = utc_stamp(now)
        with self._write_guard():
            reduced = self._read_reduced(now=now)
            self._ensure_clean(reduced)
            normalized_id = _valid_uuid(item_id)
            prior = next(
                (
                    row
                    for row in reduced.tombstones
                    if row["id"] == normalized_id
                    and row["final_state"] == "acknowledged"
                ),
                None,
            )
            if prior is not None:
                expected = prior.get("lease_token_hash", "")
                if not isinstance(lease_token, str) or not lease_token or not (
                    expected
                    and hmac.compare_digest(expected, _token_hash(lease_token))
                ):
                    raise MailboxConflictError("lease token is stale or invalid")
                return _public_tombstone(prior)
            item = self._require_claimed_token(reduced, item_id, lease_token)
            tombstone = {
                "schema": SCHEMA_VERSION,
                "event": "tombstone",
                "id": item["id"],
                "plan_path": item["plan_path"],
                "final_state": "acknowledged",
                "created_at": item["created_at"],
                "completed_at": completed_at,
                "lease_token_hash": item["lease_token_hash"],
            }
            remaining = [event for event in reduced.events if event.get("id") != item["id"]]
            reduced.events = remaining
            reduced.items.pop(item["id"], None)
            reduced.tombstones.append(tombstone)
            self._write_events(self._compacted_events(reduced))
        return _public_tombstone(tombstone)

    def fail_intent(
        self,
        item_id: str,
        lease_token: str,
        code: str,
        *,
        now: datetime | None = None,
    ) -> dict:
        if not isinstance(code, str) or code not in SAFE_FAILURE_CODES:
            raise MailboxValidationError("failure code is not allowed")
        failed_at = utc_stamp(now)
        with self._write_guard():
            reduced = self._read_reduced(now=now)
            self._ensure_clean(reduced)
            normalized_id = _valid_uuid(item_id)
            prior = reduced.items.get(normalized_id)
            if prior and prior["state"] in {"retryable", "failed"}:
                expected = prior.get("last_lease_token_hash", "")
                if (
                    prior.get("failure_code") == code
                    and isinstance(lease_token, str)
                    and lease_token
                    and expected
                    and hmac.compare_digest(expected, _token_hash(lease_token))
                ):
                    return _public_item(prior)
                raise MailboxConflictError("failure callback does not match prior result")
            item = self._require_claimed_token(reduced, item_id, lease_token)
            event = {
                "schema": SCHEMA_VERSION,
                "event": "fail",
                "id": item["id"],
                "code": code,
                "failed_at": failed_at,
            }
            self._append_and_write(reduced, event)
        state = "retryable" if code in RETRYABLE_FAILURE_CODES else "failed"
        return _public_item(
            {
                **item,
                "state": state,
                "failure_code": code,
                "updated_at": failed_at,
                "lease_token_hash": None,
                "lease_expires_at": None,
                "claimed_at": None,
                "consumer": None,
            }
        )

    def retry_intent(self, item_id: str, *, now: datetime | None = None) -> dict:
        retried_at = utc_stamp(now)
        with self._write_guard():
            reduced = self._read_reduced(now=now)
            self._ensure_clean(reduced)
            item = reduced.items.get(_valid_uuid(item_id))
            if not item or item["state"] != "retryable":
                raise MailboxConflictError("item is not retryable")
            event = {
                "schema": SCHEMA_VERSION,
                "event": "retry",
                "id": item["id"],
                "retried_at": retried_at,
            }
            self._append_and_write(reduced, event)
        return {
            **_public_item(item),
            "state": "queued",
            "failure_code": None,
            "updated_at": retried_at,
        }

    def dismiss_intent(self, item_id: str, *, now: datetime | None = None) -> dict:
        completed_at = utc_stamp(now)
        with self._write_guard():
            reduced = self._read_reduced(now=now)
            self._ensure_clean(reduced)
            normalized_id = _valid_uuid(item_id)
            item = reduced.items.get(normalized_id)
            if not item:
                raise MailboxConflictError("item is not active")
            if item["state"] == "claimed":
                raise MailboxConflictError("claimed intent cannot be dismissed")
            tombstone = {
                "schema": SCHEMA_VERSION,
                "event": "tombstone",
                "id": item["id"],
                "plan_path": item["plan_path"],
                "final_state": "dismissed",
                "created_at": item["created_at"],
                "completed_at": completed_at,
            }
            reduced.events = [event for event in reduced.events if event.get("id") != item["id"]]
            reduced.items.pop(item["id"], None)
            reduced.tombstones.append(tombstone)
            self._write_events(self._compacted_events(reduced))
        return dict(tombstone)
