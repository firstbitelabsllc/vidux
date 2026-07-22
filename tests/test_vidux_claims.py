"""Tests for scripts/vidux-claims.py."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "vidux-claims.py"

spec = importlib.util.spec_from_file_location("vidux_claims", SCRIPT)
assert spec is not None
claims = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = claims
spec.loader.exec_module(claims)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _json(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def _claim_args(claims_file: str, *, owner: str = "codex-a") -> list[str]:
    return [
        "--claims-file",
        claims_file,
        "claim",
        "--repo",
        "vidux",
        "--claim",
        "PLAN.md",
        "--owner",
        owner,
        "--lane",
        f"lane-{owner}",
        "--plan-path",
        "PLAN.md",
        "--task-id",
        "T4",
    ]


def _legacy_claim(
    ts: str,
    *,
    plan_path: str = "/tmp/legacy.plan.md",
    row_id: str = "legacy-row",
    agent_id: str = "legacy-agent",
    expected_ship_by: str = "",
) -> dict:
    return {
        "ts": ts,
        "event": "claim",
        "agent_id": agent_id,
        "plan_path": plan_path,
        "row_id": row_id,
        "expected_ship_by": expected_ship_by,
    }


def _legacy_release(
    ts: str,
    *,
    plan_path: str = "/tmp/legacy.plan.md",
    row_id: str = "legacy-row",
    agent_id: str = "legacy-agent",
    status: str = "shipped",
) -> dict:
    return {
        "ts": ts,
        "event": "release",
        "agent_id": agent_id,
        "plan_path": plan_path,
        "row_id": row_id,
        "status": status,
    }


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _assert_private_process_fields_absent(test: unittest.TestCase, value: object) -> None:
    if isinstance(value, dict):
        test.assertNotIn("host", value)
        test.assertNotIn("pid", value)
        for child in value.values():
            _assert_private_process_fields_absent(test, child)
    elif isinstance(value, list):
        for child in value:
            _assert_private_process_fields_absent(test, child)


class ViduxClaimsTests(unittest.TestCase):
    def test_terminal_legacy_claims_bus_rows_are_read_without_mutation(self) -> None:
        now = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            _write_rows(
                path,
                [
                    _legacy_release("2000-01-01T00:00:00Z", row_id="old-row"),
                    _legacy_claim("2026-07-15T12:00:00Z"),
                    _legacy_release("2026-07-15T12:00:00Z"),
                ],
            )
            original = path.read_bytes()
            store = claims.CoordinationClaims(path)

            snapshot = store.snapshot(now=now)

            self.assertEqual(snapshot["claims"], [])
            self.assertEqual(snapshot["handoffs"], [])
            self.assertEqual(path.read_bytes(), original)

            claimed = store.claim(
                claim_id="clm_legacycompat",
                repo="vidux",
                claim="browser/coordination_claims.py",
                owner="codex-a",
                lane="coordination",
                plan_path="PLAN.md",
                task_id="6.0.9",
                now=now,
            )
            self.assertEqual(claimed["status"], "claimed")

    def test_active_legacy_claims_bus_claim_fails_closed_without_mutation(self) -> None:
        now = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            _write_rows(
                path,
                [
                    _legacy_claim("2026-07-15T11:59:00Z"),
                    # The retired bus chose the latest timestamp, not the
                    # final physical line. An older appended release must not
                    # hide the newer active claim.
                    _legacy_release("2026-07-15T11:58:00Z"),
                ],
            )
            original = path.read_bytes()

            with self.assertRaisesRegex(
                claims.ClaimsJournalError,
                "active legacy claims-bus claim cannot be safely projected",
            ):
                claims.CoordinationClaims(path).snapshot(now=now)

            self.assertEqual(path.read_bytes(), original)

    def test_legacy_relative_release_reconciles_unique_same_owner_claim(self) -> None:
        now = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            _write_rows(
                path,
                [
                    _legacy_claim(
                        "2026-07-15T11:59:00Z",
                        plan_path="/repo/acme-ios/PLAN.md",
                        row_id="XCODEBUILD",
                    ),
                    _legacy_release(
                        "2026-07-15T12:00:00Z",
                        plan_path="PLAN.md",
                        row_id="XCODEBUILD",
                    ),
                ],
            )

            snapshot = claims.CoordinationClaims(path).snapshot(now=now)

            self.assertEqual(snapshot["claims"], [])
            self.assertEqual(snapshot["handoffs"], [])

    def test_legacy_relative_release_does_not_cross_owner_or_ambiguity(self) -> None:
        now = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
        cases = (
            [
                _legacy_claim("2026-07-15T11:59:00Z", plan_path="/one/PLAN.md"),
                _legacy_release(
                    "2026-07-15T12:00:00Z", plan_path="PLAN.md", agent_id="other"
                ),
            ],
            [
                _legacy_claim("2026-07-15T11:59:00Z", plan_path="/one/PLAN.md"),
                _legacy_claim("2026-07-15T11:59:00Z", plan_path="/two/PLAN.md"),
                _legacy_release("2026-07-15T12:00:00Z", plan_path="PLAN.md"),
            ],
        )
        for rows in cases:
            with self.subTest(rows=rows), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "claims.jsonl"
                _write_rows(path, rows)
                with self.assertRaisesRegex(
                    claims.ClaimsJournalError,
                    "active legacy claims-bus claim cannot be safely projected",
                ):
                    claims.CoordinationClaims(path).snapshot(now=now)

    def test_legacy_terminal_marker_does_not_close_another_owners_claim(self) -> None:
        now = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            _write_rows(
                path,
                [
                    _legacy_claim(
                        "2026-07-15T11:59:00Z",
                        plan_path="/repo/PLAN.md",
                        row_id="same-row",
                        agent_id="owner-a",
                    ),
                    _legacy_release(
                        "2026-07-15T12:00:00Z",
                        plan_path="/repo/PLAN.md",
                        row_id="same-row",
                        agent_id="owner-b",
                    ),
                ],
            )

            with self.assertRaisesRegex(
                claims.ClaimsJournalError,
                "active legacy claims-bus claim cannot be safely projected",
            ):
                claims.CoordinationClaims(path).snapshot(now=now)

    def test_expired_legacy_claims_bus_claim_is_ignored(self) -> None:
        now = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            _write_rows(
                path,
                [_legacy_claim("2026-07-15T09:59:00Z")],
            )

            snapshot = claims.CoordinationClaims(path).snapshot(now=now)

            self.assertEqual(snapshot["claims"], [])
            self.assertEqual(snapshot["handoffs"], [])

    def test_legacy_markers_do_not_change_v1_or_v2_claim_projection(self) -> None:
        now = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
        base_claim = {
            "event": "claim",
            "ts": "2026-07-15T11:00:00Z",
            "repo": "vidux",
            "claim": "PLAN.md",
            "files_claimed": ["PLAN.md"],
            "owner": "codex-a",
            "lane": "coordination",
            "plan_path": "PLAN.md",
            "task_id": "6.0.9",
            "ttl_hours": 2,
            "expires_at": "2026-07-15T13:00:00Z",
        }
        v1_claim = {**base_claim, "claim_id": "clm_v1compat"}
        v2_claim = {
            **base_claim,
            "schema": 2,
            "claim_id": "clm_v2compat",
            "claim": "browser/coordination_claims.py",
            "files_claimed": ["browser/coordination_claims.py"],
            "owner": "codex-b",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            _write_rows(
                path,
                [
                    _legacy_claim("2026-07-15T11:00:00Z"),
                    _legacy_release("2026-07-15T11:00:00Z"),
                    v1_claim,
                    v2_claim,
                ],
            )

            snapshot = claims.CoordinationClaims(path).snapshot(now=now)

            self.assertEqual(
                [claim["claim_id"] for claim in snapshot["claims"]],
                ["clm_v1compat", "clm_v2compat"],
            )

    def test_legacy_compatibility_refuses_near_miss_rows(self) -> None:
        now = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
        bad_timestamp = _legacy_claim(
            "2026-07-15T09:59:00Z", expected_ship_by="not-a-timestamp"
        )
        missing_field = _legacy_claim("2026-07-15T09:59:00Z")
        del missing_field["expected_ship_by"]
        extra_field = _legacy_claim("2026-07-15T09:59:00Z")
        extra_field["extra"] = "not-compatible"
        empty_claim_id = _legacy_claim("2026-07-15T09:59:00Z")
        empty_claim_id["claim_id"] = ""
        cases = (
            (missing_field, "claim_id is invalid"),
            (extra_field, "claim_id is invalid"),
            (empty_claim_id, "claim_id is invalid"),
            (bad_timestamp, "expected_ship_by must be a timestamp"),
            (
                _legacy_release("2026-07-15T09:59:00Z", status="unknown"),
                "legacy claims-bus status must be one of",
            ),
        )
        for row, error in cases:
            with self.subTest(row=row):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "claims.jsonl"
                    _write_rows(path, [row])
                    with self.assertRaisesRegex(claims.ClaimsJournalError, error):
                        claims.CoordinationClaims(path).snapshot(now=now)

    def test_claims_file_override_is_accepted_after_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            claims_file = str(Path(tmp) / "claims.jsonl")
            claimed = _run(_claim_args(claims_file))
            self.assertEqual(claimed.returncode, 0, claimed.stderr)

            snapshot = _run(["snapshot", "--claims-file", claims_file])

            self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
            self.assertEqual(len(_json(snapshot)["claims"]), 1)

    def test_claim_release_round_trip_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            claims_file = str(Path(tmp) / "claims.jsonl")

            claim = _run(
                [
                    "--claims-file",
                    claims_file,
                    "claim",
                    "--repo",
                    "vidux",
                    "--claim",
                    "scripts/vidux-pr-body.py",
                    "--owner",
                    "codex-a",
                    "--lane",
                    "vidux-self-improvement",
                    "--plan-path",
                    "PLAN.md",
                    "--task-id",
                    "5.3.0c",
                ]
            )
            self.assertEqual(claim.returncode, 0, claim.stderr)
            claim_body = _json(claim)
            self.assertEqual(claim_body["status"], "claimed")
            claim_id = claim_body["claim"]["claim_id"]

            active = _run(["--claims-file", claims_file, "active", "--repo", "vidux"])
            self.assertEqual(active.returncode, 0, active.stderr)
            self.assertEqual(len(_json(active)["claims"]), 1)

            release = _run(
                [
                    "--claims-file",
                    claims_file,
                    "release",
                    "--claim-id",
                    claim_id,
                    "--owner",
                    "codex-a",
                ]
            )
            self.assertEqual(release.returncode, 0, release.stderr)
            self.assertEqual(_json(release)["status"], "released")

            active_after = _run(["--claims-file", claims_file, "active", "--repo", "vidux"])
            self.assertEqual(active_after.returncode, 0, active_after.stderr)
            self.assertEqual(_json(active_after)["claims"], [])

            rows = [
                json.loads(line)
                for line in Path(claims_file).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([row["event"] for row in rows], ["claim", "release"])

    def test_release_can_record_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            claims_file = str(Path(tmp) / "claims.jsonl")
            claim = _run(
                [
                    "--claims-file",
                    claims_file,
                    "claim",
                    "--repo",
                    "vidux",
                    "--claim",
                    "PLAN.md",
                    "--owner",
                    "codex-a",
                    "--lane",
                    "lane-a",
                    "--plan-path",
                    "PLAN.md",
                    "--task-id",
                    "T4",
                ]
            )
            self.assertEqual(claim.returncode, 0, claim.stderr)

            release = _run(
                [
                    "--claims-file",
                    claims_file,
                    "release",
                    "--repo",
                    "vidux",
                    "--claim",
                    "PLAN.md",
                    "--owner",
                    "codex-a",
                    "--status",
                    "blocked",
                ]
            )

            self.assertEqual(release.returncode, 0, release.stderr)
            self.assertEqual(_json(release)["release"]["status"], "blocked")

    def test_conflicting_active_claim_fails_without_appending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            claims_file = str(Path(tmp) / "claims.jsonl")
            first = _run(
                [
                    "--claims-file",
                    claims_file,
                    "claim",
                    "--repo",
                    "vidux",
                    "--claim",
                    "PLAN.md",
                    "--owner",
                    "codex-a",
                    "--lane",
                    "lane-a",
                    "--plan-path",
                    "PLAN.md",
                    "--task-id",
                    "T4",
                ]
            )
            self.assertEqual(first.returncode, 0, first.stderr)

            second = _run(
                [
                    "--claims-file",
                    claims_file,
                    "claim",
                    "--repo",
                    "vidux",
                    "--claim",
                    "PLAN.md",
                    "--owner",
                    "codex-b",
                    "--lane",
                    "lane-b",
                    "--plan-path",
                    "PLAN.md",
                    "--task-id",
                    "T4",
                ]
            )

            self.assertEqual(second.returncode, 3)
            self.assertEqual(_json(second)["status"], "conflict")
            self.assertEqual(len(Path(claims_file).read_text(encoding="utf-8").splitlines()), 1)

    def test_same_owner_claim_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            claims_file = str(Path(tmp) / "claims.jsonl")
            args = [
                "--claims-file",
                claims_file,
                "claim",
                "--repo",
                "vidux",
                "--claim",
                "PLAN.md",
                "--owner",
                "codex-a",
                "--lane",
                "lane-a",
                "--plan-path",
                "PLAN.md",
                "--task-id",
                "T4",
            ]
            self.assertEqual(_run(args).returncode, 0)
            second = _run(args)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(_json(second)["status"], "already_claimed")
            self.assertEqual(len(Path(claims_file).read_text(encoding="utf-8").splitlines()), 1)

    def test_heartbeat_and_checkpoint_renew_owned_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            claims_file = str(Path(tmp) / "claims.jsonl")
            claimed = _run(_claim_args(claims_file))
            self.assertEqual(claimed.returncode, 0, claimed.stderr)
            claim_id = _json(claimed)["claim"]["claim_id"]

            checkpoint = _run(
                [
                    "--claims-file",
                    claims_file,
                    "checkpoint",
                    "--claim-id",
                    claim_id,
                    "--owner",
                    "codex-a",
                    "--summary",
                    "Tests are green",
                    "--resume",
                    "Continue at PLAN row T4",
                    "--proof",
                    "python3 -m unittest tests.test_vidux_claims",
                    "--ttl-hours",
                    "3",
                ]
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr)
            checkpoint_body = _json(checkpoint)
            self.assertEqual(checkpoint_body["status"], "checkpointed")
            self.assertEqual(
                checkpoint_body["claim"]["checkpoint"]["resume"],
                "Continue at PLAN row T4",
            )

            heartbeat = _run(
                [
                    "--claims-file",
                    claims_file,
                    "heartbeat",
                    "--claim-id",
                    claim_id,
                    "--owner",
                    "codex-a",
                    "--ttl-hours",
                    "4",
                ]
            )
            self.assertEqual(heartbeat.returncode, 0, heartbeat.stderr)
            self.assertEqual(_json(heartbeat)["status"], "renewed")

            snapshot = _run(["--claims-file", claims_file, "snapshot"])
            self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
            snapshot_body = _json(snapshot)
            self.assertEqual(len(snapshot_body["claims"]), 1)
            _assert_private_process_fields_absent(self, snapshot_body)

    def test_usage_exhausted_handoff_is_resumable_and_takeover_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            first = _run(_claim_args(str(path), owner="codex-a"))
            claim_id = _json(first)["claim"]["claim_id"]
            checkpoint = _run(
                [
                    "--claims-file",
                    str(path),
                    "checkpoint",
                    "--claim-id",
                    claim_id,
                    "--owner",
                    "codex-a",
                    "--summary",
                    "Core written",
                    "--resume",
                    "Run the focused tests",
                ]
            )
            self.assertEqual(checkpoint.returncode, 0, checkpoint.stderr)

            released = _run(
                [
                    "--claims-file",
                    str(path),
                    "release",
                    "--claim-id",
                    claim_id,
                    "--owner",
                    "codex-a",
                    "--status",
                    "usage_exhausted",
                ]
            )
            self.assertEqual(released.returncode, 0, released.stderr)
            self.assertEqual(
                _json(released)["release"]["checkpoint"]["resume"],
                "Run the focused tests",
            )

            second = _run(_claim_args(str(path), owner="codex-b"))
            self.assertEqual(second.returncode, 0, second.stderr)
            second_body = _json(second)
            self.assertEqual(second_body["claim"]["takeover_of"], claim_id)
            self.assertEqual(
                second_body["takeover"]["checkpoint"]["resume"],
                "Run the focused tests",
            )

    def test_usage_exhausted_requires_resume_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            first = _run(_claim_args(str(path)))
            claim_id = _json(first)["claim"]["claim_id"]
            released = _run(
                [
                    "--claims-file",
                    str(path),
                    "release",
                    "--claim-id",
                    claim_id,
                    "--owner",
                    "codex-a",
                    "--status",
                    "usage_exhausted",
                ]
            )
            self.assertEqual(released.returncode, 2)
            self.assertIn("requires a checkpoint resume pointer", released.stderr)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

    def test_invalid_release_status_is_rejected_by_core_and_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            first = _run(_claim_args(str(path)))
            self.assertEqual(first.returncode, 0, first.stderr)
            claim_id = _json(first)["claim"]["claim_id"]
            original = path.read_text(encoding="utf-8")

            store = claims.CoordinationClaims(path)
            with self.assertRaisesRegex(
                claims.ClaimsError,
                "release status must be one of",
            ):
                store.release(
                    claim_id=claim_id,
                    owner="codex-a",
                    status="typo_complete",
                )
            self.assertEqual(path.read_text(encoding="utf-8"), original)

            cli = _run(
                [
                    "--claims-file",
                    str(path),
                    "release",
                    "--claim-id",
                    claim_id,
                    "--owner",
                    "codex-a",
                    "--status",
                    "typo_complete",
                ]
            )
            self.assertEqual(cli.returncode, 2)
            self.assertIn("invalid choice", cli.stderr)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_wrong_owner_cannot_renew_or_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            first = _run(_claim_args(str(path)))
            claim_id = _json(first)["claim"]["claim_id"]
            for command in ("heartbeat", "release"):
                result = _run(
                    [
                        "--claims-file",
                        str(path),
                        command,
                        "--claim-id",
                        claim_id,
                        "--owner",
                        "codex-b",
                    ]
                )
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertEqual(_json(result)["status"], "conflict")
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

    def test_strict_reader_refuses_malformed_and_aliased_journals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            malformed = Path(tmp) / "malformed.jsonl"
            malformed.write_text("{not-json}\n", encoding="utf-8")
            result = _run(["--claims-file", str(malformed), "active"])
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid JSON", result.stderr)

            invalid_utf8 = Path(tmp) / "invalid-utf8.jsonl"
            invalid_utf8.write_bytes(b"\xff")
            invalid = _run(["--claims-file", str(invalid_utf8), "active"])
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("valid UTF-8", invalid.stderr)

            bounded = Path(tmp) / "bounded.jsonl"
            bounded.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(claims.ClaimsJournalError):
                claims.CoordinationClaims(bounded, max_bytes=2).snapshot()

            target = Path(tmp) / "target.jsonl"
            target.write_text("", encoding="utf-8")
            alias = Path(tmp) / "alias.jsonl"
            os.symlink(target, alias)
            aliased = _run(["--claims-file", str(alias), "active"])
            self.assertEqual(aliased.returncode, 2)
            self.assertIn("unsafe", aliased.stderr)

    def test_expired_claim_does_not_block_new_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "event": "claim",
                        "claim_id": "clm_old",
                        "ts": "2000-01-01T00:00:00Z",
                        "repo": "vidux",
                        "claim": "PLAN.md",
                        "files_claimed": ["PLAN.md"],
                        "owner": "codex-old",
                        "lane": "old",
                        "plan_path": "PLAN.md",
                        "task_id": "T4",
                        "ttl_hours": 2,
                        "expires_at": "2000-01-01T02:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = _run(
                [
                    "--claims-file",
                    str(path),
                    "claim",
                    "--repo",
                    "vidux",
                    "--claim",
                    "PLAN.md",
                    "--owner",
                    "codex-new",
                    "--lane",
                    "new",
                    "--plan-path",
                    "PLAN.md",
                    "--task-id",
                    "T4",
                ]
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(_json(result)["status"], "claimed")
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)

    def test_main_empty_argv_does_not_read_process_argv(self) -> None:
        """Programmatic main([]) must not claim from ambient sys.argv."""
        with tempfile.TemporaryDirectory() as tmp:
            claims_file = Path(tmp) / "ambient-claims.jsonl"
            original_argv = sys.argv[:]
            sys.argv = [
                "probe",
                "--claims-file",
                str(claims_file),
                "claim",
                "--repo",
                "vidux",
                "--claim",
                "PLAN.md",
                "--owner",
                "codex-a",
                "--lane",
                "lane-a",
                "--plan-path",
                "PLAN.md",
                "--task-id",
                "T4",
            ]
            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                with (
                    self.assertRaises(SystemExit) as raised,
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    claims.main([])
            finally:
                sys.argv = original_argv

            self.assertEqual(raised.exception.code, 2)
            self.assertIn("the following arguments are required", stderr.getvalue())
            self.assertEqual(stdout.getvalue(), "")
            self.assertFalse(claims_file.exists())


class DefaultOwnerPidLeakTests(unittest.TestCase):
    """Regression: the manual fallback owner must not embed the raw process id.

    The owner string is projected verbatim onto the loopback /api/coordination
    panel, which guarantees no PID crosses that HTTP boundary. Before the fix,
    `_default_owner()` returned `manual-pid-<os.getpid()>`, leaking the PID — a
    path the existing coordination-projection tests never exercise (they pass
    explicit owner strings).
    """

    _OWNER_ENV = (
        "VIDUX_OWNER",
        "CODEX_THREAD_ID",
        "CODEX_AGENT_ID",
        "CLAUDE_SESSION_ID",
        "CLAUDE_AUTOMATION_NAME",
    )

    def _clear_owner_env(self) -> dict:
        saved = {k: os.environ.pop(k, None) for k in self._OWNER_ENV}
        claims._FALLBACK_OWNER = None
        return saved

    def _restore_owner_env(self, saved: dict) -> None:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        claims._FALLBACK_OWNER = None

    def test_default_owner_has_no_pid(self):
        saved = self._clear_owner_env()
        try:
            owner = claims._default_owner()
        finally:
            self._restore_owner_env(saved)
        self.assertNotIn(str(os.getpid()), owner)
        self.assertNotIn("pid", owner)
        self.assertTrue(owner.startswith("manual-"), owner)
        suffix = owner[len("manual-"):]
        self.assertEqual(len(suffix), 8, owner)
        self.assertTrue(all(c in "0123456789abcdef" for c in suffix), owner)

    def test_default_owner_is_stable_within_process(self):
        saved = self._clear_owner_env()
        try:
            self.assertEqual(claims._default_owner(), claims._default_owner())
        finally:
            self._restore_owner_env(saved)

    def test_explicit_env_owner_still_wins(self):
        saved = self._clear_owner_env()
        try:
            os.environ["VIDUX_OWNER"] = "codex-thread-7"
            self.assertEqual(claims._default_owner(), "codex-thread-7")
        finally:
            self._restore_owner_env(saved)


if __name__ == "__main__":
    unittest.main()
