#!/usr/bin/env python3
"""
vidux browser — local web UI for viewing PLAN.md across the fleet.

Read-mostly viewer. Local-only write endpoints append artifacts/INBOX notes.
Stdlib only. See projects/vidux-browser/PLAN.md.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import copy
import fcntl
import ipaddress
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter, deque
from contextlib import ExitStack, contextmanager
from datetime import date
from glob import glob
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# Receipt corpus lab handlers (math-fortress T9). Sibling package — server.py
# is callable both as __main__ (sys.path[0] = browser/) and via importlib spec
# from tests (sys.path[0] = caller CWD). Insert browser/ explicitly so the
# import resolves regardless of caller.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_files import UnsafeFileAliasError, atomic_write_text, open_regular_fd, read_text
from coordination_claims import ClaimsError, CoordinationClaims
from steering_mailbox import (
    ACTIVE_LIMIT_PER_PLAN as STEERING_CAPACITY,
    DEFAULT_STORE as DEFAULT_STEERING_FILE,
    INTENT_MAX_BYTES as STEERING_INTENT_MAX_BYTES,
    JournalCorruptError as SteeringJournalCorruptError,
    MailboxConflictError as SteeringMailboxConflictError,
    MailboxError as SteeringMailboxError,
    MailboxValidationError as SteeringMailboxValidationError,
    SteeringMailbox,
    is_authority_plan_name,
)

DEV_ROOT = Path(os.environ.get("VIDUX_DEV_ROOT", Path.home() / "Development")).expanduser().resolve()
HOST = os.environ.get("VIDUX_BROWSER_HOST", "127.0.0.1")
PORT = int(os.environ.get("VIDUX_BROWSER_PORT", "7191"))

BROWSER_DIR = Path(__file__).resolve().parent
VIDUX_ROOT = Path(os.environ.get("VIDUX_ROOT", BROWSER_DIR.parent)).expanduser().resolve()
SERVER_FILE = Path(__file__).resolve()
SERVER_MTIME_NS = SERVER_FILE.stat().st_mtime_ns
STEERING_MODULE_MTIME_NS = (BROWSER_DIR / "steering_mailbox.py").stat().st_mtime_ns
COORDINATION_MODULE_MTIME_NS = (BROWSER_DIR / "coordination_claims.py").stat().st_mtime_ns
STATIC_DIR = BROWSER_DIR / "static"
ARTIFACTS_DIR = Path(
    os.environ.get("VIDUX_BROWSER_ARTIFACTS_DIR", BROWSER_DIR / "artifacts")
).expanduser().resolve()
CLAUDE_PROJECTS_DIR = Path(
    os.environ.get("VIDUX_CLAUDE_PROJECTS_DIR", Path.home() / ".claude" / "projects")
).expanduser()
SESSION_TURN_LIMIT = 5
SESSION_EXCERPT_LIMIT = 360
SESSION_TAIL_BYTES = 2 * 1024 * 1024
try:
    DASHBOARD_ITEM_LIMIT = max(1, int(os.environ.get("VIDUX_DASHBOARD_ITEM_LIMIT", "200")))
except ValueError:
    DASHBOARD_ITEM_LIMIT = 200
LEDGER_FILE = Path(os.environ.get("VIDUX_LEDGER_FILE", Path.home() / ".agent-ledger" / "activity.jsonl")).expanduser()
try:
    LEDGER_ITEM_LIMIT = max(1, int(os.environ.get("VIDUX_LEDGER_ITEM_LIMIT", "20")))
except ValueError:
    LEDGER_ITEM_LIMIT = 20
try:
    LEDGER_SCAN_LIMIT = max(1, int(os.environ.get("VIDUX_LEDGER_SCAN_LIMIT", "5000")))
except ValueError:
    LEDGER_SCAN_LIMIT = 5000

# Plan-layout conventions. The two-segment vidux/projects/ai patterns catch
# parent plans (e.g., `vidux/design-overhaul/PLAN.md`); the `**` recursive forms
# pick up sub-plans nested under those parents (e.g.,
# `vidux/design-overhaul/<child>/PLAN.md`). Recursive globs land MORE files but
# `discover_plans()` dedupes by resolved path so we never count twice. Override
# via env `VIDUX_PLAN_GLOBS` (colon-separated) for non-standard fleets.
PLAN_GLOBS = (
    os.environ.get("VIDUX_PLAN_GLOBS", "").split(":")
    if os.environ.get("VIDUX_PLAN_GLOBS")
    else [
        "*/ai/plans/*/PLAN.md",
        "*/vidux/*/PLAN.md",
        "*/vidux/**/PLAN.md",
        "*/projects/*/PLAN.md",
        "*/projects/**/PLAN.md",
        "*/.cursor/plans/*.plan.md",
        "*/.cursor/plans/**/*.plan.md",
        "*/PLAN.md",
        # A PLAN.md sitting directly at the scan root (`--root <dir>` where
        # <dir> IS the project) — every other pattern requires at least one
        # directory level, so without this a root-level plan is invisible.
        "PLAN.md",
    ]
)

# Aliases for historical checkout names that can still contain copied vidux
# plans (e.g., a repo was renamed but old clones still exist). When the same
# plan resolves under both names, prefer the canonical checkout. Override via
# env `VIDUX_REPO_ALIASES` as JSON (e.g. '{"oldname": "newname"}').
def _parse_repo_aliases():
    raw = os.environ.get("VIDUX_REPO_ALIASES", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return {str(k): str(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}
LEGACY_REPO_ALIASES = _parse_repo_aliases()

PLANS_CACHE_TTL_SECONDS = float(os.environ.get("VIDUX_PLANS_CACHE_TTL_SECONDS", "20"))
_PLANS_CACHE_LOCK = threading.Lock()
_PLANS_CACHE: dict[str, object] = {
    "key": None,
    "expires_at": 0.0,
    "plans": None,
}


def clear_plans_cache() -> None:
    with _PLANS_CACHE_LOCK:
        _PLANS_CACHE["key"] = None
        _PLANS_CACHE["expires_at"] = 0.0
        _PLANS_CACHE["plans"] = None


def discover_plans_cached() -> list[dict]:
    """Cache the fleet index briefly so auto-refresh does not rescan every hit."""
    if PLANS_CACHE_TTL_SECONDS <= 0:
        return discover_plans()

    key = (str(DEV_ROOT), tuple(PLAN_GLOBS), tuple(sorted(LEGACY_REPO_ALIASES.items())))
    now = time.monotonic()
    with _PLANS_CACHE_LOCK:
        plans = _PLANS_CACHE["plans"]
        if plans is not None and _PLANS_CACHE["key"] == key and now < _PLANS_CACHE["expires_at"]:
            return plans  # type: ignore[return-value]

        plans = discover_plans()
        _PLANS_CACHE["key"] = key
        _PLANS_CACHE["expires_at"] = time.monotonic() + PLANS_CACHE_TTL_SECONDS
        _PLANS_CACHE["plans"] = plans
        return plans

# Files to expose alongside PLAN.md when present.
# PROGRESS.md and ASK-OWNER.md are optional operator extensions; the browser
# surfaces them when present but does not require them — a clean repo without
# those files still works.
ASK_OWNER_FILENAMES = ("ASK-OWNER.md",)
SIBLING_FILES = ["PROGRESS.md", "INBOX.md", "ASK-OWNER.md", "DOCTRINE.md", "README.md"]

# safe_resolve() whitelist. Any other filename under DEV_ROOT is rejected —
# without this gate, a malicious page could fetch /api/file?path=…/.env or
# …/.ssh/config from a browser tab on the operator machine.
ALLOWED_PLAN_FILES = frozenset({"PLAN.md", *SIBLING_FILES})


def resolve_ask_owner_path(parent_dir: Path) -> Path | None:
    """Return the operator-question queue path (`ASK-OWNER.md`) if present."""
    for name in ASK_OWNER_FILENAMES:
        path = parent_dir / name
        if path.is_file():
            return path
    return None


def is_repo_native_authority_path(path: Path) -> bool:
    """Admit named authorities only from the repo-owned .cursor/plans tree."""
    if path.name == "PLAN.md" or not is_authority_plan_name(path.name):
        return False
    try:
        relative = path.relative_to(DEV_ROOT)
    except ValueError:
        return False
    return len(relative.parts) >= 4 and relative.parts[1:3] == (".cursor", "plans")

SENSITIVE_REDACTION = "[REDACTED:secret]"
SENSITIVE_PROVIDER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|"
    r"lin_api_[A-Za-z0-9]{20,}|"
    r"AKIA[A-Z0-9]{16}|"
    r"AIza[A-Za-z0-9_-]{30,}|"
    r"sk_live_[A-Za-z0-9]{16,}"
    r")(?![A-Za-z0-9])"
)
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?im)(?:[\"'`])?(?:api[_-]?key|access[_-]?(?:key|token)|auth[_-]?token|"
    r"client[_-]?secret|private[_-]?key|secret|credential|token)"
    r"(?:[\"'`])?\s*(?:=|:)\s*"
    r"(?P<value>\"[^\"\r\n]{12,}\"|'[^'\r\n]{12,}'|`[^`\r\n]{12,}`|[^\s,;]{12,})"
)
SENSITIVE_PASSWORD_ASSIGNMENT_RE = re.compile(
    r"(?im)(?:[\"'`])?(?:password|passwd)(?:[\"'`])?\s*(?:=|:)\s*"
    r"(?P<value>\"[^\"\r\n]{4,}\"|'[^'\r\n]{4,}'|`[^`\r\n]{4,}`|[^\s,;]{4,})"
)
SENSITIVE_BEARER_RE = re.compile(
    r"(?im)\bauthorization\s*:\s*bearer\s+(?P<value>[^\s,;]{12,})"
)
SENSITIVE_JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
    r"[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)
SENSITIVE_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    re.S,
)
SENSITIVE_ATOM_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<value>[A-Za-z0-9_#+.=-]{40,})(?![A-Za-z0-9])"
)
SENSITIVE_PLACEHOLDER_MARKERS = (
    "redacted",
    "placeholder",
    "example",
    "sample",
    "dummy",
    "fake",
    "xxxxx",
    "changeme",
    "your_",
    "your-",
    "not-a-secret",
    "test-secret",
    "test_secret",
)

ARTIFACT_CONTENT_SECURITY_POLICY = "; ".join((
    "default-src 'none'",
    "base-uri 'none'",
    "connect-src 'none'",
    "font-src data:",
    "form-action 'none'",
    "frame-ancestors 'self'",
    "frame-src 'none'",
    "img-src data: blob:",
    "manifest-src 'none'",
    "media-src data: blob:",
    "object-src 'none'",
    "script-src 'none'",
    "style-src 'unsafe-inline'",
    "worker-src 'none'",
))
ARTIFACT_SECURITY_HEADERS = {
    "Content-Disposition": 'attachment; filename="vidux-artifact.html"',
    "Content-Security-Policy": ARTIFACT_CONTENT_SECURITY_POLICY,
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
}


def _unquoted_secret_value(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'`":
        return text[1:-1]
    return text


def _is_placeholder_secret(value: str) -> bool:
    text = _unquoted_secret_value(value).strip().lower()
    if not text or text.startswith(("${", "{{", "<")):
        return True
    if text in {"none", "null", "unset", "todo", "n/a"}:
        return True
    return any(marker in text for marker in SENSITIVE_PLACEHOLDER_MARKERS)


def _looks_like_high_entropy_secret(value: str) -> bool:
    text = _unquoted_secret_value(value).strip()
    if len(text) < 40 or _is_placeholder_secret(text):
        return False
    if re.fullmatch(r"[0-9a-fA-F]+", text):
        return False
    if not (
        re.search(r"[A-Z]", text)
        and re.search(r"[a-z]", text)
        and re.search(r"\d", text)
        and re.search(r"[_#/+=]", text)
    ):
        return False
    counts = Counter(text)
    entropy = -sum((count / len(text)) * math.log2(count / len(text)) for count in counts.values())
    return len(counts) >= 12 and entropy >= 3.3


def sensitive_text_spans(text: str) -> list[tuple[int, int]]:
    """Return merged high-confidence credential spans without their values."""
    spans: list[tuple[int, int]] = []
    for pattern in (SENSITIVE_PRIVATE_KEY_RE, SENSITIVE_PROVIDER_RE, SENSITIVE_JWT_RE):
        spans.extend((match.start(), match.end()) for match in pattern.finditer(text))
    for pattern in (
        SENSITIVE_ASSIGNMENT_RE,
        SENSITIVE_PASSWORD_ASSIGNMENT_RE,
        SENSITIVE_BEARER_RE,
    ):
        for match in pattern.finditer(text):
            value = match.group("value")
            if not _is_placeholder_secret(value):
                spans.append(match.span("value"))
    for match in SENSITIVE_ATOM_RE.finditer(text):
        if _looks_like_high_entropy_secret(match.group("value")):
            spans.append(match.span("value"))

    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def redact_sensitive_text(text: str) -> tuple[str, int]:
    spans = sensitive_text_spans(text)
    if not spans:
        return text, 0
    redacted = text
    for start, end in reversed(spans):
        redacted = redacted[:start] + SENSITIVE_REDACTION + redacted[end:]
    return redacted, len(spans)


def has_sensitive_text(text: str) -> bool:
    return bool(sensitive_text_spans(text))


def redact_sensitive_value(value):
    if isinstance(value, str):
        return redact_sensitive_text(value)[0]
    if isinstance(value, (list, tuple)):
        return [redact_sensitive_value(item) for item in value]
    if isinstance(value, dict):
        return {
            redact_sensitive_text(key)[0] if isinstance(key, str) else key:
            redact_sensitive_value(item)
            for key, item in value.items()
        }
    return value

HOT_DAYS = 7
STALE_DAYS = 30

ARTIFACT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ARTIFACT_MAX_BYTES = 1024 * 1024  # 1 MB cap on POSTed HTML
ARTIFACT_TITLE_RE = re.compile(
    r"<title>([^<]+)</title>|<h1[^>]*>([^<]+)</h1>", re.I
)
PLAN_NOTE_MAX_BYTES = 16 * 1024
PLAN_NOTE_SOURCE_RE = re.compile(r"[^A-Za-z0-9_.:/@ -]+")
COMMENTS_FILE = Path(
    os.environ.get("VIDUX_BROWSER_COMMENTS_FILE", Path.home() / ".vidux-browser" / "comments.jsonl")
).expanduser()
STEERING_FILE = Path(
    os.environ.get("VIDUX_BROWSER_STEERING_FILE", DEFAULT_STEERING_FILE)
).expanduser()
CLAIMS_FILE = Path(
    os.environ.get("VIDUX_CLAIMS_FILE", Path.home() / ".agent-ledger" / "claims.jsonl")
).expanduser()
# JSON may encode every decoded intent byte as a six-byte ``\u00xx`` escape.
# Keep the HTTP envelope bounded while still admitting every valid 8 KiB
# intent accepted by the provider-neutral journal.
STEERING_HTTP_MAX_BYTES = STEERING_INTENT_MAX_BYTES * 6 + 4096
_COMMENTS_WRITE_LOCK = threading.Lock()
_PLAN_NOTE_WRITE_LOCK = threading.Lock()
COMMENT_BODY_MAX_BYTES = 8 * 1024
COMMENT_AUTHOR_MAX_CHARS = 80
COMMENT_AUTHOR_RE = re.compile(r"[^A-Za-z0-9_.:/@' -]+")
COMMENT_ANCHOR_FIELD_LIMITS = {
    "selector": 160,
    "label": 180,
    "excerpt": 360,
    "tag": 32,
    "kind": 32,
}
COMMENT_ANCHOR_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})
JSON_CONTENT_TYPE = "application/json"


@contextmanager
def _comments_write_guard():
    """Serialize comment rewrites across threads and Vidux server processes."""
    lock_path = COMMENTS_FILE.with_suffix(COMMENTS_FILE.suffix + ".lock")
    with _COMMENTS_WRITE_LOCK, ExitStack() as stack:
        # open_regular_fd(create_parent=True) recreates the lock's
        # parent dir, but under pathological concurrent load (e.g. many parallel
        # test suites sharing a machine) an unrelated process can delete that
        # dir again in the window between mkdir and open, surfacing as a
        # transient FileNotFoundError that aborts an otherwise-valid comment
        # write. A small bounded retry rides out a one-shot transient without
        # touching the security invariant: open_regular_fd still rejects unsafe
        # (symlink/alias/non-regular) targets immediately, and only the
        # parent-vanished ENOENT is retried. (The race needs an external
        # deleter, so it is not deterministically unit-testable.)
        lock_fd = None
        last_exc: FileNotFoundError | None = None
        for _ in range(3):
            try:
                lock_fd = stack.enter_context(
                    open_regular_fd(lock_path, os.O_RDWR | os.O_CREAT, create_parent=True)
                )
                break
            except FileNotFoundError as exc:
                last_exc = exc
        if lock_fd is None:
            raise last_exc  # type: ignore[misc]
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
VIDUX_TRUTH_CACHE_TTL_SECONDS = float(os.environ.get("VIDUX_TRUTH_CACHE_TTL_SECONDS", "45"))
_VIDUX_TRUTH_CACHE_LOCK = threading.Lock()
_VIDUX_TRUTH_CACHE: dict[str, object] = {
    "expires_at": 0.0,
    "payload": None,
    "generated_monotonic": 0.0,
    "refreshing": False,
}


def clear_vidux_truth_cache() -> None:
    with _VIDUX_TRUTH_CACHE_LOCK:
        _VIDUX_TRUTH_CACHE["expires_at"] = 0.0
        _VIDUX_TRUTH_CACHE["payload"] = None
        _VIDUX_TRUTH_CACHE["generated_monotonic"] = 0.0
        _VIDUX_TRUTH_CACHE["refreshing"] = False


def run_truth_command(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(VIDUX_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _truth_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _truth_command_payload(args: list[str], *, timeout: float) -> dict:
    started = time.monotonic()
    try:
        result = run_truth_command(args, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return {
            "command": args,
            "command_ok": False,
            "returncode": None,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "error": f"timed out after {exc.timeout}s",
            "data": {},
        }
    except OSError as exc:
        return {
            "command": args,
            "command_ok": False,
            "returncode": None,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "error": str(exc),
            "data": {},
        }

    raw = (result.stdout or "").strip()
    try:
        data = json.loads(raw) if raw else {}
        parsed = isinstance(data, dict)
    except json.JSONDecodeError as exc:
        data = {}
        parsed = False
        error = f"invalid json: {exc}"
    else:
        error = "" if parsed else "json root was not an object"

    return {
        "command": args,
        "command_ok": result.returncode == 0 and parsed,
        "returncode": result.returncode,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "error": error or (result.stderr or "").strip(),
        "data": data if parsed else {},
    }



def _collect_vidux_truth_payload() -> dict:
    """Collect read-only local truth for the browser chrome.

    The browser intentionally does not run the install doctor (`vidux doctor`)
    because that path can execute `npm test`. Runtime state comes from the
    JSON runtime doctor without --fix, so refreshes stay read-only.
    """
    config_cmd = _truth_command_payload(
        [sys.executable, str(VIDUX_ROOT / "scripts" / "vidux-config.py"), "check", "--json"],
        timeout=5,
    )
    runtime_cmd = _truth_command_payload(
        ["bash", str(VIDUX_ROOT / "scripts" / "vidux-doctor.sh"), "--json"],
        timeout=20,
    )
    config_data = config_cmd["data"]
    runtime_data = runtime_cmd["data"]
    runtime_checks = runtime_data.get("checks", []) if isinstance(runtime_data.get("checks"), list) else []
    runtime_warnings = [
        str(check.get("id", "unknown"))
        for check in runtime_checks
        if isinstance(check, dict) and check.get("status") == "warn"
    ]
    runtime_blockers = [
        str(check.get("id", "unknown"))
        for check in runtime_checks
        if isinstance(check, dict) and check.get("status") == "block"
    ]
    runtime_status = "block" if runtime_blockers else ("warn" if runtime_warnings else "pass")
    runtime_system_memory = next(
        (
            check
            for check in runtime_checks
            if isinstance(check, dict) and check.get("id") == "system_memory_pressure"
        ),
        {},
    )
    system_memory_keys = (
        "status",
        "available",
        "memory_pressure_free_pct",
        "memory_free_pct",
        "min_memory_free_pct",
        "memory_pct_source",
        "vm_free_mb",
        "vm_speculative_mb",
        "free_mb",
        "speculative_mb",
        "vm_pages_source",
        "total_bytes",
    )
    system_memory = {
        key: runtime_system_memory[key]
        for key in system_memory_keys
        if isinstance(runtime_system_memory, dict) and key in runtime_system_memory
    }

    payload = {
        "ok": True,
        "generated_at": _truth_now(),
        "repo_root": str(VIDUX_ROOT),
        "read_only": True,
        "browser_runs_install_doctor": False,
        "browser_runs_runtime_fix": False,
        "config": {
            "ok": bool(config_cmd["command_ok"] and config_data.get("status") == "ok"),
            "command": "python3 scripts/vidux-config.py check --json",
            "returncode": config_cmd["returncode"],
            "duration_ms": config_cmd["duration_ms"],
            "status": config_data.get("status", "unknown"),
            "source": config_data.get("source", "unknown"),
            "path": config_data.get("path", ""),
            "live_config_present": bool(config_data.get("live_config_present")),
            "using_example": bool(config_data.get("using_example")),
            "issues": config_data.get("issues", []),
            "plan_store": config_data.get("plan_store", {}),
            "error": config_cmd["error"],
        },
        "install_doctor": {
            "command": "vidux doctor",
            "role": "install/readiness",
            "browser_status": "not_run",
            "pre_hook_safe": False,
            "may_run_npm_test": True,
        },
        "runtime_doctor": {
            "ok": bool(runtime_cmd["command_ok"]),
            "command": "scripts/vidux-doctor.sh --json",
            "role": "runtime",
            "returncode": runtime_cmd["returncode"],
            "duration_ms": runtime_cmd["duration_ms"],
            "status": runtime_status,
            "pass": runtime_data.get("pass", 0),
            "total": runtime_data.get("total", 0),
            "warnings": runtime_warnings,
            "blockers": runtime_blockers,
            "system_memory": system_memory,
            "pre_hook_safe": True,
            "fix_available_only_with_explicit_flag": True,
            "error": runtime_cmd["error"],
        },
    }

    return payload


def _cache_vidux_truth_payload(payload: dict) -> None:
    if VIDUX_TRUTH_CACHE_TTL_SECONDS <= 0:
        return
    with _VIDUX_TRUTH_CACHE_LOCK:
        _VIDUX_TRUTH_CACHE["payload"] = payload
        _VIDUX_TRUTH_CACHE["generated_monotonic"] = time.monotonic()
        _VIDUX_TRUTH_CACHE["expires_at"] = time.monotonic() + VIDUX_TRUTH_CACHE_TTL_SECONDS


def _truth_with_cache_status(payload: dict, *, status: str, refreshing: bool, age_seconds: float | None) -> dict:
    enriched = copy.deepcopy(payload)
    enriched["cache"] = {
        "status": status,
        "refreshing": refreshing,
        "age_seconds": None if age_seconds is None else round(max(age_seconds, 0.0), 2),
        "ttl_seconds": VIDUX_TRUTH_CACHE_TTL_SECONDS,
    }
    return enriched


def _warming_vidux_truth_payload(*, refreshing: bool) -> dict:
    return _truth_with_cache_status(
        {
            "ok": True,
            "generated_at": _truth_now(),
            "repo_root": str(VIDUX_ROOT),
            "read_only": True,
            "browser_runs_install_doctor": False,
            "browser_runs_runtime_fix": False,
            "config": {
                "ok": False,
                "command": "python3 scripts/vidux-config.py check --json",
                "returncode": None,
                "duration_ms": None,
                "status": "warming",
                "source": "pending",
                "path": "",
                "live_config_present": False,
                "using_example": False,
                "issues": [],
                "plan_store": {},
                "error": "",
            },
            "install_doctor": {
                "command": "vidux doctor",
                "role": "install/readiness",
                "browser_status": "not_run",
                "pre_hook_safe": False,
                "may_run_npm_test": True,
            },
            "runtime_doctor": {
                "ok": False,
                "command": "scripts/vidux-doctor.sh --json",
                "role": "runtime",
                "returncode": None,
                "duration_ms": None,
                "status": "warming",
                "pass": 0,
                "total": 0,
                "warnings": [],
                "blockers": [],
                "system_memory": {},
                "pre_hook_safe": True,
                "fix_available_only_with_explicit_flag": True,
                "error": "",
            },
        },
        status="warming",
        refreshing=refreshing,
        age_seconds=None,
    )


def _refresh_vidux_truth_cache() -> None:
    try:
        payload = _collect_vidux_truth_payload()
        _cache_vidux_truth_payload(payload)
    finally:
        with _VIDUX_TRUTH_CACHE_LOCK:
            _VIDUX_TRUTH_CACHE["refreshing"] = False


def _start_vidux_truth_refresh() -> bool:
    with _VIDUX_TRUTH_CACHE_LOCK:
        if _VIDUX_TRUTH_CACHE.get("refreshing"):
            return False
        _VIDUX_TRUTH_CACHE["refreshing"] = True
    thread = threading.Thread(target=_refresh_vidux_truth_cache, daemon=True)
    thread.start()
    return True


def vidux_truth_payload(*, force_refresh: bool = False) -> dict:
    now = time.monotonic()
    if not force_refresh and VIDUX_TRUTH_CACHE_TTL_SECONDS > 0:
        with _VIDUX_TRUTH_CACHE_LOCK:
            cached = _VIDUX_TRUTH_CACHE.get("payload")
            expires_at = float(_VIDUX_TRUTH_CACHE.get("expires_at", 0.0))
            generated_at = float(_VIDUX_TRUTH_CACHE.get("generated_monotonic", 0.0))
            refreshing = bool(_VIDUX_TRUTH_CACHE.get("refreshing"))
        if cached is not None and now < expires_at:
            return _truth_with_cache_status(
                cached,  # type: ignore[arg-type]
                status="fresh",
                refreshing=refreshing,
                age_seconds=now - generated_at,
            )

    payload = _collect_vidux_truth_payload()
    _cache_vidux_truth_payload(payload)
    return _truth_with_cache_status(payload, status="fresh", refreshing=False, age_seconds=0.0)


def vidux_truth_cached_payload(*, background: bool = True) -> dict:
    """Return quickly for browser/monitor callers, refreshing expensive truth off-thread."""
    now = time.monotonic()
    with _VIDUX_TRUTH_CACHE_LOCK:
        cached = _VIDUX_TRUTH_CACHE.get("payload")
        expires_at = float(_VIDUX_TRUTH_CACHE.get("expires_at", 0.0))
        generated_at = float(_VIDUX_TRUTH_CACHE.get("generated_monotonic", 0.0))
        refreshing = bool(_VIDUX_TRUTH_CACHE.get("refreshing"))

    if cached is not None and now < expires_at:
        return _truth_with_cache_status(
            cached,  # type: ignore[arg-type]
            status="fresh",
            refreshing=refreshing,
            age_seconds=now - generated_at,
        )

    if background:
        started = _start_vidux_truth_refresh()
        refreshing = refreshing or started

    if cached is not None:
        return _truth_with_cache_status(
            cached,  # type: ignore[arg-type]
            status="stale",
            refreshing=refreshing,
            age_seconds=now - generated_at,
        )
    return _warming_vidux_truth_payload(refreshing=refreshing)

# /vidux task-FSM markers. Used by task_stats() to compute completion-bar.
# Per /vidux doctrine: completion (X/Y tasks) is the headline; ETA is parsed
# but does not drive the UI (tasks vary in difficulty, ETA is fiction).
TASKS_SECTION_RE = re.compile(r"^##\s+Tasks\s*\n(.*?)(?=^##\s|\Z)", re.M | re.S)
TASK_LINE_RE = re.compile(r"^-\s+\[(pending|in_progress|in_review|completed|blocked)\]", re.M)
ETA_RE = re.compile(r"\[ETA:\s*([\d.]+)h\]")
INVESTIGATION_RE = re.compile(r"\[Investigation:\s*([^\]]+?)\]")
PLAN_BRIEF_TASK_RE = re.compile(
    r"^-\s+\[(?P<status>pending|in_progress|in_review|completed|blocked)\]\s+(?P<body>.+?)\s*$",
    re.M,
)
PLAN_BRIEF_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?P<body>.+?)\s*$")
PLAN_BRIEF_TAG_RE = re.compile(r"\s*\[[A-Za-z][A-Za-z0-9 _/-]*:\s*[^\]]+\]")
PLAN_BRIEF_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
TASK_SEVERITY_RE = re.compile(r"(?:^|\s)(?:\[(?P<bracket>P[0-3])\]|(?P<plain>P[0-3])\b)", re.I)
TASK_STRUCTURED_TAG_RE = re.compile(
    r"\[(?P<key>owner|blocker|validation|evidence|proof):\s*(?P<value>[^\]]+)\]",
    re.I,
)
DASHBOARD_TASK_RE = re.compile(
    r"^-\s+\[(?P<status>pending|in_progress|in_review|completed|blocked)\]\s+(?P<body>.+?)\s*$"
)
DASHBOARD_OPEN_HEADING_RE = re.compile(r"^[ \t]{0,3}#{3,6}\s+(?P<body>.+?)\s*#*\s*$")
DASHBOARD_ASK_HEADING_RE = re.compile(r"^[ \t]{0,3}##\s+(?P<body>Q\d+\b.+?)\s*#*\s*$", re.I)
DASHBOARD_ASK_RESOLVED_RE = re.compile(r"\b(?:resolved:\s*\S+|status:\s*resolved)\b", re.I)
DASHBOARD_SOURCE_TAG_RE = re.compile(r"\[Source:\s*(?P<source>[^,\]]+)(?:,[^\]]+)?\]", re.I)
OPERATOR_BRIEF_ROW_RE = re.compile(
    r"^\s*[-*+]\s+(?P<key>[A-Za-z][A-Za-z _-]{0,31}):\s*(?P<value>.*?)\s*$"
)
OPERATOR_BRIEF_KEYS = frozenset({
    "status",
    "priority",
    "outcome",
    "next",
    "why",
    "validation",
    "cost",
    "evidence",
    "updated",
})
OUTCOME_SCORECARD_HEADERS = ("metric", "baseline", "current", "target", "status", "proof")
TERMINAL_OPERATOR_STATUSES = frozenset({"archived", "closed", "complete", "completed", "done", "exhausted"})
TASK_SEVERITY_ORDER = {"p0": 0, "p1": 1, "p2": 2, "p3": 3, "unspecified": 4}
PROOF_FILE_RE = re.compile(
    r"(?P<path>(?:(?:\.\.?/)?[^\s|]+/)*(?:evidence|investigations)/[^\s|]+\.md)"
)
EVIDENCE_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[-_].*)?\.md$")
DECISION_LOG_HEADING_RE = re.compile(
    r"^(?P<indent>[ \t]{0,3})(?P<marks>#{2,6})\s+decision(?:\s+log|s)\s*#*\s*$",
    re.I,
)
MARKDOWN_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})\s+\S")
DECISION_ENTRY_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?P<body>.+?)\s*$")
DECISION_KIND_RE = re.compile(r"^\[(?P<kind>[A-Z][A-Z0-9_-]{1,31})\]\s*(?P<rest>.*)$")
DECISION_DATE_RE = re.compile(r"^\[?(?P<date>\d{4}-\d{2}-\d{2}(?:[^\]]{0,60})?)\]?\s*(?P<rest>.*)$")
DECISION_DIRECTION_KINDS = frozenset({
    "DIRECTION",
    "PIVOT",
    "REFRAME",
    "DELETION",
    "MERGE",
    "STUCK",
})
# Sub-plan backlink: child plans declare their parent on a line near the top
# matching either `> Parent: <relpath>` or `**Parent:** <relpath>`. The relpath
# is taken verbatim and normalized to a string later.
PARENT_REF_RE = re.compile(
    r"^(?:>\s*Parent:|\*\*Parent:\*\*)\s*([^\s][^\n]*?)\s*$",
    re.M,
)
TASK_STATUSES = ("pending", "in_progress", "in_review", "completed", "blocked")


def claude_project_slug(repo_path: Path) -> str:
    return str(repo_path.expanduser().resolve(strict=False)).replace("/", "-")


def compact_session_text(value: str, limit: int = SESSION_EXCERPT_LIMIT) -> str:
    safe_value, _ = redact_sensitive_text(value or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", safe_value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    clipped = text[: max(0, limit - 3)].rsplit(" ", 1)[0].strip()
    return f"{clipped or text[: max(0, limit - 3)].strip()}..."


def extract_session_text(content: object) -> str:
    chunks: list[str] = []
    if isinstance(content, str):
        chunks.append(content)
    elif isinstance(content, dict):
        value = content.get("text")
        if isinstance(value, str):
            chunks.append(value)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if not isinstance(item, dict):
                continue
            block_type = str(item.get("type", ""))
            value = item.get("text")
            if isinstance(value, str) and block_type in ("", "text", "input_text", "output_text"):
                chunks.append(value)
    return compact_session_text(" ".join(chunks))


def read_tail_lines(path: Path, max_bytes: int = SESSION_TAIL_BYTES) -> tuple[list[str], bool]:
    try:
        size = path.stat().st_size
        start = max(size - max_bytes, 0)
        with path.open("rb") as f:
            f.seek(start)
            raw = f.read()
    except OSError:
        return [], False
    text = raw.decode("utf-8", errors="replace")
    truncated = start > 0
    if truncated and "\n" in text:
        text = text.split("\n", 1)[1]
    return [line for line in text.splitlines() if line.strip()], truncated


def parse_claude_session_file(path: Path, limit: int = SESSION_TURN_LIMIT) -> dict:
    lines, truncated = read_tail_lines(path)
    turns: list[dict] = []
    parsed_lines = 0
    invalid_lines = 0
    turns_seen = 0
    session_id = path.stem
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        if not isinstance(item, dict):
            continue
        parsed_lines += 1
        if item.get("sessionId"):
            session_id = str(item["sessionId"])
        message = item.get("message") if isinstance(item.get("message"), dict) else {}
        role = str(message.get("role") or item.get("role") or item.get("type") or "")
        if role not in ("user", "assistant"):
            continue
        text = extract_session_text(message.get("content", item.get("content")))
        if not text:
            continue
        turns_seen += 1
        turns.append({
            "role": role,
            "text": text,
            "timestamp": str(item.get("timestamp") or ""),
        })
        turns = turns[-limit:]
    return {
        "session_id": session_id,
        "turns": turns,
        "turns_seen": turns_seen,
        "parsed_lines": parsed_lines,
        "invalid_lines": invalid_lines,
        "tail_truncated": truncated,
    }


def missing_session_payload(repo: str, status: str = "missing") -> dict:
    project_dir = CLAUDE_PROJECTS_DIR / claude_project_slug(DEV_ROOT / repo)
    return {
        "available": False,
        "status": status,
        "repo": repo,
        "project_dir": str(project_dir),
        "path": "",
        "file": "",
        "session_id": "",
        "mtime": None,
        "age_days": None,
        "turns": [],
        "turns_seen": 0,
        "parsed_lines": 0,
        "invalid_lines": 0,
        "tail_truncated": False,
        "source": "~/.claude/projects/latest-jsonl",
    }


def latest_claude_session_for_repo(repo: str) -> dict:
    project_dir = CLAUDE_PROJECTS_DIR / claude_project_slug(DEV_ROOT / repo)
    if not project_dir.is_dir():
        return missing_session_payload(repo)
    try:
        candidates = [p for p in project_dir.glob("*.jsonl") if p.is_file()]
    except OSError:
        return missing_session_payload(repo, "unreadable")
    if not candidates:
        return missing_session_payload(repo, "empty")
    try:
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        mtime = latest.stat().st_mtime
    except OSError:
        return missing_session_payload(repo, "unreadable")
    session = parse_claude_session_file(latest)
    session.update({
        "available": True,
        "status": "ok",
        "repo": repo,
        "project_dir": str(project_dir),
        "path": str(latest),
        "file": latest.name,
        "mtime": mtime,
        "age_days": round((time.time() - mtime) / 86400, 1),
        "source": "~/.claude/projects/latest-jsonl",
    })
    return session


def discover_repo_sessions(repos: set[str]) -> dict[str, dict]:
    return {repo: latest_claude_session_for_repo(repo) for repo in sorted(repos)}


def compact_ledger_text(value: object, limit: int = 360) -> str:
    safe_value, _ = redact_sensitive_text(str(value or ""))
    text = re.sub(r"[\x00-\x1f]+", " ", safe_value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def ledger_path_candidates(value: object, repo: str) -> set[Path]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    try:
        raw_path = Path(raw).expanduser()
    except (OSError, ValueError):
        return set()

    candidates: set[Path] = set()
    try:
        if raw_path.is_absolute():
            candidates.add(raw_path.resolve(strict=False))
        else:
            candidates.add((DEV_ROOT / raw_path).resolve(strict=False))
            if repo:
                candidates.add((DEV_ROOT / repo / raw_path).resolve(strict=False))
    except (OSError, ValueError):
        return set()
    return candidates


def plan_ledger_match_paths(plan_path: Path) -> tuple[str, set[Path]]:
    resolved = plan_path.resolve(strict=False)
    paths = {resolved}
    try:
        rel = resolved.relative_to(DEV_ROOT)
    except (OSError, ValueError):
        return "", paths
    repo = rel.parts[0] if rel.parts else ""
    try:
        paths.add((DEV_ROOT / rel).resolve(strict=False))
    except (OSError, ValueError):
        pass
    if repo:
        try:
            paths.add((DEV_ROOT / repo / resolved.relative_to(DEV_ROOT / repo)).resolve(strict=False))
        except (OSError, ValueError):
            pass
    return repo, paths


def row_has_publish_or_checkpoint_event(row: dict) -> bool:
    event = str(row.get("event", ""))
    publish_kind = str(row.get("publish_kind", ""))
    return event in {"publish", "vidux_checkpoint"} or publish_kind == "checkpoint"


def ledger_row_matches_plan(row: dict, plan_paths: set[Path], repo: str) -> bool:
    row_repo = str(row.get("repo", ""))
    if row_repo and repo and row_repo != repo:
        return False
    path_fields: list[object] = [row.get("plan_path")]
    for key in ("files", "files_claimed"):
        values = row.get(key)
        if isinstance(values, list):
            path_fields.extend(values)

    for value in path_fields:
        candidate_repos = [row_repo]
        if repo and repo not in candidate_repos:
            candidate_repos.append(repo)
        for candidate_repo in candidate_repos:
            if ledger_path_candidates(value, candidate_repo) & plan_paths:
                return True
    return False


def compact_ledger_row(row: dict, line_number: int, scope: str) -> dict:
    files = row.get("files") if isinstance(row.get("files"), list) else []
    files_claimed = row.get("files_claimed") if isinstance(row.get("files_claimed"), list) else []
    return {
        "scope": scope,
        "line": line_number,
        "ts": compact_ledger_text(row.get("ts"), 80),
        "eid": compact_ledger_text(row.get("eid"), 140),
        "event": compact_ledger_text(row.get("event"), 80),
        "repo": compact_ledger_text(row.get("repo"), 120),
        "lane": compact_ledger_text(row.get("lane"), 160),
        "task_id": compact_ledger_text(row.get("task_id"), 120),
        "summary": compact_ledger_text(row.get("summary"), 260),
        "plan_path": compact_ledger_text(row.get("plan_path"), 220),
        "proof": compact_ledger_text(row.get("proof"), 320),
        "handoff_status": compact_ledger_text(row.get("handoff_status"), 80),
        "next_agent_resume": compact_ledger_text(row.get("next_agent_resume"), 320),
        "files_count": len(files),
        "files_claimed_count": len(files_claimed),
    }


def ledger_payload_for_plan(
    plan_path: Path,
    *,
    item_limit: int | None = None,
    scan_limit: int | None = None,
    ledger_file: Path | None = None,
) -> dict:
    item_limit = item_limit or LEDGER_ITEM_LIMIT
    scan_limit = scan_limit or LEDGER_SCAN_LIMIT
    ledger_file = ledger_file or LEDGER_FILE
    repo, plan_paths = plan_ledger_match_paths(plan_path)
    payload = {
        "available": False,
        "status": "missing",
        "read_only": True,
        "source": str(ledger_file),
        "plan_path": str(plan_path),
        "repo": repo,
        "scan_limit": scan_limit,
        "item_limit": item_limit,
        "scanned_rows": 0,
        "total_rows": 0,
        "scan_tail_truncated": False,
        "invalid_rows": 0,
        "plan_total": 0,
        "repo_total": 0,
        "returned": 0,
        "truncated": False,
        "items": [],
    }
    if not ledger_file.is_file():
        return payload

    recent: deque[tuple[int, str]] = deque(maxlen=scan_limit)
    try:
        with ledger_file.open("r", encoding="utf-8", errors="replace") as fh:
            for line_number, line in enumerate(fh, start=1):
                recent.append((line_number, line))
                payload["total_rows"] = line_number
    except OSError:
        payload["status"] = "unreadable"
        return payload

    payload["available"] = True
    payload["status"] = "ok"
    payload["scanned_rows"] = len(recent)
    payload["scan_tail_truncated"] = payload["total_rows"] > len(recent)
    if payload["scan_tail_truncated"]:
        payload["status"] = "partial"

    plan_items: list[dict] = []
    repo_items: list[dict] = []
    for line_number, line in reversed(recent):
        raw = line.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            payload["invalid_rows"] += 1
            continue
        if not isinstance(row, dict) or not row_has_publish_or_checkpoint_event(row):
            continue

        if ledger_row_matches_plan(row, plan_paths, repo):
            payload["plan_total"] += 1
            if len(plan_items) < item_limit:
                plan_items.append(compact_ledger_row(row, line_number, "plan"))
            continue

        if repo and str(row.get("repo", "")) == repo:
            payload["repo_total"] += 1
            if len(repo_items) < item_limit:
                repo_items.append(compact_ledger_row(row, line_number, "repo"))

    items = plan_items[:item_limit]
    if len(items) < item_limit:
        items.extend(repo_items[: item_limit - len(items)])
    payload["items"] = items
    payload["returned"] = len(items)
    payload["truncated"] = (
        payload["scan_tail_truncated"]
        or (payload["plan_total"] + payload["repo_total"]) > len(items)
    )
    return payload


def resolve_ledger_plan_target(raw: str) -> Path | None:
    path = safe_resolve(raw)
    if path and is_authority_plan_name(path.name):
        return path
    return None


def discover_plans() -> list[dict]:
    """Walk DEV_ROOT and return one entry per discovered authority plan.

    Post-processing wires up:
      * `children`: list of child plan-dicts that backlink this plan via
        `> Parent: <relpath>`. The list lives directly on the parent so the
        client can render indented sidebar rows without a second pass.
      * `aggregate_stats`: rolled-up `task_stats` across this plan plus every
        descendant in the parent→children tree. Cycle-safe via visited-set.
    """
    seen: set[Path] = set()
    plans: list[dict] = []
    for pattern in PLAN_GLOBS:
        # recursive=True so `**` in patterns expands to "any depth"; deduped
        # against the seen-set below so the shallow + recursive variants
        # of the same pattern don't double-count.
        for hit in glob(str(DEV_ROOT / pattern), recursive=True):
            path = Path(hit).resolve()
            if path in seen:
                continue
            # glob + resolve() follows symlinks, so a symlink
            # under DEV_ROOT can resolve OUTSIDE it. plan_meta() then does
            # path.relative_to(DEV_ROOT) with no guard, raising ValueError and
            # crashing the entire /api/plans dashboard -- discover_plans_cached()
            # never populates its cache on a raise, so every subsequent request
            # re-attempts and re-crashes until a human removes the symlink.
            # Re-validate containment after resolve() (same as safe_resolve does),
            # and defensively isolate any single bad entry so one malformed file
            # (symlink escape, permission error, transient I/O) can never take
            # down the whole fleet view.
            if not path.is_relative_to(DEV_ROOT):
                continue
            if "node_modules" in path.parts:
                continue
            if has_sensitive_text(str(path)):
                continue
            seen.add(path)
            try:
                plans.append(plan_meta(path))
            except (ValueError, OSError):
                continue
    plans = dedupe_legacy_repo_plans(plans)
    plans = attach_children(plans)
    aggregate_memo: dict[str, dict] = {}
    for plan in plans:
        plan["aggregate_stats"] = aggregate_stats(plan, _memo=aggregate_memo)
    sessions = discover_repo_sessions({plan["repo"] for plan in plans})
    for plan in plans:
        plan["session"] = sessions.get(plan["repo"], missing_session_payload(plan["repo"]))
    plans.sort(key=lambda p: (-p["mtime"], p["repo"], p["slug"]))
    return plans


def plan_list_payload(plans: list[dict]) -> list[dict]:
    """Return sidebar-safe plan metadata without recursively embedding children.

    `discover_plans()` keeps full child objects in memory because aggregate
    stats and tests use that shape. The HTTP list endpoint should not duplicate
    every child subtree in JSON; the browser can rehydrate child objects from
    these rels after one pass through the flat list.
    """
    payload: list[dict] = []
    for plan in plans:
        item = {
            k: v
            for k, v in plan.items()
            if k not in (
                "children",
                "dashboard_tasks",
                "dashboard_verdicts",
                "dashboard_inbox_entries",
                "dashboard_ask_owner_entries",
                "dashboard_ask_leo_entries",  # legacy key, if any residual payloads
            )
        }
        item["child_rels"] = [child["rel"] for child in plan.get("children", [])]
        payload.append(item)
    return payload


def format_eta_hours(hours: float) -> str:
    value = round(float(hours), 2)
    if value.is_integer():
        return f"{int(value)}h"
    return f"{value:.2f}".rstrip("0").rstrip(".") + "h"


def build_fleet_summary(plans: list[dict]) -> dict:
    plans_count = len(plans)
    repos_count = len({plan.get("repo", "") for plan in plans if plan.get("repo")})
    completed = 0
    total = 0
    eta_remaining = 0.0
    eta_tagged = 0
    eta_eligible = 0
    for plan in plans:
        stats = plan.get("task_stats") or {}
        counts = stats.get("counts") or {}
        completed += int(counts.get("completed") or 0)
        total += int(stats.get("total") or 0)
        eta_remaining += float(stats.get("eta_total") or 0.0)
        eta_tagged += int(stats.get("eta_tagged") or 0)
        eta_eligible += int(stats.get("eta_eligible") or 0)

    pct = round((completed / total) * 100) if total else 0
    eta_remaining = round(eta_remaining, 2)
    return {
        "plans": plans_count,
        "repos": repos_count,
        "tasks_completed": completed,
        "tasks_total": total,
        "completion_pct": pct,
        "eta_remaining_hours": eta_remaining,
        "eta_remaining_label": f"{format_eta_hours(eta_remaining)} tagged estimate",
        "eta_tagged": eta_tagged,
        "eta_eligible": eta_eligible,
    }


def dashboard_source_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(DEV_ROOT))
    except (OSError, ValueError):
        return str(path)


def resolve_plan_proof(plan_path: Path, raw: object) -> dict:
    """Classify a proof cell without allowing it to escape the owning plan."""
    value = str(raw or "").strip()
    if not value:
        return {"state": "needed", "label": "Proof needed"}

    match = PROOF_FILE_RE.search(value)
    if not match:
        return {"state": "needed", "label": "Proof needed", "note": value[:160]}

    reference = match.group("path").rstrip(".,;:)")
    plan_dir = plan_path.parent.resolve(strict=False)
    candidate = Path(reference)
    if not candidate.is_absolute():
        candidate = plan_dir / candidate
    candidate = candidate.resolve(strict=False)

    try:
        candidate.relative_to(plan_dir)
    except ValueError:
        return {"state": "invalid", "label": "Proof path rejected"}

    if not is_allowed_file_target(str(candidate)):
        return {"state": "invalid", "label": "Proof path rejected"}

    rel = str(candidate.relative_to(plan_dir))
    if not candidate.is_file():
        return {
            "state": "missing",
            "label": "Proof missing",
            "rel": rel,
        }

    return {
        "state": "available",
        "label": "Open proof",
        "path": str(candidate),
        "rel": rel,
        "tab": f"EVD:{candidate}",
    }


def dashboard_base_item(plan: dict, source_path: Path, raw: dict, *, kind: str, tab: str) -> dict:
    brief = plan.get("operator_brief") or {}
    freshness = operator_brief_freshness(brief.get("updated", ""))
    item = {
        "kind": kind,
        "repo": plan.get("repo", ""),
        "rel": plan.get("rel", ""),
        "path": plan.get("path", ""),
        "source_path": str(source_path),
        "source_rel": dashboard_source_rel(source_path),
        "tab": tab,
        "line": raw.get("line"),
        "label": raw.get("label", ""),
        "status": raw.get("status", ""),
        "plan_priority": int(brief.get("priority") or 0),
        "plan_freshness": freshness.get("status", "unknown"),
        "plan_mtime": float(plan.get("mtime") or 0),
    }
    for key in ("severity", "owner", "blocker", "validation", "proof"):
        value = raw.get(key)
        if value:
            item[key] = value
    proof_path = raw.get("proof_path", "")
    if proof_path:
        item["proof_path"] = proof_path
        if raw.get("proof_rel"):
            item["proof_rel"] = raw.get("proof_rel")
        elif Path(str(proof_path)).is_absolute():
            item["proof_rel"] = dashboard_source_rel(Path(str(proof_path)))
        else:
            item["proof_rel"] = proof_path
    return item


def build_mission_control(plans: list[dict]) -> dict:
    candidates: list[dict] = []
    terminal_briefs = 0
    mtime_by_rel = {plan.get("rel", ""): plan.get("mtime") or 0 for plan in plans}
    for plan in plans:
        brief = plan.get("operator_brief") or {}
        if not brief or not (brief.get("outcome") or brief.get("next")):
            continue
        if brief.get("status") in TERMINAL_OPERATOR_STATUSES:
            terminal_briefs += 1
            continue
        plan_path = Path(plan.get("path", ""))
        item = {
            **copy.deepcopy(brief),
            "repo": plan.get("repo", ""),
            "slug": plan.get("slug", ""),
            "rel": plan.get("rel", ""),
            "path": plan.get("path", ""),
            "source_path": str(plan_path),
            "source_rel": dashboard_source_rel(plan_path),
            "tab": "PLAN.md",
            "scorecard": copy.deepcopy(plan.get("outcome_scorecard") or []),
            "scorecard_total": int(plan.get("outcome_scorecard_total") or 0),
            "scorecard_truncated": bool(plan.get("outcome_scorecard_truncated")),
        }
        item["evidence_target"] = resolve_plan_proof(plan_path, item.get("evidence"))
        for metric in item["scorecard"]:
            metric["proof_target"] = resolve_plan_proof(plan_path, metric.get("proof"))
        item["freshness"] = operator_brief_freshness(item.get("updated", ""))
        candidates.append(item)

    candidates.sort(
        key=lambda item: (
            {"fresh": 0, "unknown": 1, "stale": 2}.get(
                (item.get("freshness") or {}).get("status"), 3
            ),
            -int(item.get("priority") or 0),
            -float(mtime_by_rel.get(item.get("rel", ""), 0)),
            str(item.get("rel") or ""),
        )
    )
    selected = candidates[0] if candidates else None
    selected_freshness = (
        (selected.get("freshness") or {}).get("status") if selected else None
    )
    ranking_pool = [
        item
        for item in candidates
        if (item.get("freshness") or {}).get("status") == selected_freshness
    ]
    top_priority = int(selected.get("priority") or 0) if selected else 0
    tied = [item for item in ranking_pool if int(item.get("priority") or 0) == top_priority]
    tied_projects = sorted({mission_candidate_label(item) for item in tied})
    if selected:
        if len(ranking_pool) == 1:
            selected["selection_reason"] = (
                "only declared current goal"
                if len(candidates) == 1
                else f"only {selected_freshness} current goal"
            )
        elif len(tied) > 1:
            selected["selection_reason"] = (
                f"priority {top_priority} · newest of {len(tied)} tied current goals"
            )
        else:
            selected["selection_reason"] = (
                f"priority {top_priority} · highest of {len(ranking_pool)} {selected_freshness} current goals"
            )

    if not selected:
        authority = {
            "state": "missing",
            "claims_total": 0,
            "tied_total": 0,
            "tied_projects": [],
        }
    elif len(tied) > 1:
        selected_label = mission_candidate_label(selected)
        authority = {
            "state": "conflict",
            "claims_total": len(ranking_pool),
            "tied_total": len(tied),
            "priority": top_priority,
            "tied_projects": tied_projects,
            "explanation": (
                f"{len(tied)} plans share priority {top_priority}. Showing {selected_label} by latest "
                "plan change, then plan name. Change Priority in one Operator Brief to choose the default."
            ),
        }
    elif len(candidates) > 1:
        selected_label = mission_candidate_label(selected)
        claim_phrase = "plan declares" if len(ranking_pool) == 1 else "plans declare"
        authority = {
            "state": "ranked",
            "claims_total": len(ranking_pool),
            "tied_total": 1,
            "priority": top_priority,
            "tied_projects": tied_projects,
            "explanation": (
                f"{len(ranking_pool)} {selected_freshness} {claim_phrase} current work. Showing {selected_label} because priority "
                f"{top_priority} is highest."
            ),
        }
    else:
        authority = {
            "state": "selected",
            "claims_total": 1,
            "tied_total": 1,
            "priority": top_priority,
            "tied_projects": tied_projects,
        }
    return {
        "briefs_total": len(candidates),
        "terminal_briefs_total": terminal_briefs,
        "deferred_briefs_total": len(candidates) - len(ranking_pool),
        "selected": selected,
        "authority": authority,
    }


def mission_candidate_label(item: dict) -> str:
    repo = clean_structured_value(item.get("repo") or "Project", 80)
    slug = clean_structured_value(item.get("slug") or "", 80)
    if slug and slug != "_root_":
        return f"{repo} / {slug}"
    return repo


def has_current_operator_brief(plan: dict) -> bool:
    brief = plan.get("operator_brief") or {}
    return bool(
        brief.get("outcome")
        and brief.get("next")
        and brief.get("status") not in TERMINAL_OPERATOR_STATUSES
    )


def discover_project_inventory(plans: list[dict]) -> list[dict]:
    """Return path-free project setup state for the first-run cockpit."""
    inventory: dict[str, dict] = {}
    for plan in plans:
        name = clean_structured_value(plan.get("repo") or "", 80)
        if not name:
            continue
        project = inventory.setdefault(name, {"name": name, "plans": 0, "briefs": 0})
        project["plans"] += 1
        if has_current_operator_brief(plan):
            project["briefs"] += 1

    try:
        root_children = sorted(DEV_ROOT.iterdir(), key=lambda path: path.name.casefold())
    except OSError:
        root_children = []
    for child in root_children:
        name = clean_structured_value(child.name, 80)
        if not name or name.startswith(".") or has_sensitive_text(name) or child.is_symlink():
            continue
        try:
            if not child.is_dir():
                continue
            git_marker = child / ".git"
            if git_marker.is_symlink() or not (git_marker.is_dir() or git_marker.is_file()):
                continue
        except OSError:
            continue
        inventory.setdefault(name, {"name": name, "plans": 0, "briefs": 0})

    projects = []
    for project in inventory.values():
        if project["plans"] == 0:
            state = "unconnected"
        elif project["briefs"] == 0:
            state = "needs_brief"
        else:
            state = "ready"
        projects.append({**project, "state": state})
    projects.sort(key=lambda item: item["name"].casefold())
    return projects


def build_onboarding(plans: list[dict], mission: dict, project_limit: int = 12) -> dict:
    projects = discover_project_inventory(plans)
    connected = sum(1 for project in projects if project["plans"] > 0)
    unconnected = sum(1 for project in projects if project["plans"] == 0)
    briefs_total = int(mission.get("briefs_total") or 0)
    missing_briefs = sum(1 for plan in plans if not has_current_operator_brief(plan))
    authority_state = (mission.get("authority") or {}).get("state")

    if not projects:
        state = "empty"
    elif not plans:
        state = "projects_found"
    elif authority_state == "conflict":
        state = "authority_conflict"
    elif not mission.get("selected"):
        state = "needs_brief"
    else:
        state = "ready"

    return {
        "state": state,
        "projects_total": len(projects),
        "plans_total": len(plans),
        "connected_projects": connected,
        "unconnected_projects": unconnected,
        "briefs_total": briefs_total,
        "missing_briefs_total": missing_briefs,
        "projects": projects[:project_limit],
        "truncated": len(projects) > project_limit,
        "init_command": "vidux init --here",
    }


def build_dashboard(plans: list[dict], limit: int = DASHBOARD_ITEM_LIMIT) -> dict:
    categories: dict[str, dict] = {
        "next": {"label": "Next", "items": [], "total": 0},
        "in_progress": {"label": "In Progress", "items": [], "total": 0},
        "blocked": {"label": "Blocked", "items": [], "total": 0},
        "verdicts": {"label": "Verdicts", "items": [], "total": 0},
        "decisions": {"label": "Decisions", "items": [], "total": 0},
        "ask_owner": {"label": "Ask owner", "items": [], "total": 0},
        "inbox": {"label": "INBOX", "items": [], "total": 0},
    }

    def add(category: str, item: dict) -> None:
        bucket = categories[category]
        bucket["items"].append(item)

    for plan in plans:
        plan_path = Path(plan.get("path", ""))
        for task in plan.get("dashboard_tasks", []) or []:
            status = task.get("status", "")
            if status in ("in_progress", "blocked"):
                add(status, dashboard_base_item(plan, plan_path, task, kind="task", tab="PLAN.md"))
            elif status == "pending" and task.get("severity") in ("p0", "p1"):
                add("next", dashboard_base_item(plan, plan_path, task, kind="task", tab="PLAN.md"))

        for verdict in plan.get("dashboard_verdicts", []) or []:
            add("verdicts", dashboard_base_item(plan, plan_path, verdict, kind="verdict", tab="PLAN.md"))

        for entry in (plan.get("decision_log") or {}).get("recent_directions", []) or []:
            label_parts = [part for part in [entry.get("date"), entry.get("body") or entry.get("raw")] if part]
            label = clean_plan_brief_text(" ".join(label_parts), 220)
            if label:
                add(
                    "decisions",
                    dashboard_base_item(
                        plan,
                        plan_path,
                        {
                            "label": label,
                            "line": entry.get("line"),
                            "status": (entry.get("kind") or "decision").lower(),
                        },
                        kind="decision",
                        tab="Decision Log",
                    ),
                )

        inbox_path = plan_path.parent / "INBOX.md"
        for entry in plan.get("dashboard_inbox_entries", []) or []:
            add("inbox", dashboard_base_item(plan, inbox_path, entry, kind="inbox", tab="INBOX.md"))

        ask_path = resolve_ask_owner_path(plan_path.parent)
        for entry in plan.get("dashboard_ask_owner_entries", []) or []:
            if ask_path is None:
                break
            add(
                "ask_owner",
                dashboard_base_item(
                    plan,
                    ask_path,
                    entry,
                    kind="ask_owner",
                    tab=ask_path.name,
                ),
            )

    def task_order(item: dict) -> tuple:
        return (
            TASK_SEVERITY_ORDER.get(item.get("severity", "unspecified"), 4),
            {"blocked": 0, "in_progress": 1, "pending": 2}.get(item.get("status"), 3),
            -int(item.get("plan_priority") or 0),
            {"fresh": 0, "unknown": 1, "stale": 2}.get(item.get("plan_freshness"), 3),
            -float(item.get("plan_mtime") or 0),
            str(item.get("repo") or "").casefold(),
            int(item.get("line") or 0),
        )

    mission = build_mission_control(plans)
    selected_rel = (mission.get("selected") or {}).get("rel", "")
    for key, bucket in categories.items():
        if key in {"next", "in_progress", "blocked"}:
            bucket["items"].sort(key=task_order)
        bucket["total"] = len(bucket["items"])
        if key in {"next", "in_progress", "blocked"}:
            simple_items = [
                item for item in bucket["items"] if item.get("rel") != selected_rel
            ]
            bucket["simple_total"] = len(simple_items)
            bucket["simple_items"] = simple_items[: min(8, limit)]
        bucket["items"] = bucket["items"][:limit]
        bucket["truncated"] = bucket["total"] > len(bucket["items"])
        bucket["limit"] = limit

    return {
        "generated_at": _truth_now(),
        "plans_scanned": len(plans),
        "repos": len({plan.get("repo", "") for plan in plans if plan.get("repo")}),
        "limit": limit,
        "mission_control": mission,
        "onboarding": build_onboarding(plans, mission),
        "categories": categories,
    }


def attach_children(plans: list[dict]) -> list[dict]:
    """Group plans by parent_rel and attach `children` lists in place.

    Lookup is two-tier: prefer an exact match against full DEV_ROOT-rel paths
    (e.g., `repo/vidux/foo/PLAN.md`), then fall back to a repo-scoped match
    where the backlink is written relative to the repo root (e.g.,
    `vidux/foo/PLAN.md` from a child living in the same repo). Authors write
    backlinks the natural way — relative to where they are — so the resolver
    has to bridge both shapes.

    Children are sorted by rel-path for deterministic UI order. Plans without
    a recognized parent get `children = []` so the frontend can branch on
    existence-only rather than presence checks.
    """
    by_rel: dict[str, dict] = {p["rel"]: p for p in plans}
    by_path: dict[Path, dict] = {Path(p["path"]).resolve(): p for p in plans}
    # Repo-scoped index: ('<repo>', '<repo-relative-rel>') → plan. The
    # repo-relative rel strips the leading `<repo>/` so a child's
    # `vidux/foo/PLAN.md` backlink finds `<repo>/vidux/foo/PLAN.md`.
    by_repo_rel: dict[tuple[str, str], dict] = {}
    for plan in plans:
        parts = plan["rel"].split("/")
        if len(parts) >= 2:
            by_repo_rel[(plan["repo"], "/".join(parts[1:]))] = plan
    for plan in plans:
        plan["children"] = []
    for plan in plans:
        parent_rel = plan.get("parent_rel")
        if not parent_rel:
            continue
        parent = by_rel.get(parent_rel)
        if parent is None:
            parent = resolve_relative_parent(plan, parent_rel, by_path)
        if parent is None:
            # Backlink wasn't a full DEV_ROOT-rel — try repo-scoped resolution.
            parent = by_repo_rel.get((plan["repo"], parent_rel))
        if parent is None:
            # Dangling backlink — child references a parent we didn't discover
            # in either repo. Leave it ungrouped at the sidebar root.
            continue
        if parent is plan:
            # Self-reference (a plan that says "Parent: <self>"). Ignore.
            continue
        parent["children"].append(plan)
    for plan in plans:
        plan["children"].sort(key=lambda c: c["rel"])
    return plans


def resolve_relative_parent(plan: dict, parent_ref: str, by_path: dict[Path, dict]) -> dict | None:
    """Resolve `Parent: ../../PLAN.md` style refs from the child plan's directory."""
    if not parent_ref.startswith(("./", "../")):
        return None
    try:
        candidate = (Path(plan["path"]).resolve().parent / parent_ref).resolve()
        candidate.relative_to(DEV_ROOT)
    except (OSError, ValueError):
        return None
    return by_path.get(candidate)


