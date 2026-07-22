"""Provider-neutral work-surface leases for concurrent Vidux runners.

The Authority PLAN remains the work queue.  This module only projects the
short-lived coordination facts that do not belong in PLAN markdown: who holds
one work surface, whether that lease is still alive, and the last bounded
checkpoint another runner needs after a handoff or expiry.

The journal accepts the original ``claim``/``release`` rows written by
``scripts/vidux-claims.py`` and adds schema-v2 heartbeat and checkpoint events.
All mutations are serialized through an alias-safe lock and atomic rewrite.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import socket
import threading
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from safe_files import atomic_write_text, open_regular_fd


SCHEMA_VERSION = 2
DEFAULT_TTL_HOURS = 2.0
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_ROWS = 50_000
MAX_LINE_BYTES = 64 * 1024
MAX_LABEL_CHARS = 160
MAX_SURFACE_CHARS = 1024
MAX_CHECKPOINT_BYTES = 8 * 1024
DEFAULT_HANDOFF_LIMIT = 16
ALLOWED_RELEASE_STATUSES = frozenset(
    {"done", "blocked", "handoff", "usage_exhausted", "cancelled"}
)
HANDOFF_RELEASE_STATUSES = frozenset(
    {"usage_exhausted", "handoff", "blocked", "in_progress"}
)
RESUME_REQUIRED_RELEASE_STATUSES = frozenset({"usage_exhausted", "handoff"})
LEGACY_CLAIMS_BUS_RELEASE_STATUSES = frozenset({"shipped", "aborted", "deferred"})

_LEGACY_CLAIMS_BUS_CLAIM_KEYS = frozenset(
    {"ts", "event", "agent_id", "plan_path", "row_id", "expected_ship_by"}
)
_LEGACY_CLAIMS_BUS_RELEASE_KEYS = frozenset(
    {"ts", "event", "agent_id", "plan_path", "row_id", "status"}
)

_CLAIM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,96}$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9_.:/@' +#-]+$")
_PROCESS_LOCK = threading.Lock()
UTC = timezone.utc


class ClaimsError(RuntimeError):
    """Base error for a refused coordination operation."""


class ClaimsValidationError(ClaimsError):
    """Input does not satisfy the claims contract."""


class ClaimsConflictError(ClaimsError):
    """The requested transition conflicts with current lease ownership."""

    def __init__(self, message: str, *, active: dict | None = None) -> None:
        super().__init__(message)
        self.active = active


class ClaimsJournalError(ClaimsError):
    """The on-disk coordination journal is malformed or too large."""


@dataclass
class ReducedClaims:
    events: list[dict]
    claims: dict[str, dict]


@dataclass(frozen=True)
class LegacyClaimsBusMarker:
    """A strictly recognized marker from the retired shared claims bus."""

    kind: str
    agent_id: str
    plan_path: str
    row_id: str
    at: datetime


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def utc_stamp(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_stamp(raw: object, field: str) -> datetime:
    if not isinstance(raw, str) or not raw:
        raise ClaimsJournalError(f"{field} must be a timestamp")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClaimsJournalError(f"{field} must be a timestamp") from exc
    if value.tzinfo is None:
        raise ClaimsJournalError(f"{field} must include a timezone")
    return value.astimezone(UTC)


def clean_label(raw: object, field: str, *, required: bool = True) -> str:
    if raw is None:
        text = ""
    elif isinstance(raw, str):
        text = raw.strip()
    else:
        raise ClaimsValidationError(f"{field} must be text")
    if not text:
        if required:
            raise ClaimsValidationError(f"{field} must be non-empty")
        return ""
    if len(text) > MAX_LABEL_CHARS or not _LABEL_RE.fullmatch(text):
        raise ClaimsValidationError(f"{field} contains unsupported characters")
    return text


def clean_surface(raw: object, field: str = "claim") -> str:
    if not isinstance(raw, str):
        raise ClaimsValidationError(f"{field} must be text")
    text = raw.strip()
    if not text or len(text) > MAX_SURFACE_CHARS:
        raise ClaimsValidationError(f"{field} must be non-empty and bounded")
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ClaimsValidationError(f"{field} contains control characters")
    return text


def clean_checkpoint_text(
    raw: object,
    field: str,
    *,
    required: bool,
) -> str:
    if raw is None:
        text = ""
    elif isinstance(raw, str):
        text = raw.strip()
    else:
        raise ClaimsValidationError(f"{field} must be text")
    if not text:
        if required:
            raise ClaimsValidationError(f"{field} must be non-empty")
        return ""
    if len(text.encode("utf-8")) > MAX_CHECKPOINT_BYTES:
        raise ClaimsValidationError(f"{field} exceeds {MAX_CHECKPOINT_BYTES} bytes")
    if any(ord(character) < 32 and character not in "\t\n" for character in text):
        raise ClaimsValidationError(f"{field} contains control characters")
    return text


def clean_claim_id(raw: object) -> str:
    if not isinstance(raw, str) or not _CLAIM_ID_RE.fullmatch(raw):
        raise ClaimsValidationError("claim_id is invalid")
    return raw


def clean_release_status(raw: object) -> str:
    status = clean_label(raw, "status", required=False)
    if status and status not in ALLOWED_RELEASE_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_RELEASE_STATUSES))
        raise ClaimsValidationError(
            f"release status must be one of: {allowed}"
        )
    return status


def positive_ttl(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ClaimsValidationError("ttl_hours must be positive")
    if value > 168:
        raise ClaimsValidationError("ttl_hours must not exceed 168 hours")
    return float(value)


def _legacy_timestamp(raw: object, field: str) -> datetime:
    try:
        return parse_stamp(raw, field)
    except ClaimsJournalError as exc:
        raise ClaimsValidationError(str(exc)) from exc


def legacy_claims_bus_marker(event: dict) -> LegacyClaimsBusMarker | None:
    """Recognize only the retired claims-bus dialect in a shared journal.

    The old shell bus predated Vidux coordination IDs and used a distinct,
    documented six-field schema.  It shares the same append-only file on some
    hosts, so terminal or expired rows must remain readable without treating
    arbitrary missing-ID records as harmless.  A currently live legacy claim
    is deliberately surfaced as a fail-closed blocker by ``read`` below.
    """

    if "schema" in event or "claim_id" in event:
        return None
    kind = event.get("event")
    expected_keys = (
        _LEGACY_CLAIMS_BUS_CLAIM_KEYS
        if kind == "claim"
        else _LEGACY_CLAIMS_BUS_RELEASE_KEYS
        if kind == "release"
        else None
    )
    if expected_keys is None or frozenset(event) != expected_keys:
        return None

    at = _legacy_timestamp(event.get("ts"), "ts")
    agent_id = clean_label(event.get("agent_id"), "legacy claims-bus agent_id")
    plan_path = clean_surface(event.get("plan_path"), "legacy claims-bus plan_path")
    row_id = clean_label(event.get("row_id"), "legacy claims-bus row_id")
    if kind == "claim":
        expected_ship_by = event.get("expected_ship_by")
        if not isinstance(expected_ship_by, str):
            raise ClaimsValidationError("legacy claims-bus expected_ship_by must be text")
        if expected_ship_by:
            _legacy_timestamp(expected_ship_by, "expected_ship_by")
    else:
        status = clean_label(event.get("status"), "legacy claims-bus status")
        if status not in LEGACY_CLAIMS_BUS_RELEASE_STATUSES:
            allowed = ", ".join(sorted(LEGACY_CLAIMS_BUS_RELEASE_STATUSES))
            raise ClaimsValidationError(
                f"legacy claims-bus status must be one of: {allowed}"
            )
    return LegacyClaimsBusMarker(kind, agent_id, plan_path, row_id, at)


def _legacy_relative_plan_name(plan_path: str) -> str | None:
    """Return a bare legacy plan filename, never a relative directory path.

    The retired shell bus sometimes emitted a terminal row as ``PLAN.md`` after
    claiming the same plan with an absolute path.  A bare filename carries too
    little identity to normalize globally, so it is used only as a conservative
    fallback alongside the same legacy owner and row when there is exactly one
    matching claim path in the journal.
    """

    path = Path(plan_path)
    if path.is_absolute() or len(path.parts) != 1:
        return None
    return path.name


def _public_checkpoint(state: dict) -> dict | None:
    if not state.get("resume"):
        return None
    checkpoint = {
        "at": state.get("checkpoint_at", ""),
        "summary": state.get("checkpoint_summary", ""),
        "resume": state.get("resume", ""),
    }
    if state.get("proof"):
        checkpoint["proof"] = state["proof"]
    return checkpoint


def public_claim(state: dict, *, now: datetime | None = None) -> dict:
    """Return the browser/CLI-safe projection; never expose host or pid."""
    moment = now or utc_now()
    released = bool(state.get("released_at"))
    expired = not released and parse_stamp(state["expires_at"], "expires_at") <= moment
    lifecycle = "released" if released else ("expired" if expired else "active")
    result = {
        "claim_id": state["claim_id"],
        "repo": state["repo"],
        "claim": state["claim"],
        "files_claimed": list(state.get("files_claimed", [])),
        "owner": state["owner"],
        "lane": state["lane"],
        "plan_path": state["plan_path"],
        "task_id": state["task_id"],
        "claimed_at": state["ts"],
        "last_heartbeat_at": state.get("last_heartbeat_at", state["ts"]),
        "expires_at": state["expires_at"],
        "state": lifecycle,
    }
    checkpoint = _public_checkpoint(state)
    if checkpoint:
        result["checkpoint"] = checkpoint
    for field in ("takeover_of", "taken_over_by"):
        if state.get(field):
            result[field] = state[field]
    if released:
        result["released_at"] = state["released_at"]
        if state.get("release_status"):
            result["release_status"] = state["release_status"]
            # Preserve the original CLI release-row field for old callers.
            result["status"] = state["release_status"]
    return result


class CoordinationClaims:
    """Strict reader and atomic mutator for the provider-neutral claims bus."""

    def __init__(
        self,
        store_path: str | Path,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> None:
        self.store_path = Path(store_path).expanduser()
        self.max_bytes = max_bytes
        self.max_rows = max_rows

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
            with open_regular_fd(self.store_path, os.O_RDONLY) as fd:
                size = os.fstat(fd).st_size
                if size > self.max_bytes:
                    raise ClaimsJournalError("claims journal exceeds byte limit")
                chunks: list[bytes] = []
                remaining = size
                while remaining:
                    chunk = os.read(fd, min(remaining, 64 * 1024))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
        except FileNotFoundError:
            return ""
        raw = b"".join(chunks)
        if len(raw) != size:
            raise ClaimsJournalError("claims journal changed during read")
        try:
            return raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ClaimsJournalError("claims journal is not valid UTF-8") from exc

    def read(self, *, now: datetime | None = None) -> ReducedClaims:
        moment = now or utc_now()
        text = self._read_text()
        events: list[dict] = []
        claims: dict[str, dict] = {}
        legacy_markers: list[LegacyClaimsBusMarker] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            if len(events) >= self.max_rows:
                raise ClaimsJournalError("claims journal exceeds row limit")
            if len(line.encode("utf-8")) > MAX_LINE_BYTES:
                raise ClaimsJournalError(f"claims journal line {line_number} is too large")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ClaimsJournalError(
                    f"invalid JSON in claims journal at line {line_number}"
                ) from exc
            if not isinstance(event, dict):
                raise ClaimsJournalError(
                    f"claims journal line {line_number} is not an object"
                )
            try:
                legacy_marker = legacy_claims_bus_marker(event)
                if legacy_marker is not None:
                    legacy_markers.append(legacy_marker)
                else:
                    self._apply_event(event, claims, line_number)
            except ClaimsValidationError as exc:
                raise ClaimsJournalError(
                    f"invalid claims journal row at line {line_number}: {exc}"
                ) from exc
            events.append(event)
        legacy_claim_paths: dict[tuple[str, str, str], set[str]] = {}
        for marker in legacy_markers:
            if marker.kind != "claim":
                continue
            key = (marker.agent_id, marker.row_id, Path(marker.plan_path).name)
            legacy_claim_paths.setdefault(key, set()).add(marker.plan_path)

        legacy_latest: dict[tuple[str, str, str], LegacyClaimsBusMarker] = {}
        for marker in legacy_markers:
            plan_path = marker.plan_path
            relative_name = _legacy_relative_plan_name(plan_path)
            if marker.kind == "release" and relative_name is not None:
                candidates = legacy_claim_paths.get(
                    (marker.agent_id, marker.row_id, relative_name), set()
                )
                if len(candidates) == 1:
                    plan_path = next(iter(candidates))
            key = (marker.agent_id, plan_path, marker.row_id)
            previous = legacy_latest.get(key)
            # The retired bus selected the latest timestamp and used append
            # order to break ties, so a later equal timestamp replaces the
            # earlier marker.
            if previous is None or marker.at >= previous.at:
                legacy_latest[key] = marker
        for marker in legacy_latest.values():
            if (
                marker.kind == "claim"
                and marker.at + timedelta(hours=DEFAULT_TTL_HOURS) > moment
            ):
                raise ClaimsJournalError(
                    "active legacy claims-bus claim cannot be safely projected "
                    f"for {marker.plan_path} row {marker.row_id}"
                )
        return ReducedClaims(events=events, claims=claims)

    def _base_claim(self, event: dict, line_number: int) -> dict:
        claim_id = clean_claim_id(event.get("claim_id"))
        claimed_at = parse_stamp(event.get("ts"), "ts")
        expires_at = parse_stamp(event.get("expires_at"), "expires_at")
        if expires_at <= claimed_at:
            raise ClaimsValidationError("expires_at must follow ts")
        files = event.get("files_claimed", [event.get("claim")])
        if not isinstance(files, list) or not files:
            raise ClaimsValidationError("files_claimed must be a non-empty list")
        clean_files = [clean_surface(value, "files_claimed") for value in files]
        state = {
            "claim_id": claim_id,
            "event": "claim",
            "ts": utc_stamp(claimed_at),
            "repo": clean_label(event.get("repo"), "repo"),
            "claim": clean_surface(event.get("claim")),
            "files_claimed": clean_files,
            "owner": clean_label(event.get("owner"), "owner"),
            "lane": clean_label(event.get("lane"), "lane"),
            "plan_path": clean_surface(event.get("plan_path"), "plan_path"),
            "task_id": clean_label(event.get("task_id"), "task_id"),
            "ttl_hours": positive_ttl(event.get("ttl_hours", DEFAULT_TTL_HOURS)),
            "expires_at": utc_stamp(expires_at),
            "last_heartbeat_at": utc_stamp(claimed_at),
            "host": str(event.get("host", "")),
            "pid": event.get("pid"),
            "_sequence": line_number,
        }
        takeover_of = event.get("takeover_of")
        if takeover_of:
            state["takeover_of"] = clean_claim_id(takeover_of)
        return state

    def _apply_event(self, event: dict, claims: dict[str, dict], line_number: int) -> None:
        schema = event.get("schema")
        if schema not in (None, SCHEMA_VERSION):
            raise ClaimsValidationError("unsupported schema version")
        kind = event.get("event")
        if kind == "claim":
            state = self._base_claim(event, line_number)
            claim_id = state["claim_id"]
            if claim_id in claims:
                raise ClaimsValidationError("duplicate claim_id")
            prior_id = state.get("takeover_of")
            if prior_id:
                prior = claims.get(prior_id)
                if not prior:
                    raise ClaimsValidationError("takeover references unknown claim")
                claimed_at = parse_stamp(state["ts"], "ts")
                prior_active = not prior.get("released_at") and (
                    parse_stamp(prior["expires_at"], "expires_at") > claimed_at
                )
                if prior_active or prior.get("taken_over_by"):
                    raise ClaimsValidationError("takeover references an unavailable claim")
                prior["taken_over_by"] = claim_id
            claims[claim_id] = state
            return

        claim_id = clean_claim_id(event.get("claim_id"))
        state = claims.get(claim_id)
        if not state:
            raise ClaimsValidationError(f"{kind or 'event'} references unknown claim")
        owner = clean_label(event.get("owner"), "owner")
        legacy_release = schema is None and kind == "release"
        if owner != state["owner"] and not legacy_release:
            raise ClaimsValidationError("event owner does not hold claim")

        at_field = {
            "heartbeat": "ts",
            "checkpoint": "ts",
            "release": "ts",
        }.get(str(kind))
        if not at_field:
            raise ClaimsValidationError("unknown claims event")
        at = parse_stamp(event.get(at_field), at_field)
        last_at = max(
            parse_stamp(state["last_heartbeat_at"], "last_heartbeat_at"),
            parse_stamp(state.get("checkpoint_at", state["ts"]), "checkpoint_at"),
        )
        if at < last_at:
            raise ClaimsValidationError("event precedes prior claim activity")

        if kind in {"heartbeat", "checkpoint"}:
            if state.get("released_at") or state.get("taken_over_by"):
                raise ClaimsValidationError("inactive claim cannot be renewed")
            if at > parse_stamp(state["expires_at"], "expires_at"):
                raise ClaimsValidationError("expired claim cannot be renewed")
            expires_at = parse_stamp(event.get("expires_at"), "expires_at")
            if expires_at <= at:
                raise ClaimsValidationError("renewed expiry must follow activity")
            state["last_heartbeat_at"] = utc_stamp(at)
            state["expires_at"] = utc_stamp(expires_at)
            state["ttl_hours"] = positive_ttl(
                event.get("ttl_hours", state["ttl_hours"])
            )

        if kind == "heartbeat":
            return

        if kind == "checkpoint":
            state["checkpoint_at"] = utc_stamp(at)
            state["checkpoint_summary"] = clean_checkpoint_text(
                event.get("summary"), "summary", required=True
            )
            state["resume"] = clean_checkpoint_text(
                event.get("resume"), "resume", required=True
            )
            state["proof"] = clean_checkpoint_text(
                event.get("proof", ""), "proof", required=False
            )
            return

        if kind == "release":
            if state.get("released_at"):
                raise ClaimsValidationError("claim is already released")
            release_status = (
                clean_release_status(event.get("status", ""))
                if schema == SCHEMA_VERSION
                else clean_label(event.get("status", ""), "status", required=False)
            )
            state["released_at"] = utc_stamp(at)
            state["release_status"] = release_status
            if event.get("summary") or event.get("resume") or event.get("proof"):
                state["checkpoint_at"] = utc_stamp(at)
                state["checkpoint_summary"] = clean_checkpoint_text(
                    event.get("summary", state.get("checkpoint_summary", "")),
                    "summary",
                    required=False,
                )
                state["resume"] = clean_checkpoint_text(
                    event.get("resume", state.get("resume", "")),
                    "resume",
                    required=False,
                )
                state["proof"] = clean_checkpoint_text(
                    event.get("proof", state.get("proof", "")),
                    "proof",
                    required=False,
                )
            return

    def _serialize(self, events: list[dict]) -> str:
        if len(events) > self.max_rows:
            raise ClaimsJournalError("claims journal exceeds row limit")
        text = "".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
            for event in events
        )
        if len(text.encode("utf-8")) > self.max_bytes:
            raise ClaimsJournalError("claims journal exceeds byte limit")
        return text

    def _write(self, events: list[dict]) -> None:
        atomic_write_text(self.store_path, self._serialize(events), mode=0o600)

    @staticmethod
    def _is_active(state: dict, moment: datetime) -> bool:
        return (
            not state.get("released_at")
            and not state.get("taken_over_by")
            and parse_stamp(state["expires_at"], "expires_at") > moment
        )

    @staticmethod
    def _same_surface(state: dict, repo: str, claim: str) -> bool:
        return state["repo"] == repo and state["claim"] == claim

    def _latest_takeover_candidate(
        self,
        reduced: ReducedClaims,
        *,
        repo: str,
        claim: str,
        now: datetime,
    ) -> dict | None:
        candidates = [
            state
            for state in reduced.claims.values()
            if self._same_surface(state, repo, claim)
            and not state.get("taken_over_by")
            and not self._is_active(state, now)
            and (
                not state.get("released_at")
                or state.get("release_status") in HANDOFF_RELEASE_STATUSES
            )
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda state: state["_sequence"])

    def claim(
        self,
        *,
        claim_id: str,
        repo: str,
        claim: str,
        owner: str,
        lane: str,
        plan_path: str,
        task_id: str,
        ttl_hours: float = DEFAULT_TTL_HOURS,
        now: datetime | None = None,
        host: str | None = None,
        pid: int | None = None,
    ) -> dict:
        moment = now or utc_now()
        clean_repo = clean_label(repo, "repo")
        clean_claim = clean_surface(claim)
        clean_owner = clean_label(owner, "owner")
        clean_lane = clean_label(lane, "lane")
        clean_plan = clean_surface(plan_path, "plan_path")
        clean_task = clean_label(task_id, "task_id")
        ttl = positive_ttl(ttl_hours)
        clean_id = clean_claim_id(claim_id)

        with self._write_guard():
            reduced = self.read(now=moment)
            active = [
                state
                for state in reduced.claims.values()
                if self._same_surface(state, clean_repo, clean_claim)
                and self._is_active(state, moment)
            ]
            if active:
                current = max(active, key=lambda state: state["_sequence"])
                if current["owner"] == clean_owner:
                    return {
                        "ok": True,
                        "status": "already_claimed",
                        "claim": public_claim(current, now=moment),
                    }
                raise ClaimsConflictError(
                    "work surface is already claimed",
                    active=public_claim(current, now=moment),
                )

            prior = self._latest_takeover_candidate(
                reduced, repo=clean_repo, claim=clean_claim, now=moment
            )
            event = {
                "schema": SCHEMA_VERSION,
                "event": "claim",
                "claim_id": clean_id,
                "ts": utc_stamp(moment),
                "repo": clean_repo,
                "claim": clean_claim,
                "files_claimed": [clean_claim],
                "owner": clean_owner,
                "lane": clean_lane,
                "plan_path": clean_plan,
                "task_id": clean_task,
                "ttl_hours": ttl,
                "expires_at": utc_stamp(moment + timedelta(hours=ttl)),
                "host": host or socket.gethostname(),
                "pid": os.getpid() if pid is None else pid,
            }
            if prior:
                event["takeover_of"] = prior["claim_id"]
            events = [*reduced.events, event]
            self._write(events)
            projected = self.read(now=moment).claims[clean_id]

        result = {
            "ok": True,
            "status": "claimed",
            "claim": public_claim(projected, now=moment),
        }
        if prior:
            result["takeover"] = public_claim(prior, now=moment)
        return result

    def _owned_claim(
        self,
        reduced: ReducedClaims,
        *,
        claim_id: str,
        owner: str,
    ) -> dict:
        clean_id = clean_claim_id(claim_id)
        clean_owner = clean_label(owner, "owner")
        state = reduced.claims.get(clean_id)
        if not state:
            raise ClaimsConflictError("claim is not active")
        if state["owner"] != clean_owner:
            raise ClaimsConflictError(
                "claim is owned by another runner",
                active=public_claim(state),
            )
        return state

    def heartbeat(
        self,
        *,
        claim_id: str,
        owner: str,
        ttl_hours: float | None = None,
        now: datetime | None = None,
    ) -> dict:
        moment = now or utc_now()
        with self._write_guard():
            reduced = self.read(now=moment)
            state = self._owned_claim(reduced, claim_id=claim_id, owner=owner)
            if not self._is_active(state, moment):
                raise ClaimsConflictError(
                    "claim lease has expired or ended", active=public_claim(state, now=moment)
                )
            ttl = positive_ttl(ttl_hours if ttl_hours is not None else state["ttl_hours"])
            event = {
                "schema": SCHEMA_VERSION,
                "event": "heartbeat",
                "claim_id": state["claim_id"],
                "owner": state["owner"],
                "ts": utc_stamp(moment),
                "ttl_hours": ttl,
                "expires_at": utc_stamp(moment + timedelta(hours=ttl)),
            }
            self._write([*reduced.events, event])
            projected = self.read(now=moment).claims[state["claim_id"]]
        return {"ok": True, "status": "renewed", "claim": public_claim(projected, now=moment)}

    def checkpoint(
        self,
        *,
        claim_id: str,
        owner: str,
        summary: str,
        resume: str,
        proof: str = "",
        ttl_hours: float | None = None,
        now: datetime | None = None,
    ) -> dict:
        moment = now or utc_now()
        clean_summary = clean_checkpoint_text(summary, "summary", required=True)
        clean_resume = clean_checkpoint_text(resume, "resume", required=True)
        clean_proof = clean_checkpoint_text(proof, "proof", required=False)
        with self._write_guard():
            reduced = self.read(now=moment)
            state = self._owned_claim(reduced, claim_id=claim_id, owner=owner)
            if not self._is_active(state, moment):
                raise ClaimsConflictError(
                    "claim lease has expired or ended", active=public_claim(state, now=moment)
                )
            ttl = positive_ttl(ttl_hours if ttl_hours is not None else state["ttl_hours"])
            event = {
                "schema": SCHEMA_VERSION,
                "event": "checkpoint",
                "claim_id": state["claim_id"],
                "owner": state["owner"],
                "ts": utc_stamp(moment),
                "ttl_hours": ttl,
                "expires_at": utc_stamp(moment + timedelta(hours=ttl)),
                "summary": clean_summary,
                "resume": clean_resume,
                "proof": clean_proof,
            }
            self._write([*reduced.events, event])
            projected = self.read(now=moment).claims[state["claim_id"]]
        return {
            "ok": True,
            "status": "checkpointed",
            "claim": public_claim(projected, now=moment),
        }

    def release(
        self,
        *,
        owner: str,
        claim_id: str | None = None,
        repo: str | None = None,
        claim: str | None = None,
        status: str = "",
        summary: str = "",
        resume: str = "",
        proof: str = "",
        now: datetime | None = None,
    ) -> dict:
        moment = now or utc_now()
        clean_owner = clean_label(owner, "owner")
        clean_status = clean_release_status(status)
        clean_summary = clean_checkpoint_text(summary, "summary", required=False)
        clean_resume = clean_checkpoint_text(resume, "resume", required=False)
        clean_proof = clean_checkpoint_text(proof, "proof", required=False)

        with self._write_guard():
            reduced = self.read(now=moment)
            state: dict | None = None
            if claim_id:
                candidate = reduced.claims.get(clean_claim_id(claim_id))
                if candidate and not candidate.get("released_at"):
                    state = candidate
            else:
                if not repo or not claim:
                    raise ClaimsValidationError(
                        "release requires claim_id or both repo and claim"
                    )
                clean_repo = clean_label(repo, "repo")
                clean_claim = clean_surface(claim)
                candidates = [
                    row
                    for row in reduced.claims.values()
                    if self._same_surface(row, clean_repo, clean_claim)
                    and not row.get("released_at")
                    and not row.get("taken_over_by")
                ]
                if candidates:
                    state = max(candidates, key=lambda row: row["_sequence"])
            if state is None:
                return {"ok": True, "status": "no_active_claim"}
            if state["owner"] != clean_owner:
                raise ClaimsConflictError(
                    "claim is owned by another runner",
                    active=public_claim(state, now=moment),
                )
            if state.get("taken_over_by"):
                raise ClaimsConflictError(
                    "claim has already been taken over", active=public_claim(state, now=moment)
                )
            effective_resume = clean_resume or state.get("resume", "")
            if clean_status in RESUME_REQUIRED_RELEASE_STATUSES and not effective_resume:
                raise ClaimsValidationError(
                    f"{clean_status} release requires a checkpoint resume pointer"
                )
            event = {
                "schema": SCHEMA_VERSION,
                "event": "release",
                "claim_id": state["claim_id"],
                "owner": clean_owner,
                "ts": utc_stamp(moment),
                "status": clean_status,
            }
            if clean_summary:
                event["summary"] = clean_summary
            if clean_resume:
                event["resume"] = clean_resume
            if clean_proof:
                event["proof"] = clean_proof
            self._write([*reduced.events, event])
            projected = self.read(now=moment).claims[state["claim_id"]]
        return {
            "ok": True,
            "status": "released",
            "release": public_claim(projected, now=moment),
        }

    def snapshot(
        self,
        *,
        repo: str | None = None,
        claim: str | None = None,
        plan_path: str | None = None,
        handoff_limit: int = DEFAULT_HANDOFF_LIMIT,
        now: datetime | None = None,
    ) -> dict:
        moment = now or utc_now()
        if handoff_limit < 0 or handoff_limit > 256:
            raise ClaimsValidationError("handoff_limit must be between 0 and 256")
        clean_repo = clean_label(repo, "repo") if repo else ""
        clean_claim = clean_surface(claim) if claim else ""
        clean_plan = clean_surface(plan_path, "plan_path") if plan_path else ""
        reduced = self.read(now=moment)
        states = list(reduced.claims.values())
        if clean_repo:
            states = [state for state in states if state["repo"] == clean_repo]
        if clean_claim:
            states = [state for state in states if state["claim"] == clean_claim]
        if clean_plan:
            states = [state for state in states if state["plan_path"] == clean_plan]
        active = [state for state in states if self._is_active(state, moment)]
        handoffs = [
            state
            for state in states
            if not state.get("taken_over_by")
            and not self._is_active(state, moment)
            and (
                (not state.get("released_at") and bool(state.get("resume")))
                or state.get("release_status") in HANDOFF_RELEASE_STATUSES
            )
        ]
        active.sort(key=lambda state: state["_sequence"])
        handoffs.sort(key=lambda state: state["_sequence"], reverse=True)
        return {
            "ok": True,
            "generated_at": utc_stamp(moment),
            "claims": [public_claim(state, now=moment) for state in active],
            "handoffs": [
                public_claim(state, now=moment)
                for state in handoffs[:handoff_limit]
            ],
        }
