from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BROWSER_DIR = ROOT / "browser"
sys.path.insert(0, str(BROWSER_DIR))

from safe_files import UnsafeFileAliasError, open_regular_fd  # noqa: E402
from server import has_sensitive_text  # noqa: E402
from steering_mailbox import (  # noqa: E402
    ACTIVE_LIMIT_PER_PLAN,
    DEFAULT_TOMBSTONE_LIMIT,
    INTENT_MAX_BYTES,
    JournalCorruptError,
    MailboxConflictError,
    MailboxValidationError,
    SteeringMailbox,
)


class SteeringMailboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dev_root = Path(self.tmp.name) / "Development"
        self.dev_root.mkdir()
        self.plan_a = self._make_plan("alpha")
        self.plan_b = self._make_plan("beta")
        self.store = Path(self.tmp.name) / "state" / "steering.jsonl"
        self.mailbox = SteeringMailbox(
            self.store,
            dev_root=self.dev_root,
            sensitive_check=has_sensitive_text,
        )
        self.start = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_plan(self, name: str) -> Path:
        plan = self.dev_root / name / "PLAN.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(f"# {name}\n", encoding="utf-8")
        return plan.resolve()

    def _enqueue(self, body: str, *, plan: Path | None = None, seconds: int = 0) -> dict:
        return self.mailbox.enqueue_intent(
            plan or self.plan_a,
            body,
            source="test-loop",
            now=self.start + timedelta(seconds=seconds),
        )

    def test_enqueue_rejects_outside_wrong_name_sensitive_and_ninth_active_item(self) -> None:
        outside = Path(self.tmp.name) / "outside" / "PLAN.md"
        outside.parent.mkdir()
        outside.write_text("# Outside\n", encoding="utf-8")
        wrong_name = self.plan_a.with_name("NOTES.md")
        wrong_name.write_text("# Notes\n", encoding="utf-8")

        with self.assertRaisesRegex(MailboxValidationError, "development root"):
            self.mailbox.enqueue_intent(outside, "safe intent")
        with self.assertRaisesRegex(MailboxValidationError, "PLAN.md"):
            self.mailbox.enqueue_intent(wrong_name, "safe intent")
        with self.assertRaisesRegex(MailboxValidationError, "sensitive content"):
            self.mailbox.enqueue_intent(self.plan_a, "token=sk-" + "a1b2c3d4" * 4)

        for index in range(ACTIVE_LIMIT_PER_PLAN):
            self._enqueue(f"intent {index}", seconds=index)
        with self.assertRaisesRegex(MailboxConflictError, "8 active"):
            self._enqueue("one too many", seconds=20)

    def test_enqueue_rejects_in_root_plan_not_discovered_by_cockpit(self) -> None:
        undiscovered = self.dev_root / "repo" / "random" / "nested" / "PLAN.md"
        undiscovered.parent.mkdir(parents=True)
        undiscovered.write_text("# Undiscovered\n", encoding="utf-8")
        with self.assertRaisesRegex(MailboxValidationError, "discovered"):
            self.mailbox.enqueue_intent(undiscovered, "must not enter mailbox")

    def test_discovery_cache_refreshes_when_new_plan_appears(self) -> None:
        self._enqueue("fill discovery cache")
        new_plan = self._make_plan("newly-created")
        queued = self.mailbox.enqueue_intent(new_plan, "new plan is immediately allowed")
        self.assertEqual(queued["plan_path"], str(new_plan))

    def test_named_authority_plan_is_discovered_and_steerable(self) -> None:
        plan = self.dev_root / "acme-ios" / ".cursor" / "plans" / "NORTH-STAR.plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# Acme North Star\n", encoding="utf-8")

        queued = self.mailbox.enqueue_intent(plan, "coordinate the next safe cycle")
        lease = self.mailbox.lease_next_intent(plan, "acme-loop", now=self.start)

        self.assertEqual(queued["plan_path"], str(plan.resolve()))
        self.assertEqual(lease["id"], queued["id"])

    def test_legacy_cached_winner_is_rechecked_when_canonical_plan_appears(self) -> None:
        legacy = self._make_plan("legacy")
        self.mailbox.repo_aliases = {"legacy": "canonical"}
        queued = self.mailbox.enqueue_intent(legacy, "legacy while canonical is absent")
        self._make_plan("canonical")

        with self.assertRaisesRegex(MailboxValidationError, "discovered"):
            self.mailbox.lease_next_intent(legacy, "loop", now=self.start)
        snapshot = self.mailbox.read_mailbox()
        item = next(row for row in snapshot["items"] if row["id"] == queued["id"])
        self.assertFalse(item["plan_available"])

    def test_alias_availability_reuses_one_discovery_scan_per_read(self) -> None:
        legacy = self._make_plan("legacy")
        self.mailbox.repo_aliases = {"legacy": "canonical"}
        self.mailbox.enqueue_intent(legacy, "first legacy item")
        self.mailbox.enqueue_intent(legacy, "second legacy item")

        original = self.mailbox._discovered_plan_paths
        with mock.patch.object(
            self.mailbox,
            "_discovered_plan_paths",
            wraps=original,
        ) as discover:
            snapshot = self.mailbox.read_mailbox()
        self.assertTrue(snapshot["ok"], snapshot)
        forced = [
            call
            for call in discover.call_args_list
            if call.kwargs.get("force_refresh") is True
        ]
        self.assertEqual(len(forced), 1)

    def test_default_tombstone_limit_matches_security_contract(self) -> None:
        self.assertEqual(DEFAULT_TOMBSTONE_LIMIT, 64)

    def test_renamed_plan_symlink_cannot_retarget_queued_intent(self) -> None:
        item = self._enqueue("intent for alpha only")
        stored_path = str(self.plan_a)
        alpha_dir = self.plan_a.parent
        moved_dir = self.dev_root / "alpha-moved"
        alpha_dir.rename(moved_dir)
        alpha_dir.symlink_to(self.plan_b.parent, target_is_directory=True)

        beta_snapshot = self.mailbox.read_mailbox(plan_path=self.plan_b)
        self.assertTrue(beta_snapshot["ok"], beta_snapshot)
        self.assertEqual(beta_snapshot["items"], [])
        self.assertIsNone(
            self.mailbox.lease_next_intent(self.plan_b, "beta-loop", now=self.start)
        )

        all_items = self.mailbox.read_mailbox()["items"]
        self.assertEqual(all_items[0]["id"], item["id"])
        self.assertEqual(all_items[0]["plan_path"], stored_path)
        self.assertFalse(all_items[0]["plan_available"])

    def test_hard_linked_plan_cannot_alias_queued_authority(self) -> None:
        item = self._enqueue("intent for original alpha authority")
        self.plan_a.unlink()
        os.link(self.plan_b, self.plan_a)

        snapshot = self.mailbox.read_mailbox()
        self.assertTrue(snapshot["ok"], snapshot)
        queued = next(row for row in snapshot["items"] if row["id"] == item["id"])
        self.assertFalse(queued["plan_available"])
        with self.assertRaisesRegex(MailboxValidationError, "single-link"):
            self.mailbox.lease_next_intent(self.plan_a, "loop", now=self.start)

    def test_deleted_plan_does_not_corrupt_unrelated_plan_queue(self) -> None:
        alpha = self._enqueue("orphaned alpha intent")
        self.plan_a.unlink()

        beta = self._enqueue("beta continues", plan=self.plan_b, seconds=1)
        snapshot = self.mailbox.read_mailbox()
        self.assertTrue(snapshot["ok"], snapshot)
        by_id = {item["id"]: item for item in snapshot["items"]}
        self.assertFalse(by_id[alpha["id"]]["plan_available"])
        self.assertTrue(by_id[beta["id"]]["plan_available"])
        leased = self.mailbox.lease_next_intent(
            self.plan_b, "beta-loop", now=self.start + timedelta(seconds=2)
        )
        self.assertEqual(leased["id"], beta["id"])

    def test_fifo_leases_are_exact_plan_and_one_per_consumer(self) -> None:
        first = self._enqueue("alpha first", seconds=0)
        beta = self._enqueue("beta only", plan=self.plan_b, seconds=1)
        self._enqueue("alpha second", seconds=2)

        leased_alpha = self.mailbox.lease_next_intent(
            self.plan_a, "loop-a", now=self.start + timedelta(seconds=3)
        )
        self.assertEqual(leased_alpha["id"], first["id"])
        with self.assertRaisesRegex(MailboxConflictError, "already holds"):
            self.mailbox.lease_next_intent(
                self.plan_a, "loop-a", now=self.start + timedelta(seconds=4)
            )

        leased_beta = self.mailbox.lease_next_intent(
            self.plan_b, "loop-b", now=self.start + timedelta(seconds=3)
        )
        self.assertEqual(leased_beta["id"], beta["id"])

    def test_lease_token_is_hashed_at_rest_and_never_listed(self) -> None:
        self._enqueue("keep the token private")
        leased = self.mailbox.lease_next_intent(self.plan_a, "local-loop", now=self.start)
        token = leased["lease_token"]

        journal = self.store.read_text(encoding="utf-8")
        self.assertNotIn(token, journal)
        self.assertIn("lease_token_hash", journal)
        listed = self.mailbox.read_mailbox(plan_path=self.plan_a)["items"][0]
        self.assertNotIn("lease_token", listed)
        self.assertNotIn("lease_token_hash", listed)
        self.assertNotIn("consumer", listed)

    def test_ack_is_idempotent_only_for_matching_lease_token(self) -> None:
        item = self._enqueue("one shot only")
        leased = self.mailbox.lease_next_intent(self.plan_a, "loop", now=self.start)
        with self.assertRaisesRegex(MailboxConflictError, "stale or invalid"):
            self.mailbox.acknowledge_intent(item["id"], "wrong-token", now=self.start)
        first = self.mailbox.acknowledge_intent(
            item["id"], leased["lease_token"], now=self.start
        )
        repeated = self.mailbox.acknowledge_intent(
            item["id"], leased["lease_token"], now=self.start + timedelta(seconds=1)
        )
        self.assertEqual(repeated, first)
        with self.assertRaisesRegex(MailboxConflictError, "stale or invalid"):
            self.mailbox.acknowledge_intent(item["id"], "wrong-token", now=self.start)

    def test_fail_is_idempotent_only_for_matching_token_and_code(self) -> None:
        item = self._enqueue("fail callback may be replayed")
        leased = self.mailbox.lease_next_intent(self.plan_a, "loop", now=self.start)
        first = self.mailbox.fail_intent(
            item["id"],
            leased["lease_token"],
            "usage_exhausted",
            now=self.start + timedelta(seconds=1),
        )
        with self.mailbox._write_guard():
            reduced = self.mailbox._read_reduced(now=self.start + timedelta(seconds=1))
            self.mailbox._write_events(self.mailbox._compacted_events(reduced))
        reopened = SteeringMailbox(
            self.store,
            dev_root=self.dev_root,
            sensitive_check=has_sensitive_text,
        )
        repeated = reopened.fail_intent(
            item["id"],
            leased["lease_token"],
            "usage_exhausted",
            now=self.start + timedelta(seconds=2),
        )
        self.assertEqual(repeated, first)
        with self.assertRaisesRegex(MailboxConflictError, "does not match"):
            reopened.fail_intent(
                item["id"],
                leased["lease_token"],
                "transport_unavailable",
                now=self.start + timedelta(seconds=2),
            )
        with self.assertRaisesRegex(MailboxConflictError, "does not match"):
            reopened.fail_intent(
                item["id"],
                "wrong-token",
                "usage_exhausted",
                now=self.start + timedelta(seconds=2),
            )

    def test_retry_preserves_original_fifo_position(self) -> None:
        first = self._enqueue("first", seconds=0)
        second = self._enqueue("second", seconds=1)
        lease = self.mailbox.lease_next_intent(
            self.plan_a, "loop", now=self.start + timedelta(seconds=2)
        )
        failed = self.mailbox.fail_intent(
            first["id"],
            lease["lease_token"],
            "usage_exhausted",
            now=self.start + timedelta(seconds=3),
        )
        self.assertEqual(failed["state"], "retryable")
        self.assertNotIn("claimed_at", failed)

        retried = self.mailbox.retry_intent(
            first["id"], now=self.start + timedelta(seconds=4)
        )
        self.assertEqual(retried["created_at"], first["created_at"])
        leased_again = self.mailbox.lease_next_intent(
            self.plan_a, "loop", now=self.start + timedelta(seconds=5)
        )
        self.assertEqual(leased_again["id"], first["id"])
        self.assertNotEqual(leased_again["id"], second["id"])

    def test_acknowledgement_compacts_body_to_bounded_tombstone(self) -> None:
        mailbox = SteeringMailbox(
            self.store,
            dev_root=self.dev_root,
            sensitive_check=has_sensitive_text,
            tombstone_limit=2,
        )
        ids = []
        bodies = []
        for index in range(3):
            body = f"transient body {index}"
            bodies.append(body)
            item = mailbox.enqueue_intent(
                self.plan_a, body, now=self.start + timedelta(seconds=index * 3)
            )
            ids.append(item["id"])
            lease = mailbox.lease_next_intent(
                self.plan_a,
                f"loop-{index}",
                now=self.start + timedelta(seconds=index * 3 + 1),
            )
            mailbox.acknowledge_intent(
                item["id"],
                lease["lease_token"],
                now=self.start + timedelta(seconds=index * 3 + 2),
            )

        snapshot = mailbox.read_mailbox(plan_path=self.plan_a, include_tombstones=True)
        self.assertEqual(snapshot["items"], [])
        self.assertEqual([row["id"] for row in snapshot["tombstones"]], ids[-2:])
        journal = self.store.read_text(encoding="utf-8")
        for body in bodies:
            self.assertNotIn(body, journal)
        self.assertNotIn("body", snapshot["tombstones"][0])

    def test_ack_compaction_preserves_other_active_intent(self) -> None:
        first = self._enqueue("first disappears", seconds=0)
        second = self._enqueue("second remains", seconds=1)
        leased = self.mailbox.lease_next_intent(
            self.plan_a, "loop", now=self.start + timedelta(seconds=2)
        )
        self.mailbox.acknowledge_intent(
            first["id"], leased["lease_token"], now=self.start + timedelta(seconds=3)
        )
        snapshot = self.mailbox.read_mailbox(plan_path=self.plan_a)
        self.assertEqual([item["id"] for item in snapshot["items"]], [second["id"]])
        self.assertNotIn("first disappears", self.store.read_text(encoding="utf-8"))
        self.assertIn("second remains", self.store.read_text(encoding="utf-8"))

    def test_terminal_failure_is_not_retryable_and_can_be_dismissed(self) -> None:
        item = self._enqueue("policy-sensitive instruction")
        lease = self.mailbox.lease_next_intent(self.plan_a, "loop", now=self.start)
        failed = self.mailbox.fail_intent(
            item["id"], lease["lease_token"], "policy_blocked", now=self.start
        )
        self.assertEqual(failed["state"], "failed")
        with self.assertRaisesRegex(MailboxConflictError, "not retryable"):
            self.mailbox.retry_intent(item["id"], now=self.start)
        self.mailbox.dismiss_intent(item["id"], now=self.start)
        self.assertNotIn("policy-sensitive instruction", self.store.read_text(encoding="utf-8"))

    def test_expired_lease_projects_retryable_then_persists_valid_retry(self) -> None:
        item = self._enqueue("retry after expiry")
        self.mailbox.lease_next_intent(
            self.plan_a,
            "loop",
            lease_seconds=5,
            now=self.start,
        )
        after_expiry = self.start + timedelta(seconds=6)
        listed = self.mailbox.read_mailbox(plan_path=self.plan_a, now=after_expiry)["items"][0]
        self.assertEqual(listed["state"], "retryable")
        self.assertEqual(listed["failure_code"], "lease_expired")

        self.mailbox.retry_intent(item["id"], now=after_expiry)
        leased_again = self.mailbox.lease_next_intent(
            self.plan_a, "loop", now=after_expiry + timedelta(seconds=1)
        )
        self.assertEqual(leased_again["id"], item["id"])

    def test_malformed_journal_preserves_prior_read_but_blocks_mutation(self) -> None:
        first = self._enqueue("valid before corruption")
        with self.store.open("a", encoding="utf-8") as handle:
            handle.write("{not-json}\n")

        snapshot = self.mailbox.read_mailbox(plan_path=self.plan_a)
        self.assertFalse(snapshot["ok"])
        self.assertEqual(snapshot["items"][0]["id"], first["id"])
        self.assertIn("journal line 2", snapshot["journal_error"])
        with self.assertRaises(JournalCorruptError):
            self._enqueue("must fail closed")

    def test_invalid_utf8_journal_fails_closed_without_rewriting_bytes(self) -> None:
        self._enqueue("valid before invalid bytes")
        original = self.store.read_bytes() + b"\xff"
        self.store.write_bytes(original)

        snapshot = self.mailbox.read_mailbox()
        self.assertFalse(snapshot["ok"])
        self.assertEqual(snapshot["items"], [])
        self.assertEqual(snapshot["journal_error"], "journal is not valid UTF-8")
        with self.assertRaisesRegex(JournalCorruptError, "UTF-8"):
            self._enqueue("must not rewrite invalid bytes")
        self.assertEqual(self.store.read_bytes(), original)

    def test_malformed_snapshot_metadata_is_not_exposed(self) -> None:
        base = {
            "schema": 1,
            "event": "snapshot",
            "id": "11111111-1111-4111-8111-111111111111",
            "plan_path": str(self.plan_a),
            "body": "safe body",
            "source": "",
            "state": "queued",
            "created_at": "2026-07-11T12:00:00.000Z",
            "attempts": 0,
        }
        cases = (
            {"updated_at": "token=sk-" + "a1b2c3d4" * 4},
            {"failure_code": "policy_blocked"},
            {"claimed_at": "2026-07-11T12:00:01.000Z"},
        )
        for index, invalid_fields in enumerate(cases):
            with self.subTest(invalid_fields=invalid_fields):
                event = {**base, **invalid_fields}
                event["id"] = f"11111111-1111-4111-8111-{index + 1:012d}"
                self.store.parent.mkdir(parents=True, exist_ok=True)
                self.store.write_text(json.dumps(event) + "\n", encoding="utf-8")
                snapshot = self.mailbox.read_mailbox()
                self.assertFalse(snapshot["ok"])
                self.assertEqual(snapshot["items"], [])
                self.assertNotIn("token=sk-", json.dumps(snapshot))

    def test_unknown_event_secret_is_redacted_from_journal_error(self) -> None:
        secret = "token=sk-" + "a1b2c3d4" * 4
        event = {
            "schema": 1,
            "event": secret,
            "id": "33333333-3333-4333-8333-333333333333",
        }
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(json.dumps(event) + "\n", encoding="utf-8")
        snapshot = self.mailbox.read_mailbox()
        self.assertFalse(snapshot["ok"])
        self.assertNotIn(secret, json.dumps(snapshot))
        self.assertIn("unknown event type", snapshot["journal_error"])

    def test_malformed_tombstone_timestamps_fail_closed(self) -> None:
        tombstone = {
            "schema": 1,
            "event": "tombstone",
            "id": "22222222-2222-4222-8222-222222222222",
            "plan_path": str(self.plan_a),
            "final_state": "acknowledged",
            "created_at": "not-a-timestamp",
            "completed_at": "2026-07-11T12:00:00.000Z",
        }
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(json.dumps(tombstone) + "\n", encoding="utf-8")
        snapshot = self.mailbox.read_mailbox(include_tombstones=True)
        self.assertFalse(snapshot["ok"])
        self.assertEqual(snapshot["tombstones"], [])

    def test_malformed_json_field_types_fail_cleanly(self) -> None:
        with self.assertRaisesRegex(MailboxValidationError, "PLAN.md"):
            self.mailbox.enqueue_intent(42, "safe intent")
        item = self._enqueue("token type check")
        self.mailbox.lease_next_intent(self.plan_a, "loop", now=self.start)
        with self.assertRaisesRegex(MailboxConflictError, "stale or invalid"):
            self.mailbox.acknowledge_intent(item["id"], {"not": "a token"}, now=self.start)

    def test_store_and_lock_aliases_are_rejected_without_touching_referent(self) -> None:
        cases = ("store-symlink", "store-hardlink", "lock-symlink", "lock-hardlink")
        for case in cases:
            with self.subTest(case=case):
                case_root = Path(self.tmp.name) / case
                case_root.mkdir()
                store = case_root / "steering.jsonl"
                mailbox = SteeringMailbox(
                    store,
                    dev_root=self.dev_root,
                    sensitive_check=has_sensitive_text,
                )
                outside = case_root / "outside.txt"
                outside.write_text("outside stays unchanged\n", encoding="utf-8")
                target = store if case.startswith("store") else mailbox.lock_path
                if case.endswith("symlink"):
                    target.symlink_to(outside)
                else:
                    os.link(outside, target)

                with self.assertRaises(UnsafeFileAliasError):
                    mailbox.enqueue_intent(self.plan_a, "safe local intent")
                self.assertEqual(
                    outside.read_text(encoding="utf-8"),
                    "outside stays unchanged\n",
                )

    def test_create_open_retries_transient_darwin_enoent(self) -> None:
        target = Path(self.tmp.name) / "transient-create.lock"
        real_open = os.open
        final_attempts = 0

        def transient_open(path, flags, *args, **kwargs):
            nonlocal final_attempts
            if path == target.name and flags & os.O_CREAT:
                final_attempts += 1
                if final_attempts == 1:
                    raise FileNotFoundError(2, "transient create race", path)
            return real_open(path, flags, *args, **kwargs)

        with mock.patch("safe_files.os.open", side_effect=transient_open):
            with open_regular_fd(
                target,
                os.O_RDWR | os.O_CREAT,
                create_parent=True,
            ):
                pass

        self.assertEqual(final_attempts, 2)
        self.assertTrue(target.is_file())

    def test_concurrent_cli_enqueues_do_not_lose_rows(self) -> None:
        env = {
            **os.environ,
            "VIDUX_BROWSER_STEERING_FILE": str(self.store),
            "VIDUX_DEV_ROOT": str(self.dev_root),
        }
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "vidux-steer.py"),
                    "enqueue",
                    "--plan",
                    str(self.plan_a),
                    "--message",
                    f"concurrent {index}",
                    "--json",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for index in range(ACTIVE_LIMIT_PER_PLAN)
        ]
        outputs = [process.communicate(timeout=20) for process in processes]
        for process, (stdout, stderr) in zip(processes, outputs):
            self.assertEqual(process.returncode, 0, stdout + stderr)
            self.assertTrue(json.loads(stdout)["ok"])
        snapshot = self.mailbox.read_mailbox(plan_path=self.plan_a)
        self.assertTrue(snapshot["ok"], snapshot)
        self.assertEqual(len(snapshot["items"]), ACTIVE_LIMIT_PER_PLAN)

    def test_two_cli_consumers_cannot_lease_the_same_item(self) -> None:
        self._enqueue("single lease target")
        env = {
            **os.environ,
            "VIDUX_BROWSER_STEERING_FILE": str(self.store),
            "VIDUX_DEV_ROOT": str(self.dev_root),
        }
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "vidux-steer.py"),
                    "lease",
                    "--plan",
                    str(self.plan_a),
                    "--consumer",
                    f"consumer-{index}",
                    "--json",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for index in range(2)
        ]
        outputs = [process.communicate(timeout=20) for process in processes]
        payloads = []
        for process, (stdout, stderr) in zip(processes, outputs):
            self.assertEqual(process.returncode, 0, stdout + stderr)
            payloads.append(json.loads(stdout)["item"])
        self.assertEqual(sum(payload is not None for payload in payloads), 1)


class SteeringCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dev_root = Path(self.tmp.name) / "Development"
        self.plan = self.dev_root / "demo" / "PLAN.md"
        self.plan.parent.mkdir(parents=True)
        self.plan.write_text("# Demo\n", encoding="utf-8")
        self.store = Path(self.tmp.name) / "steering.jsonl"
        self.env = {
            **os.environ,
            "VIDUX_BROWSER_STEERING_FILE": str(self.store),
            "VIDUX_DEV_ROOT": str(self.dev_root),
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(
        self,
        *args: str,
        stdin_payload: dict | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "vidux-steer.py"), *args],
            cwd=ROOT,
            env=self.env,
            input=json.dumps(stdin_payload) if stdin_payload is not None else None,
            text=True,
            capture_output=True,
            timeout=20,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_json_stdin_host_path_completes_lifecycle_without_token_in_argv(self) -> None:
        enqueued = self.run_cli(
            "enqueue",
            "--stdin-json",
            "--json",
            stdin_payload={"plan": str(self.plan), "message": "steer the next cycle"},
        )
        item_id = json.loads(enqueued.stdout)["item"]["id"]
        leased = self.run_cli(
            "lease",
            "--plan",
            str(self.plan),
            "--consumer",
            "test-host",
            "--json",
        )
        lease_payload = json.loads(leased.stdout)["item"]
        token = lease_payload["lease_token"]
        self.assertNotIn(token, self.store.read_text(encoding="utf-8"))

        acked = self.run_cli(
            "ack",
            "--stdin-json",
            "--json",
            stdin_payload={"id": item_id, "lease_token": token},
        )
        self.assertEqual(json.loads(acked.stdout)["tombstone"]["final_state"], "acknowledged")
        listed = self.run_cli("list", "--plan", str(self.plan), "--all", "--json")
        payload = json.loads(listed.stdout)
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["tombstones"][0]["id"], item_id)
        self.assertNotIn("steer the next cycle", self.store.read_text(encoding="utf-8"))

    def test_stdin_json_accepts_worst_case_escaped_valid_intent(self) -> None:
        message = "\x01" * (INTENT_MAX_BYTES - 2) + '"\\'
        self.assertEqual(len(message.encode("utf-8")), INTENT_MAX_BYTES)
        result = self.run_cli(
            "enqueue",
            "--stdin-json",
            "--json",
            stdin_payload={"plan": str(self.plan), "message": message},
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["item"]["body"], message)

    def test_human_lease_is_refused_without_consuming_item(self) -> None:
        self.run_cli("enqueue", "--plan", str(self.plan), "--message", "human output")
        refused = self.run_cli(
            "lease",
            "--plan",
            str(self.plan),
            "--consumer",
            "human-host",
            check=False,
        )
        self.assertEqual(refused.returncode, 1)
        self.assertIn("requires --json", refused.stderr)
        listed = json.loads(
            self.run_cli("list", "--plan", str(self.plan), "--json").stdout
        )
        self.assertEqual(listed["items"][0]["state"], "queued")
        self.assertNotIn('"event":"lease"', self.store.read_text(encoding="utf-8"))

    def test_human_list_escapes_terminal_control_sequences(self) -> None:
        message = "safe\x1b]0;OWNED\x07"
        self.run_cli(
            "enqueue",
            "--plan",
            str(self.plan),
            "--message",
            message,
            "--json",
        )
        listed = self.run_cli("list", "--plan", str(self.plan))
        self.assertNotIn("\x1b", listed.stdout)
        self.assertNotIn("\x07", listed.stdout)
        self.assertIn("safe\\x1b]0;OWNED\\x07", listed.stdout)

    def test_browse_help_exposes_steering_contract(self) -> None:
        browse_help = subprocess.run(
            [str(ROOT / "bin" / "vidux"), "help", "browse"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(browse_help.returncode, 0, browse_help.stderr)
        self.assertIn("--steering-path PATH", browse_help.stdout)

    def test_raw_failure_text_is_not_accepted_as_a_code(self) -> None:
        self.run_cli("enqueue", "--plan", str(self.plan), "--message", "will fail safely")
        lease = json.loads(
            self.run_cli(
                "lease",
                "--plan",
                str(self.plan),
                "--consumer",
                "host",
                "--json",
            ).stdout
        )["item"]
        result = self.run_cli(
            "fail",
            "--stdin-json",
            "--json",
            stdin_payload={
                "id": lease["id"],
                "lease_token": lease["lease_token"],
                "code": "provider said account balance and raw stack trace",
            },
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"], "failure code is not allowed")

    def test_stdin_json_wrong_types_return_bounded_error_without_traceback(self) -> None:
        result = self.run_cli(
            "enqueue",
            "--stdin-json",
            "--json",
            stdin_payload={"plan": 42, "message": "safe intent"},
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("PLAN.md", json.loads(result.stdout)["error"])
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