def aggregate_stats(
    plan: dict,
    _visited: set[str] | None = None,
    _memo: dict[str, dict] | None = None,
) -> dict:
    """Recursively roll up task_stats across a plan and all descendants.

    Returns the same shape as `task_stats()` (counts/total/eta_total/
    eta_tagged/eta_eligible) plus a `descendants` count. Cycle-safe: the
    visited set tracks rel-paths so a cyclic Parent: chain (broken plan
    authorship) never recurses forever.
    """
    if _visited is None:
        _visited = set()
    if _memo is None:
        _memo = {}
    rel = plan.get("rel", "")
    if rel in _memo:
        return _memo[rel]
    if rel in _visited:
        return {
            "counts": {s: 0 for s in TASK_STATUSES},
            "total": 0,
            "eta_total": 0.0,
            "eta_tagged": 0,
            "eta_eligible": 0,
            "descendants": 0,
        }
    _visited.add(rel)

    own = plan.get("task_stats") or {}
    counts = {s: int((own.get("counts") or {}).get(s, 0)) for s in TASK_STATUSES}
    total = int(own.get("total", 0))
    eta_total = float(own.get("eta_total", 0.0))
    eta_tagged = int(own.get("eta_tagged", 0))
    eta_eligible = int(own.get("eta_eligible", 0))
    descendants = 0

    for child in plan.get("children", []) or []:
        sub = aggregate_stats(child, _visited.copy(), _memo)
        for s in TASK_STATUSES:
            counts[s] += int((sub.get("counts") or {}).get(s, 0))
        total += int(sub.get("total", 0))
        eta_total += float(sub.get("eta_total", 0.0))
        eta_tagged += int(sub.get("eta_tagged", 0))
        eta_eligible += int(sub.get("eta_eligible", 0))
        descendants += 1 + int(sub.get("descendants", 0))

    result = {
        "counts": counts,
        "total": total,
        "eta_total": round(eta_total, 2),
        "eta_tagged": eta_tagged,
        "eta_eligible": eta_eligible,
        "descendants": descendants,
    }
    _memo[rel] = result
    return result


def dedupe_legacy_repo_plans(plans: list[dict]) -> list[dict]:
    """Drop legacy-checkout duplicates when a canonical repo has the same plan."""
    winners: dict[tuple[str, ...], dict] = {}
    for plan in plans:
        parts = Path(plan["rel"]).parts
        if not parts:
            continue
        canonical_repo = LEGACY_REPO_ALIASES.get(plan["repo"], plan["repo"])
        key = (canonical_repo, *parts[1:])
        current = winners.get(key)
        if current is None or plan_preference(plan) > plan_preference(current):
            winners[key] = plan
            continue
        if plan_preference(plan) == plan_preference(current) and plan["mtime"] > current["mtime"]:
            winners[key] = plan
    return list(winners.values())


def plan_preference(plan: dict) -> int:
    return 0 if plan["repo"] in LEGACY_REPO_ALIASES else 1


def plan_meta(path: Path) -> dict:
    rel = path.relative_to(DEV_ROOT)
    parts = rel.parts
    repo = parts[0]
    # Canonical PLAN.md files inherit their directory slug. Named repo-native
    # authorities can share one directory, so their filename supplies the slug.
    parent_dir = path.parent
    if path.name != "PLAN.md":
        slug = path.name[: -len(".plan.md")]
    elif parent_dir == DEV_ROOT / repo:
        slug = "_root_"
    else:
        slug = parent_dir.name
    mtime = path.stat().st_mtime
    age_days = (time.time() - mtime) / 86400
    if age_days <= HOT_DAYS:
        status = "hot"
    elif age_days <= STALE_DAYS:
        status = "stale"
    else:
        status = "cold"
    siblings = [f for f in SIBLING_FILES if (parent_dir / f).is_file()]
    try:
        raw_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raw_text = ""
    text, sensitive_redactions = redact_sensitive_text(raw_text)
    purpose = extract_purpose_from_text(text)
    stats = task_stats(text)
    decision_log = parse_decision_log(text)
    scorecard = parse_outcome_scorecard(text)
    investigations = discover_investigations(parent_dir, text)
    evidence = discover_evidence(parent_dir)
    parent_rel = extract_parent_rel(text)
    dashboard_inbox_entries = read_open_entries(parent_dir / "INBOX.md") if "INBOX.md" in siblings else []
    ask_owner_path = resolve_ask_owner_path(parent_dir)
    dashboard_ask_owner_entries = (
        read_ask_owner_entries(ask_owner_path) if ask_owner_path is not None else []
    )
    return {
        "repo": repo,
        "slug": slug,
        "path": str(path),
        "rel": str(rel),
        "size": path.stat().st_size,
        "mtime": mtime,
        "age_days": round(age_days, 1),
        "status": status,
        "siblings": siblings,
        "purpose": purpose,
        "task_stats": stats,
        "brief": plan_brief(text, purpose, stats, decision_log),
        "decision_log": decision_log,
        "investigations": investigations,
        "evidence": evidence,
        "parent_rel": parent_rel,
        "operator_brief": parse_operator_brief(text),
        "outcome_scorecard": scorecard["items"],
        "outcome_scorecard_total": scorecard["total"],
        "outcome_scorecard_truncated": scorecard["truncated"],
        "content_redacted": sensitive_redactions > 0,
        "sensitive_redactions": sensitive_redactions,
        "dashboard_tasks": extract_dashboard_tasks(text),
        "dashboard_verdicts": extract_dashboard_verdicts(text),
        "dashboard_inbox_entries": dashboard_inbox_entries,
        "dashboard_ask_owner_entries": dashboard_ask_owner_entries,
    }


def extract_parent_rel(text: str) -> str | None:
    """Pull the rel-path from a `> Parent:` or `**Parent:**` backlink.

    Returns a forward-slash rel-path (e.g., `vidux/design-overhaul/PLAN.md`)
    with surrounding backticks/quotes stripped. Anything after whitespace
    in the value (e.g., `... task D2`) is dropped — only the path is meaningful
    for parent→children grouping. Returns None if no backlink is present.
    """
    m = PARENT_REF_RE.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    # Drop backticks/quotes/markdown emphasis around the path token.
    raw = raw.strip("`'\"")
    # Some plans extend the backlink with `... task D2` — keep only the path.
    token = raw.split()[0] if raw else ""
    token = token.strip("`'\",")
    if not token or token in (".", ".."):
        return None
    # Normalize to forward slashes; PLAN.md `rel` strings always use / on POSIX
    # because `Path.relative_to(...)` plus `str()` round-trips that way on macOS.
    return token.replace("\\", "/")


def task_stats(text: str) -> dict:
    """Parse the `## Tasks` section into status counts + ETA total.

    Returns counts for every known status, total tasks, ETA hours summed
    over pending+in_progress+in_review (ETAs on terminal states are ignored
    per /vidux), and how many of those eligible tasks actually have an ETA
    tag (eta_tagged) vs. how many should (eta_eligible).
    """
    counts = {s: 0 for s in TASK_STATUSES}
    eta_total = 0.0
    eta_tagged = 0
    eta_eligible = 0
    m = TASKS_SECTION_RE.search(text)
    if not m:
        return {
            "counts": counts,
            "total": 0,
            "eta_total": 0.0,
            "eta_tagged": 0,
            "eta_eligible": 0,
        }
    body = m.group(1)
    for line in body.splitlines():
        lm = TASK_LINE_RE.match(line)
        if not lm:
            continue
        status = lm.group(1)
        counts[status] += 1
        if status in ("pending", "in_progress", "in_review"):
            eta_eligible += 1
            em = ETA_RE.search(line)
            if em:
                eta_tagged += 1
                try:
                    eta_total += float(em.group(1))
                except ValueError:
                    pass
    return {
        "counts": counts,
        "total": sum(counts.values()),
        "eta_total": round(eta_total, 2),
        "eta_tagged": eta_tagged,
        "eta_eligible": eta_eligible,
    }


def section_body(text: str, heading: str) -> str:
    """Return a markdown section body by heading text."""
    lines = text.splitlines()
    start_index = None
    start_level = None
    heading_re = re.compile(
        rf"^[ \t]{{0,3}}(?P<marks>##{{1,6}})\s+{re.escape(heading)}\s*#*\s*$",
        re.I,
    )
    for i, line in enumerate(lines):
        m = heading_re.match(line)
        if not m:
            continue
        start_index = i
        start_level = len(m.group("marks"))
        break
    if start_index is None or start_level is None:
        return ""
    body_lines: list[str] = []
    for line in lines[start_index + 1:]:
        hm = MARKDOWN_HEADING_RE.match(line)
        if hm and len(hm.group(1)) <= start_level:
            break
        body_lines.append(line)
    return "\n".join(body_lines).strip()


def clean_plan_brief_text(value: str, limit: int = 180) -> str:
    """Compact markdown-ish plan text into a one-line UI summary."""
    text = PLAN_BRIEF_LINK_RE.sub(r"\1", value or "")
    text = PLAN_BRIEF_TAG_RE.sub("", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"[*_#>]+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -")
    if len(text) <= limit:
        return text
    clipped = text[: max(0, limit - 3)].rsplit(" ", 1)[0].strip()
    return f"{clipped or text[: max(0, limit - 3)].strip()}..."


def normalize_structured_status(value: object) -> str:
    status = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower())
    return status.strip("-") or "unknown"


def clean_structured_value(value: object, limit: int = 500) -> str:
    text = str(value or "").strip()
    text = PLAN_BRIEF_LINK_RE.sub(r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    clipped = text[: max(0, limit - 3)].rsplit(" ", 1)[0].strip()
    return f"{clipped or text[: max(0, limit - 3)].strip()}..."


def parse_operator_brief(text: str) -> dict:
    brief: dict[str, object] = {}
    for line_number, line in markdown_section_lines(text, "Operator Brief"):
        match = OPERATOR_BRIEF_ROW_RE.match(line)
        if not match:
            continue
        key = re.sub(r"[ -]+", "_", match.group("key").strip().lower())
        if key not in OPERATOR_BRIEF_KEYS:
            continue
        value = clean_structured_value(match.group("value"))
        if not value:
            continue
        if "line" not in brief:
            brief["line"] = line_number
        if key == "priority":
            try:
                priority = int(value)
            except ValueError:
                priority = 0
            brief[key] = max(0, min(100, priority))
        elif key == "status":
            brief[key] = normalize_structured_status(value)
        else:
            brief[key] = value
    if brief and "priority" not in brief:
        brief["priority"] = 0
    if brief and "status" not in brief:
        brief["status"] = "unknown"
    return brief


def split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return []
    cells = re.split(r"(?<!\\)\|", stripped[1:-1])
    return [clean_structured_value(cell.replace(r"\|", "|"), 400) for cell in cells]


def parse_outcome_scorecard(text: str, limit: int = 50) -> dict:
    lines = markdown_section_lines(text, "Outcome Scorecard")
    header_index = None
    for index, (_, line) in enumerate(lines):
        cells = split_markdown_table_row(line)
        if tuple(cell.lower() for cell in cells) == OUTCOME_SCORECARD_HEADERS:
            header_index = index
            break
    if header_index is None or header_index + 1 >= len(lines):
        return {"items": [], "total": 0, "truncated": False}

    separator = split_markdown_table_row(lines[header_index + 1][1])
    if len(separator) != len(OUTCOME_SCORECARD_HEADERS) or not all(
        re.fullmatch(r":?-{3,}:?", cell) for cell in separator
    ):
        return {"items": [], "total": 0, "truncated": False}

    rows: list[dict] = []
    total = 0
    for line_number, line in lines[header_index + 2:]:
        cells = split_markdown_table_row(line)
        if not cells:
            if rows and not line.strip():
                break
            continue
        if len(cells) != len(OUTCOME_SCORECARD_HEADERS):
            continue
        row = dict(zip(OUTCOME_SCORECARD_HEADERS, cells))
        if not row["metric"]:
            continue
        row["status"] = normalize_structured_status(row["status"])
        row["line"] = line_number
        total += 1
        if len(rows) < limit:
            rows.append(row)
    return {"items": rows, "total": total, "truncated": total > len(rows)}


def operator_brief_freshness(updated: object, today: date | None = None) -> dict:
    raw = str(updated or "").strip()
    try:
        updated_date = date.fromisoformat(raw)
    except ValueError:
        return {"status": "unknown", "age_days": None}
    age_days = max(0, ((today or date.today()) - updated_date).days)
    return {
        "status": "fresh" if age_days <= 7 else "stale",
        "age_days": age_days,
    }


def markdown_section_lines(text: str, heading: str) -> list[tuple[int, str]]:
    """Return (1-based line, text) pairs for a markdown heading body."""
    lines = text.splitlines()
    start_index = None
    start_level = None
    heading_re = re.compile(
        rf"^[ \t]{{0,3}}(?P<marks>##{{1,6}})\s+{re.escape(heading)}\s*#*\s*$",
        re.I,
    )
    for i, line in enumerate(lines):
        m = heading_re.match(line)
        if not m:
            continue
        start_index = i
        start_level = len(m.group("marks"))
        break
    if start_index is None or start_level is None:
        return []

    body: list[tuple[int, str]] = []
    for i, line in enumerate(lines[start_index + 1:], start=start_index + 2):
        hm = MARKDOWN_HEADING_RE.match(line)
        if hm and len(hm.group(1)) <= start_level:
            break
        body.append((i, line))
    return body


def extract_dashboard_tasks(text: str) -> list[dict]:
    tasks: list[dict] = []
    for line_number, line in markdown_section_lines(text, "Tasks"):
        m = DASHBOARD_TASK_RE.match(line)
        if not m:
            continue
        status = m.group("status")
        if status not in ("pending", "in_progress", "blocked"):
            continue
        body = m.group("body")
        severity_match = TASK_SEVERITY_RE.search(body)
        severity = (
            (severity_match.group("bracket") or severity_match.group("plain")).lower()
            if severity_match
            else "unspecified"
        )
        structured: dict[str, str] = {}
        for tag in TASK_STRUCTURED_TAG_RE.finditer(body):
            key = tag.group("key").lower()
            if key in ("evidence", "proof"):
                key = "proof"
            structured[key] = clean_structured_value(tag.group("value"), 320)
        label_body = re.sub(r"^\s*(?:\[?P[0-3]\]?\s*[:\-–—]?\s*)", "", body, flags=re.I)
        label = clean_plan_brief_text(label_body, 320)
        if label:
            tasks.append(
                {
                    "status": status,
                    "severity": severity,
                    "label": label,
                    "line": line_number,
                    **structured,
                }
            )
    return tasks


def extract_dashboard_verdicts(text: str) -> list[dict]:
    verdicts: list[dict] = []
    for line_number, line in markdown_section_lines(text, "Evidence"):
        m = PLAN_BRIEF_BULLET_RE.match(line)
        if not m:
            continue
        body = m.group("body")
        lowered = body.lower()
        has_subject = any(
            phrase in lowered
            for phrase in (
                "planner-executor",
                "bakeoff",
                "h1/h2/h3",
                "kernel handoff",
                "kernel >= freeform",
            )
        )
        has_verdict = any(
            phrase in lowered
            for phrase in (
                "refuted",
                "lost to freeform",
                "kernel-cheaper=false",
                "decision.md",
            )
        )
        if not (has_subject and has_verdict):
            continue

        label = clean_plan_brief_text(body, 260)
        if not label:
            continue
        status = "refuted" if ("refuted" in lowered or "lost to freeform" in lowered) else "verdict"
        source = ""
        source_match = DASHBOARD_SOURCE_TAG_RE.search(body)
        if source_match:
            source = source_match.group("source").strip()
        verdict = {
            "status": status,
            "label": label,
            "line": line_number,
        }
        if source:
            verdict["proof_path"] = source
        verdicts.append(verdict)
    return verdicts


def open_entry_lines(text: str) -> list[tuple[int, str]]:
    open_lines = markdown_section_lines(text, "Open")
    if open_lines:
        return open_lines
    return list(enumerate(text.splitlines(), start=1))


def extract_open_entries(text: str) -> list[dict]:
    entries: list[dict] = []
    for line_number, line in open_entry_lines(text):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            continue
        if MARKDOWN_HEADING_RE.match(line) and not DASHBOARD_OPEN_HEADING_RE.match(line):
            continue

        label = ""
        hm = DASHBOARD_OPEN_HEADING_RE.match(line)
        if hm:
            label = hm.group("body")
        else:
            bm = PLAN_BRIEF_BULLET_RE.match(line)
            if bm:
                label = bm.group("body")
        label = clean_plan_brief_text(label, 220)
        if label:
            entries.append({"label": label, "line": line_number})
    return entries


def read_open_entries(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    text, _ = redact_sensitive_text(text)
    return extract_open_entries(text)


def extract_ask_owner_entries(text: str) -> list[dict]:
    if markdown_section_lines(text, "Open"):
        return extract_open_entries(text)

    lines = text.splitlines()
    entries: list[dict] = []
    for index, line in enumerate(lines):
        m = DASHBOARD_ASK_HEADING_RE.match(line)
        if not m:
            continue
        section_lines: list[str] = []
        for next_line in lines[index + 1:]:
            if re.match(r"^[ \t]{0,3}##\s+\S", next_line):
                break
            section_lines.append(next_line)
        section_text = "\n".join(section_lines)
        if DASHBOARD_ASK_RESOLVED_RE.search(section_text):
            continue
        label = clean_plan_brief_text(m.group("body"), 220)
        if label:
            entries.append({"label": label, "line": index + 1})
    return entries if entries else extract_open_entries(text)


def read_ask_owner_entries(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    text, _ = redact_sensitive_text(text)
    return extract_ask_owner_entries(text)


# Back-compat aliases for older call sites / tests.
extract_ask_leo_entries = extract_ask_owner_entries
read_ask_leo_entries = read_ask_owner_entries


def extract_focus_tasks(text: str, limit: int = 3) -> list[dict]:
    body = section_body(text, "Tasks")
    if not body:
        return []
    tasks: list[dict] = []
    for m in PLAN_BRIEF_TASK_RE.finditer(body):
        label = clean_plan_brief_text(m.group("body"), 170)
        if not label:
            continue
        tasks.append({"status": m.group("status"), "label": label})
    order = {"in_progress": 0, "in_review": 1, "blocked": 2, "pending": 3, "completed": 4}
    tasks.sort(key=lambda item: order.get(item["status"], 9))
    return tasks[:limit]


def extract_latest_bullets(text: str, heading: str, limit: int = 1) -> list[str]:
    body = section_body(text, heading)
    if not body:
        return []
    bullets: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        if PLAN_BRIEF_TASK_RE.match(line):
            continue
        m = PLAN_BRIEF_BULLET_RE.match(line)
        if m:
            if current:
                bullets.append(clean_plan_brief_text(" ".join(current), 220))
            current = [m.group("body")]
        elif current and line.strip():
            current.append(line.strip())
    if current:
        bullets.append(clean_plan_brief_text(" ".join(current), 220))
    clean_bullets = [bullet for bullet in bullets if bullet]
    dated: list[tuple[date, int, str]] = []
    undated: list[tuple[int, str]] = []
    for index, bullet in enumerate(clean_bullets):
        match = re.match(r"^\[(\d{4}-\d{2}-\d{2})\]", bullet)
        if match:
            try:
                dated.append((date.fromisoformat(match.group(1)), index, bullet))
                continue
            except ValueError:
                pass
        undated.append((index, bullet))
    dated.sort(key=lambda item: (-item[0].toordinal(), item[1]))
    ordered = [item[2] for item in dated] + [item[1] for item in undated]
    return ordered[:limit]


def plan_state_label(stats: dict) -> str:
    counts = stats.get("counts") or {}
    total = int(stats.get("total") or 0)
    completed = int(counts.get("completed") or 0)
    if total and completed == total:
        return "shipped"
    if int(counts.get("blocked") or 0):
        return "blocked"
    if int(counts.get("in_review") or 0):
        return "in review"
    if int(counts.get("in_progress") or 0):
        return "in flight"
    if int(counts.get("pending") or 0):
        return "queued"
    return "no tasks"


def plan_brief(text: str, purpose: str, stats: dict, decision_log: dict) -> dict:
    counts = stats.get("counts") or {}
    total = int(stats.get("total") or 0)
    completed = int(counts.get("completed") or 0)
    latest_decision = ""
    recent_directions = decision_log.get("recent_directions") or []
    if recent_directions:
        latest = recent_directions[-1]
        latest_decision = clean_plan_brief_text(latest.get("body") or latest.get("raw") or "", 220)
    latest_progress = extract_latest_bullets(text, "Progress", 1)
    return {
        "summary": clean_plan_brief_text(purpose or "", 220),
        "state": plan_state_label(stats),
        "open_count": max(total - completed, 0),
        "focus_tasks": extract_focus_tasks(text, 3),
        "latest_progress": latest_progress[0] if latest_progress else "",
        "latest_decision": latest_decision,
    }


def decision_log_body(text: str) -> tuple[str, int | None]:
    """Return the Decision Log section body plus its 1-based heading line."""
    lines = text.splitlines()
    start_index = None
    start_level = None
    for i, line in enumerate(lines):
        m = DECISION_LOG_HEADING_RE.match(line)
        if not m:
            continue
        start_index = i
        start_level = len(m.group("marks"))
        break
    if start_index is None or start_level is None:
        return "", None

    body_lines: list[str] = []
    for line in lines[start_index + 1:]:
        hm = MARKDOWN_HEADING_RE.match(line)
        if hm and len(hm.group(1)) <= start_level:
            break
        body_lines.append(line)
    return "\n".join(body_lines).strip(), start_index + 1


def normalize_decision_entry(raw: str, index: int, line_number: int | None) -> dict:
    """Parse one Decision Log bullet into UI-friendly fields."""
    text = re.sub(r"\s+", " ", raw).strip()
    kind = "NOTE"
    m = DECISION_KIND_RE.match(text)
    if m:
        kind = m.group("kind").upper()
        text = m.group("rest").strip()

    date = ""
    dm = DECISION_DATE_RE.match(text)
    if dm:
        date = dm.group("date").strip()
        text = dm.group("rest").strip()

    body = text or raw.strip()
    return {
        "index": index,
        "line": line_number,
        "kind": kind,
        "date": date,
        "body": body,
        "raw": raw.strip(),
        "is_direction": kind in DECISION_DIRECTION_KINDS,
        "is_recent": False,
    }


def parse_decision_log(text: str) -> dict:
    """Extract Decision Log bullets as first-class read-only plan metadata."""
    body, heading_line = decision_log_body(text)
    entries: list[dict] = []
    if body:
        current: list[str] = []
        current_line: int | None = None
        base_line = (heading_line or 0) + 1
        for offset, line in enumerate(body.splitlines(), start=base_line):
            m = DECISION_ENTRY_RE.match(line)
            if m:
                if current:
                    entries.append(normalize_decision_entry(" ".join(current), len(entries), current_line))
                current = [m.group("body").strip()]
                current_line = offset
                continue
            if current and line.strip():
                current.append(line.strip())
        if current:
            entries.append(normalize_decision_entry(" ".join(current), len(entries), current_line))

    recent_indexes = {entry["index"] for entry in entries[-3:]}
    for entry in entries:
        entry["is_recent"] = entry["index"] in recent_indexes

    recent_directions = [entry for entry in entries if entry["is_direction"]][-3:]
    return {
        "present": heading_line is not None,
        "heading_line": heading_line,
        "count": len(entries),
        "entries": entries,
        "recent_directions": recent_directions,
    }


def discover_investigations(plan_dir: Path, plan_text: str) -> list[str]:
    """Auto-discover .md files under plan_dir/investigations/ + explicit refs.

    Canonical /vidux nesting: a parent task can carry [Investigation: <relpath>]
    pointing at a sub-plan. We surface BOTH the auto-discovered files AND any
    explicit refs from task lines (deduped by resolved path), to handle plans
    that drop investigations without linking them and plans that link without
    a directory.
    """
    found: set[str] = set()
    inv_dir = plan_dir / "investigations"
    if inv_dir.is_dir():
        for f in inv_dir.glob("*.md"):
            if f.is_file() and not has_sensitive_text(f.name):
                found.add(str(f.resolve()))
    for ref in INVESTIGATION_RE.findall(plan_text):
        rel = ref.strip().strip("`'\"")
        try:
            candidate = (plan_dir / rel).resolve()
            candidate.relative_to(plan_dir.resolve())
        except (OSError, ValueError):
            continue
        if (
            candidate.is_file()
            and candidate.suffix == ".md"
            and not has_sensitive_text(candidate.name)
        ):
            found.add(str(candidate))
    return sorted(found)


def evidence_label(path: Path) -> str:
    stem = path.stem.strip()
    if not stem:
        return path.name
    dated = re.match(r"^(\d{4}-\d{2}-\d{2})[-_](.+)$", stem)
    if dated:
        slug = re.sub(r"[-_]+", " ", dated.group(2)).strip()
        return f"{dated.group(1)} - {slug}" if slug else dated.group(1)
    return re.sub(r"[-_]+", " ", stem)


def discover_evidence(plan_dir: Path) -> list[dict]:
    """Discover markdown evidence files in chronological order.

    Canonical evidence names are `YYYY-MM-DD-<slug>.md`, but real plans
    accumulate hand-written receipts. Non-markdown files and nested directories
    are ignored; oddly named markdown is still surfaced after dated evidence
    with a readable label so the browser fails open for receipts, not the page.
    """
    evidence_dir = plan_dir / "evidence"
    if not evidence_dir.is_dir():
        return []
    items: list[dict] = []
    for path in evidence_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".md":
            continue
        if has_sensitive_text(path.name):
            continue
        st = path.stat()
        date_match = EVIDENCE_DATE_RE.match(path.name)
        items.append({
            "path": str(path.resolve()),
            "name": path.name,
            "label": evidence_label(path),
            "date": date_match.group(1) if date_match else "",
            "mtime": st.st_mtime,
            "size": st.st_size,
            "is_dated": bool(date_match),
        })
    items.sort(key=lambda item: (
        0 if item["is_dated"] else 1,
        item["date"] or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(item["mtime"])),
        item["name"].lower(),
    ))
    return items


def extract_purpose_from_text(text: str) -> str:
    """Pull the first non-heading paragraph under '## Purpose' from plan text."""
    # Strip leading Parent: metadata blockquote / bold line so it doesn't
    # leak into the sidebar purpose preview.
    text = re.sub(
        r"^(#[^\n]*\n+)?(?:>[ \t]*Parent:|\*\*Parent:\*\*)[^\n]*\n+",
        lambda m: m.group(1) or "",
        text,
        count=1,
    )
    m = re.search(r"##\s+Purpose\s*\n+([^\n#].+?)(?=\n\s*\n|\n##|\Z)", text, re.S)
    if not m:
        # Fall back to first non-heading paragraph after the title.
        m = re.search(r"^#[^\n]*\n+([^\n#].+?)(?=\n\s*\n|\n##|\Z)", text, re.S | re.M)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:240]


def extract_purpose(path: Path) -> str:
    """Compatibility wrapper for callers that only have a path."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return extract_purpose_from_text(text)


def safe_resolve(raw: str) -> Path | None:
    """Allow authority plans + canonical siblings + scoped evidence markdown.

    The whitelist is the read-only contract. node_modules paths are rejected
    even when the filename matches. The `investigations/` + `evidence/` rules
    are the canonical /vidux nesting per DOCTRINE.md + guides/investigation.md
    + guides/evidence-format.md — surfacing them is part of the viewer's job.
    """
    try:
        p = Path(raw).resolve()
    except (OSError, ValueError):
        return None
    try:
        p.relative_to(DEV_ROOT)
    except ValueError:
        return None
    if "node_modules" in p.parts:
        return None
    if not p.is_file():
        return None
    if p.name in ALLOWED_PLAN_FILES or is_repo_native_authority_path(p):
        return p
    if p.suffix == ".md" and ("investigations" in p.parts or "evidence" in p.parts):
        return p
    return None


def safe_resolve_any(raw: str) -> Path | None:
    """safe_resolve() OR an .html artifact under ARTIFACTS_DIR. Read-only either way."""
    p = safe_resolve(raw)
    if p:
        return p
    try:
        candidate = Path(raw).resolve()
    except (OSError, ValueError):
        return None
    try:
        candidate.relative_to(ARTIFACTS_DIR.resolve())
    except ValueError:
        return None
    if candidate.suffix.lower() != ".html":
        return None
    if not candidate.is_file():
        return None
    return candidate


def is_allowed_file_target(raw: str) -> bool:
    """Return True when a missing /api/file target would otherwise be allowed."""
    try:
        candidate = Path(raw).resolve(strict=False)
    except (OSError, ValueError):
        return False
    if "node_modules" in candidate.parts:
        return False
    try:
        candidate.relative_to(DEV_ROOT)
    except ValueError:
        pass
    else:
        if candidate.name in ALLOWED_PLAN_FILES or is_repo_native_authority_path(candidate):
            return True
        if candidate.suffix == ".md" and (
            "investigations" in candidate.parts or "evidence" in candidate.parts
        ):
            return True
    try:
        candidate.relative_to(ARTIFACTS_DIR.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return candidate.suffix.lower() == ".html"


def read_browser_file(path: Path) -> tuple[int, bytes | str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 404, f"file missing: {path.name}"
    except OSError as exc:
        return 500, f"file read failed: {exc}"
    redacted, _ = redact_sensitive_text(text)
    return 200, redacted.encode("utf-8")


def discover_artifacts() -> list[dict]:
    """List ad-hoc HTML artifacts in ARTIFACTS_DIR, newest first."""
    if not ARTIFACTS_DIR.is_dir():
        return []
    items: list[dict] = []
    for path in ARTIFACTS_DIR.glob("*.html"):
        if not path.is_file() or has_sensitive_text(str(path)):
            continue
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:4096]
        except OSError:
            head = ""
        head, _ = redact_sensitive_text(head)
        m = ARTIFACT_TITLE_RE.search(head)
        if m:
            raw_title = (m.group(1) or m.group(2) or "").strip()
            title = raw_title or path.stem
        else:
            title = path.stem
        st = path.stat()
        age_days = (time.time() - st.st_mtime) / 86400
        items.append({
            "slug": path.stem,
            "title": title[:200],
            "path": str(path),
            "size": st.st_size,
            "mtime": st.st_mtime,
            "age_days": round(age_days, 1),
        })
    items.sort(key=lambda a: -a["mtime"])
    return items


def write_artifact(slug: str, html: str) -> tuple[bool, str]:
    """Write an artifact. Returns (ok, message)."""
    if not ARTIFACT_SLUG_RE.match(slug):
        return False, "slug must match [a-z0-9][a-z0-9-]{0,63}"
    if has_sensitive_text(slug):
        return False, "artifact contains sensitive content"
    if len(html.encode("utf-8")) > ARTIFACT_MAX_BYTES:
        return False, f"html exceeds {ARTIFACT_MAX_BYTES} bytes"
    if has_sensitive_text(html):
        return False, "artifact contains sensitive content"
    try:
        path = ARTIFACTS_DIR / f"{slug}.html"
        atomic_write_text(path, html)
    except UnsafeFileAliasError:
        return False, "write target must be a regular single-link file"
    except OSError as e:
        return False, f"write failed: {e}"
    return True, str(path)


def is_loopback_host(host: str) -> bool:
    return host in LOOPBACK_HOSTS


def request_host_hostname(host: str) -> str:
    """Hostname portion of a Host header, tolerating IPv6 literals like [::1]:7191."""
    netloc = (host or "").strip().lower()
    if not netloc:
        return ""
    if netloc.startswith("["):
        end = netloc.find("]")
        return netloc[: end + 1] if end != -1 else netloc
    return netloc.rsplit(":", 1)[0] if ":" in netloc else netloc


def is_private_lan_ip_literal(hostname: str) -> bool:
    """True when hostname is a raw private-use (RFC 1918 / RFC 4193) IP literal.

    DNS rebinding always presents Host as the attacker's registered domain
    name (that's what the browser's address bar held) -- never as a raw IP
    literal, since there is no reason for an attacker to own a private-range
    IP. A genuine LAN device is reached by IP on a home network (no local DNS
    entry for the vidux server), so requiring a private-IP literal here
    accepts real LAN peers while rejecting a rebound domain outright.
    """
    text = hostname.strip("[]")
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return False
    if addr.version == 4:
        return any(
            addr in network
            for network in (
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"),
            )
        )
    return addr in ipaddress.ip_network("fc00::/7")


def is_allowed_request_host(host: str, bind_host: str) -> bool:
    """Reject requests whose Host header isn't a recognized loopback identity.

    Origin/Referer-must-match-Host (origin_matches_host) does not stop DNS
    rebinding: a rebound page's browser sends a Host header and an Origin
    header that agree with EACH OTHER (both reflect the attacker's domain),
    so that check passes even though the TCP connection actually lands on
    this loopback server. An independent Host allowlist is required because
    a rebound domain can never legitimately present as "127.0.0.1"/"localhost".

    Wildcard bind mode is still an allowlist: loopback identities and private
    IP literals are accepted, while domain names remain denied. Otherwise a
    DNS-rebound domain could read every plan/proof API from a LAN-bound server.
    Writes stay loopback-gated separately via client_address, except for the
    narrower private-LAN comment route.
    """
    hostname = request_host_hostname(host)
    if not hostname:
        return False
    allowed = {"127.0.0.1", "localhost", "[::1]", "::1"}
    if hostname in allowed:
        return True
    if bind_host in ("0.0.0.0", "::"):
        return is_private_lan_ip_literal(hostname)
    return hostname.strip("[]") == bind_host.strip().strip("[]").lower()


def is_json_content_type(value: str | None) -> bool:
    return (value or "").split(";", 1)[0].strip().lower() == JSON_CONTENT_TYPE


def origin_matches_host(raw: str, host: str) -> bool:
    if not raw or raw == "null" or not host:
        return False
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    return parsed.netloc.lower() == host.lower()


def clean_note_label(raw: object, default: str) -> str:
    text = str(raw or default).strip()
    text = PLAN_NOTE_SOURCE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return (text or default)[:120]


def clean_comment_author(raw: object) -> str:
    text = str(raw or "").strip()
    text = COMMENT_AUTHOR_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return (text or "Anonymous")[:COMMENT_AUTHOR_MAX_CHARS]


def clean_comment_anchor_text(raw: object, limit: int) -> str:
    text = str(raw or "").strip()
    text = COMMENT_ANCHOR_CONTROL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def clean_comment_anchor(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    anchor: dict[str, object] = {"version": 1}
    for key, limit in COMMENT_ANCHOR_FIELD_LIMITS.items():
        value = clean_comment_anchor_text(raw.get(key), limit)
        if value:
            anchor[key] = value
    if "index" in raw:
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            index = None
        if index is not None and 0 <= index <= 100_000:
            anchor["index"] = index
    return anchor if len(anchor) > 1 else None


def comment_target_kind(path: Path) -> str:
    try:
        path.relative_to(ARTIFACTS_DIR.resolve())
    except ValueError:
        return "plan"
    return "artifact"


def append_comment(
    target_path: Path,
    author: object,
    body: str,
    remote_address: str,
    anchor: object = None,
) -> tuple[bool, str | dict]:
    text = body.strip()
    if not text:
        return False, "comment must be non-empty"
    if len(text.encode("utf-8")) > COMMENT_BODY_MAX_BYTES:
        return False, f"comment exceeds {COMMENT_BODY_MAX_BYTES} bytes"
    if (
        has_sensitive_text(str(target_path))
        or has_sensitive_text(text)
        or has_sensitive_text(str(author or ""))
    ):
        return False, "comment contains sensitive content"
    if anchor is not None and has_sensitive_text(json.dumps(anchor, default=str)):
        return False, "comment contains sensitive content"

    record = {
        "id": str(uuid.uuid4()),
        "target_path": str(target_path),
        "target_kind": comment_target_kind(target_path),
        "author": clean_comment_author(author),
        "body": text,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "remote_address": remote_address,
    }
    clean_anchor = clean_comment_anchor(anchor)
    if clean_anchor:
        record["anchor"] = clean_anchor

    try:
        with _comments_write_guard():
            try:
                existing = read_text(COMMENTS_FILE, errors="replace")
            except FileNotFoundError:
                existing = ""
            atomic_write_text(
                COMMENTS_FILE,
                existing + json.dumps(record, separators=(",", ":")) + "\n",
            )
    except UnsafeFileAliasError:
        return False, "write target must be a regular single-link file"
    except OSError as e:
        return False, f"write failed: {e}"
    return True, record


def read_comments(target_path: Path, limit: int = 100) -> list[dict]:
    target = str(target_path)
    comments: list[dict] = []
    try:
        for line in read_text(COMMENTS_FILE, errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("target_path") == target:
                comments.append(redact_sensitive_value(item))
    except OSError:
        return []
    return comments[-limit:]


def resolve_plan_note_target(raw: str) -> Path | None:
    p = safe_resolve(raw)
    if not p or not is_authority_plan_name(p.name):
        return None
    return p


def write_plan_note(
    plan_path: Path,
    note: str,
    source: str = "vidux-browse-local",
    agent: str = "",
) -> tuple[bool, str]:
    """Append a local note to the plan directory's INBOX.md."""
    body = note.strip()
    if not body:
        return False, "note must be non-empty"
    if len(body.encode("utf-8")) > PLAN_NOTE_MAX_BYTES:
        return False, f"note exceeds {PLAN_NOTE_MAX_BYTES} bytes"
    if has_sensitive_text(body) or has_sensitive_text(f"{source}\n{agent}"):
        return False, "note contains sensitive content"

    source = clean_note_label(source, "vidux-browse-local")
    agent = clean_note_label(agent, "") if agent else ""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    title = re.sub(r"\s+", " ", body.splitlines()[0]).strip()[:96]
    inbox = plan_path.parent / "INBOX.md"
    quote = "\n".join(f"> {line}" if line else ">" for line in body.splitlines())
    lines = [
        f"### {stamp} - {title}",
        f"- Source: {source}",
    ]
    if agent:
        lines.append(f"- Agent: {agent}")
    entry = "\n".join(lines) + "\n\n" + quote + "\n\n"

    try:
        with _PLAN_NOTE_WRITE_LOCK:
            try:
                text = read_text(inbox)
            except FileNotFoundError:
                text = f"# {plan_path.parent.name} Inbox\n\n## Open\n\n## Processed\n"

            marker = re.search(r"(^## Open\s*\n)", text, re.M)
            if marker:
                insert_at = marker.end()
                text = text[:insert_at] + "\n" + entry + text[insert_at:]
            else:
                text = text.rstrip() + "\n\n## Open\n\n" + entry

            atomic_write_text(inbox, text)
    except UnsafeFileAliasError:
        return False, "write target must be a regular single-link file"
    except UnicodeDecodeError:
        return False, "read failed: INBOX.md is not valid UTF-8"
    except OSError as e:
        return False, f"write failed: {e}"
    return True, str(inbox)


def steering_mailbox() -> SteeringMailbox:
    """Bind the provider-neutral mailbox to this server's live root and policy."""
    return SteeringMailbox(
        STEERING_FILE,
        dev_root=DEV_ROOT,
        sensitive_check=has_sensitive_text,
    )


def coordination_claims() -> CoordinationClaims:
    """Bind the read-only browser projection to the provider-neutral claims journal."""
    return CoordinationClaims(CLAIMS_FILE)


def coordination_store_id() -> str:
    """Path-safe coordination-store identity used by launcher reuse checks."""
    resolved = str(CLAIMS_FILE.expanduser().resolve(strict=False))
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def coordination_module_mtime_ns() -> int:
    return COORDINATION_MODULE_MTIME_NS


def coordination_http_item(item: dict) -> dict:
    """Keep only public work, lease, checkpoint, and resume fields."""
    payload = {
        field: item[field]
        for field in (
            "claim_id", "repo", "claim", "owner", "lane", "plan_path", "task_id",
            "claimed_at", "last_heartbeat_at", "expires_at", "state", "checkpoint",
            "release_status", "released_at", "takeover_of", "taken_over_by",
        )
        if field in item
    }
    status = item.get("release_status")
    if status:
        payload["status"] = status
    elif item.get("state") == "expired":
        payload["status"] = "expired"
    return payload


def steering_store_id() -> str:
    """Path-safe listener identity used by the launcher reuse check."""
    resolved = str(STEERING_FILE.expanduser().resolve(strict=False))
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def steering_module_mtime_ns() -> int:
    return STEERING_MODULE_MTIME_NS


def steering_http_item(item: dict) -> dict:
    """Return the cockpit-safe shape: no plan/store path, source, consumer, or token."""
    payload = {
        "id": item.get("id", ""),
        "message": item.get("body", ""),
        "status": item.get("state", "failed"),
        "created_at": item.get("created_at", ""),
        "attempts": item.get("attempts", 0),
    }
    for field in ("claimed_at", "lease_expires_at", "failure_code", "updated_at"):
        if item.get(field):
            payload[field] = item[field]
    return payload


def steering_item_belongs_to_plan(
    mailbox: SteeringMailbox,
    plan_path: Path,
    item_id: str,
) -> bool:
    snapshot = mailbox.read_mailbox(plan_path=plan_path)
    if not snapshot.get("ok"):
        raise SteeringJournalCorruptError("steering journal needs local repair")
    return any(item.get("id") == item_id for item in snapshot.get("items", []))


class Handler(BaseHTTPRequestHandler):
    server_version = "viduxBrowser/0.1"

    def log_message(self, fmt, *args):  # noqa: N802 — stdlib override
        # Decode percent-escaped request targets before scanning; otherwise a
        # preceding `%2F` can make its trailing `F` defeat token boundaries.
        message, _ = redact_sensitive_text(unquote(fmt % args))
        # Keep each request on one physical log line after decoding so encoded
        # control characters cannot forge a second entry.
        message = re.sub(r"[\x00-\x1f\x7f]+", " ", message).strip()
        sys.stderr.write(f"[{self.log_date_time_string()}] {message}\n")

    def do_GET(self):  # noqa: N802 — stdlib override
        if not self._host_header_ok():
            return
        url = urlparse(self.path)
        route = url.path
        qs = parse_qs(url.query)
        if route == "/" or route == "/index.html":
            self._serve_static("index.html", "text/html; charset=utf-8")
        elif route.startswith("/static/"):
            name = route[len("/static/"):]
            self._serve_static(name)
        elif route == "/api/health":
            self._json({"ok": True, "dev_root": str(DEV_ROOT), "port": PORT,
                        "repo_root": str(VIDUX_ROOT),
                        "server_path": str(SERVER_FILE),
                        "server_mtime_ns": SERVER_MTIME_NS,
                        "steering_store_id": steering_store_id(),
                        "steering_module_mtime_ns": steering_module_mtime_ns(),
                        "coordination_store_id": coordination_store_id(),
                        "coordination_module_mtime_ns": coordination_module_mtime_ns(),
                        "artifacts_dir": str(ARTIFACTS_DIR)})
        elif route == "/api/plans":
            plans = discover_plans_cached()
            self._json({
                "plans": plan_list_payload(plans),
                "summary": build_fleet_summary(plans),
                "dashboard": build_dashboard(plans),
                "dev_root": str(DEV_ROOT),
            })
        elif route == "/api/artifacts":
            self._json({"artifacts": discover_artifacts(),
                        "artifacts_dir": str(ARTIFACTS_DIR)})
        elif route == "/api/vidux/truth":
            refresh = (qs.get("refresh") or [""])[0]
            self._json(
                vidux_truth_payload(force_refresh=True)
                if refresh == "sync"
                else vidux_truth_cached_payload()
            )
        elif route == "/api/ledger":
            raw = (qs.get("path") or [""])[0]
            plan_path = resolve_ledger_plan_target(raw)
            if not plan_path:
                self._send(403, "forbidden")
                return
            self._json(ledger_payload_for_plan(plan_path))
        elif route == "/api/coordination":
            if not self._require_coordination_read():
                return
            raw = (qs.get("plan_path") or [""])[0]
            plan_path = resolve_plan_note_target(raw)
            if not plan_path:
                self._send(403, "plan_path must be an allowed PLAN.md under dev_root")
                return
            try:
                # Filter inside the store before applying its handoff limit so
                # busy unrelated plans cannot evict this plan's resume rows.
                snapshot = coordination_claims().snapshot(
                    plan_path=str(plan_path),
                    handoff_limit=16,
                )
            except (ClaimsError, UnsafeFileAliasError, UnicodeError, OSError):
                self._send(409, "local coordination state is unavailable")
                return
            exact_plan = str(plan_path)
            active = [
                coordination_http_item(item)
                for item in snapshot.get("claims", [])
                if item.get("plan_path") == exact_plan
            ][:64]
            handoffs = [
                coordination_http_item(item)
                for item in snapshot.get("handoffs", [])
                if item.get("plan_path") == exact_plan
            ][:16]
            self._json({"ok": True, "active": active, "handoffs": handoffs})
        elif route == "/api/steering":
            if not self._require_steering_read():
                return
            raw = (qs.get("plan_path") or [""])[0]
            plan_path = resolve_plan_note_target(raw)
            if not plan_path:
                self._send(403, "plan_path must be an allowed PLAN.md under dev_root")
                return
            try:
                snapshot = steering_mailbox().read_mailbox(plan_path=plan_path)
            except (SteeringMailboxError, UnsafeFileAliasError, OSError):
                self._send(409, "local steering state is unavailable")
                return
            if not snapshot.get("ok"):
                # A partial journal prefix is useful to a local repair tool but
                # must never become an apparently-authoritative browser queue.
                self._send(409, "local steering state needs repair")
                return
            self._json({
                "ok": True,
                "capacity": STEERING_CAPACITY,
                "items": [
                    steering_http_item(item)
                    for item in snapshot.get("items", [])
                ],
            })
        elif route == "/api/comments":
            raw = (qs.get("path") or [""])[0]
            p = safe_resolve_any(raw)
            if not p:
                self._send(403, "forbidden")
                return
            self._json({
                "ok": True,
                "path": str(p),
                "target_kind": comment_target_kind(p),
                "comments": read_comments(p),
            })
        elif route == "/api/file":
            raw = (qs.get("path") or [""])[0]
            p = safe_resolve_any(raw)  # plans + artifacts
            if not p:
                if is_allowed_file_target(raw):
                    self._send(404, f"file missing: {Path(raw).name}")
                    return
                self._send(403, "forbidden")
                return
            ctype = ("text/html; charset=utf-8" if p.suffix.lower() == ".html"
                     else "text/markdown; charset=utf-8")
            status, body = read_browser_file(p)
            if status != 200:
                self._send(status, body if isinstance(body, str) else "file read failed")
                return
            self._send_with_type(
                body,
                ctype,
                extra_headers=(
                    ARTIFACT_SECURITY_HEADERS
                    if p.suffix.lower() == ".html"
                    else None
                ),
            )
        else:
            self._send(404, "not found")

    def do_HEAD(self):  # noqa: N802 — stdlib override
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    def do_POST(self):  # noqa: N802 — stdlib override
        if not self._host_header_ok():
            return
        url = urlparse(self.path)
        if url.path == "/api/artifact":
            if not self._require_json_write():
                return
            length = self._content_length()
            if length is None:
                return
            if length <= 0 or length > ARTIFACT_MAX_BYTES + 1024:
                self._send(400, "missing or oversized body")
                return
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as e:
                self._send(400, f"bad json: {e}")
                return
            slug = str(payload.get("slug", "")).strip()
            html = payload.get("html", "")
            if not isinstance(html, str):
                self._send(400, "html must be a string")
                return
            ok, msg = write_artifact(slug, html)
            if not ok:
                self._send(400, msg)
                return
            self._json({"ok": True, "slug": slug, "path": msg})
        elif url.path == "/api/local-plan-note":
            if not self._require_json_write():
                return
            length = self._content_length()
            if length is None:
                return
            if length <= 0 or length > PLAN_NOTE_MAX_BYTES + 2048:
                self._send(400, "missing or oversized body")
                return
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as e:
                self._send(400, f"bad json: {e}")
                return
            plan_path = resolve_plan_note_target(str(payload.get("plan_path", "")))
            if not plan_path:
                self._send(403, "plan_path must be an allowed PLAN.md under dev_root")
                return
            note = payload.get("note", "")
            if not isinstance(note, str):
                self._send(400, "note must be a string")
                return
            ok, msg = write_plan_note(
                plan_path,
                note,
                source=str(payload.get("source", "vidux-browse-local")),
                agent=str(payload.get("agent", "")),
            )
            if not ok:
                self._send(400, msg)
                return
            self._json({"ok": True, "path": msg})
        elif url.path == "/api/steering":
            if not self._require_json_write():
                return
            length = self._content_length()
            if length is None:
                return
            if length <= 0 or length > STEERING_HTTP_MAX_BYTES:
                self._send(400, "missing or oversized body")
                return
            try:
                raw = self.rfile.read(length).decode("utf-8")
            except UnicodeDecodeError:
                self._send(400, "body must be valid UTF-8")
                return
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as e:
                self._send(400, f"bad json: {e}")
                return
            if not isinstance(payload, dict):
                self._send(400, "payload must be an object")
                return
            plan_path = resolve_plan_note_target(str(payload.get("plan_path", "")))
            if not plan_path:
                self._send(403, "plan_path must be an allowed PLAN.md under dev_root")
                return
            action = payload.get("action")
            if not isinstance(action, str) or action not in {"enqueue", "retry", "dismiss"}:
                self._send(400, "action must be enqueue, retry, or dismiss")
                return
            mailbox = steering_mailbox()
            try:
                if action == "enqueue":
                    message = payload.get("message", "")
                    if not isinstance(message, str):
                        self._send(400, "message must be a string")
                        return
                    item = mailbox.enqueue_intent(
                        plan_path,
                        message,
                        source=payload.get("source", ""),
                    )
                    self._json({"ok": True, "item": steering_http_item(item)})
                    return

                item_id = payload.get("id", "")
                if not isinstance(item_id, str):
                    self._send(400, "id must be a string")
                    return
                if not steering_item_belongs_to_plan(mailbox, plan_path, item_id):
                    self._send(403, "steering item does not belong to this plan")
                    return
                if action == "retry":
                    item = mailbox.retry_intent(item_id)
                    self._json({"ok": True, "item": steering_http_item(item)})
                else:
                    mailbox.dismiss_intent(item_id)
                    self._json({"ok": True})
            except SteeringJournalCorruptError:
                self._send(409, "local steering state needs repair")
            except SteeringMailboxConflictError as e:
                self._send(409, str(e))
            except SteeringMailboxValidationError as e:
                self._send(400, str(e))
            except UnsafeFileAliasError:
                self._send(400, "steering store must be a regular single-link file")
            except OSError:
                self._send(409, "local steering state is unavailable")
        elif url.path == "/api/comments":
            if not self._require_comment_write():
                return
            length = self._content_length()
            if length is None:
                return
            if length <= 0 or length > COMMENT_BODY_MAX_BYTES + 2048:
                self._send(400, "missing or oversized body")
                return
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as e:
                self._send(400, f"bad json: {e}")
                return
            target_path = safe_resolve_any(str(payload.get("target_path", "")))
            if not target_path:
                self._send(403, "target_path must be an allowed plan file or artifact")
                return
            body = payload.get("body", "")
            if not isinstance(body, str):
                self._send(400, "body must be a string")
                return
            ok, result = append_comment(
                target_path,
                payload.get("author", ""),
                body,
                self.client_address[0],
                anchor=payload.get("anchor"),
            )
            if not ok:
                self._send(400, str(result))
                return
            self._json({"ok": True, "comment": result})
        else:
            self._send(404, "not found")

    def _host_header_ok(self) -> bool:
        if is_allowed_request_host(self.headers.get("Host") or "", HOST):
            return True
        self._send(403, "Host header not recognized")
        return False

    def _require_steering_read(self) -> bool:
        if not is_loopback_host(self.client_address[0]):
            self._send(403, "steering requires loopback client")
            return False
        return True

    def _require_coordination_read(self) -> bool:
        if not is_loopback_host(self.client_address[0]):
            self._send(403, "coordination requires loopback client")
            return False
        return True

    def _require_json_write(self) -> bool:
        if not is_loopback_host(self.client_address[0]):
            self._send(403, "write endpoints require loopback client")
            return False
        # this previously allowed the request through
        # when BOTH Origin and Referer were absent (require_origin=False),
        # unlike /api/comments which already requires one. Not exploitable
        # from a real browser today (a JSON POST is preflighted, and every
        # real cross/same-origin browser POST attaches Origin), but a
        # process that can already reach loopback directly (curl, a local
        # binary) shouldn't get a free pass either -- defense-in-depth,
        # matching what _require_comment_write() already does.
        return self._require_browser_json(require_origin=True)

    def _require_comment_write(self) -> bool:
        """/api/comments is the one write route documented for real LAN peers.
        Unlike every other write route it cannot require only
        is_loopback_host(client_address). Accept the real TCP loopback peer
        (matching every other write route) OR, only in documented LAN-bind
        mode, a request whose real TCP peer AND Host header are both
        private-use IP literals (never
        what a DNS-rebound page's Host header looks like -- that's always the
        attacker's own registered domain name, not a raw private IP)."""
        if not is_loopback_host(self.client_address[0]):
            host = request_host_hostname(self.headers.get("Host") or "")
            if not (
                HOST in ("0.0.0.0", "::")
                and is_private_lan_ip_literal(self.client_address[0])
                and is_private_lan_ip_literal(host)
            ):
                self._send(403, "comments require a loopback or private-LAN client")
                return False
        return self._require_browser_json(require_origin=True)

    def _require_browser_json(self, require_origin: bool = False) -> bool:
        if not is_json_content_type(self.headers.get("Content-Type")):
            self._send(415, "Content-Type must be application/json")
            return False
        ok, reason = self._same_origin_ok(require_origin=require_origin)
        if not ok:
            self._send(403, reason)
            return False
        return True

    def _same_origin_ok(self, require_origin: bool = False) -> tuple[bool, str]:
        host = (self.headers.get("Host") or "").strip()
        origin = (self.headers.get("Origin") or "").strip()
        referer = (self.headers.get("Referer") or "").strip()
        if origin:
            if origin_matches_host(origin, host):
                return True, ""
            return False, "Origin must match vidux-browse host"
        if referer:
            if origin_matches_host(referer, host):
                return True, ""
            return False, "Referer must match vidux-browse host"
        if require_origin:
            return False, "Origin or Referer required"
        return True, ""

    def _content_length(self) -> int | None:
        """Parse the Content-Length header, sending a 400 and returning None
        on anything non-numeric (e.g. a hand-crafted "abc" or "1;2" header)
        instead of letting int() raise and crash the request out from under
        the handler with no response sent."""
        raw = self.headers.get("Content-Length", "0")
        try:
            return int(raw)
        except ValueError:
            self._send(400, "invalid Content-Length header")
            return None

    def _serve_static(self, name: str, ctype: str | None = None):
        if not name:
            self._send(404, "not found")
            return
        try:
            candidate = (STATIC_DIR / name).resolve()
            candidate.relative_to(STATIC_DIR.resolve())
        except (OSError, ValueError):
            self._send(404, "not found")
            return
        if not candidate.is_file():
            self._send(404, f"static asset missing: {name}")
            return
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype or guess_content_type(candidate.name))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self._write_body(body)

    def _write_body(self, body: bytes) -> bool:
        if getattr(self, "_head_only", False):
            return True
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return False
        return True

    def _json(self, payload):
        body = json.dumps(redact_sensitive_value(payload), indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self._write_body(body)

    def _send_with_type(
        self,
        body: bytes,
        ctype: str,
        extra_headers: dict[str, str] | None = None,
    ):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self._write_body(body)

    def _send_text(self, text: str):
        safe_text, _ = redact_sensitive_text(text)
        body = safe_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self._write_body(body)

    def _send(self, code: int, msg: str):
        safe_message, _ = redact_sensitive_text(msg)
        body = safe_message.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._write_body(body)


def guess_content_type(name: str) -> str:
    if name.endswith(".html"):
        return "text/html; charset=utf-8"
    if name.endswith(".css"):
        return "text/css; charset=utf-8"
    if name.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if name.endswith(".json"):
        return "application/json; charset=utf-8"
    if name.endswith(".svg"):
        return "image/svg+xml"
    return "application/octet-stream"


def main(argv=None):
    """Entry point. CLI flags override env defaults so test harnesses and
    Playwright `webServer` can launch the server hermetically against a
    fixture root + ephemeral port without mutating the user's shell env."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="vidux browser",
        description="Plan + artifact viewer for /vidux fleets. LAN-safe (loopback default).",
    )
    parser.add_argument(
        "--root",
        type=str,
        default=None,
        help="Dev-root directory to scan for PLAN.md files. Defaults to env "
             "VIDUX_DEV_ROOT or ~/Development.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind. Defaults to env VIDUX_BROWSER_PORT or 7191.",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host to bind. Defaults to env VIDUX_BROWSER_HOST or 127.0.0.1. "
             "Use 0.0.0.0 only for trusted-LAN read access, then open the "
             "server by private IP address (domain Host values are rejected).",
    )
    parser.add_argument(
        "--comments-path",
        type=str,
        default=None,
        help="Path to comments JSONL file. Defaults to env "
             "VIDUX_BROWSER_COMMENTS_FILE or ~/.vidux-browser/comments.jsonl.",
    )
    parser.add_argument(
        "--steering-path",
        type=str,
        default=None,
        help="Path to the one-shot steering JSONL journal. Defaults to env "
             "VIDUX_BROWSER_STEERING_FILE or ~/.vidux-browser/steering.jsonl.",
    )
    parser.add_argument(
        "--claims-path",
        type=str,
        default=None,
        help="Path to the work-claims JSONL journal. Defaults to env "
             "VIDUX_CLAIMS_FILE or ~/.agent-ledger/claims.jsonl.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=str,
        default=None,
        help="Directory the Artifacts panel reads/writes. Defaults to env "
             "VIDUX_BROWSER_ARTIFACTS_DIR or <this checkout>/browser/artifacts "
             "-- NOT scoped by --root, so pass this explicitly for hermetic "
             "test/demo runs against a fixture root.",
    )
    args = parser.parse_args(argv)

    # CLI overrides module-level globals. Re-resolve so the server uses the
    # passed values rather than the env defaults captured at import time.
    global HOST, PORT, DEV_ROOT, COMMENTS_FILE, STEERING_FILE, CLAIMS_FILE, ARTIFACTS_DIR
    if args.host is not None:
        HOST = args.host
    if args.port is not None:
        PORT = args.port
    if args.root is not None:
        DEV_ROOT = Path(args.root).expanduser().resolve()
    if args.comments_path is not None:
        COMMENTS_FILE = Path(args.comments_path).expanduser()
    if args.steering_path is not None:
        STEERING_FILE = Path(args.steering_path).expanduser()
    if args.claims_path is not None:
        CLAIMS_FILE = Path(args.claims_path).expanduser()
    if args.artifacts_dir is not None:
        ARTIFACTS_DIR = Path(args.artifacts_dir).expanduser().resolve()

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    sys.stderr.write(f"vidux browser → {url}  (dev_root={DEV_ROOT})\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nstopped\n")
        server.server_close()


if __name__ == "__main__":
    main()
