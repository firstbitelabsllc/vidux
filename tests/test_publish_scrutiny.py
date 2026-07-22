"""Tests for scripts/vidux-publish-scrutiny.py."""

from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "vidux-publish-scrutiny.py"

spec = importlib.util.spec_from_file_location("vidux_publish_scrutiny", SCRIPT)
assert spec is not None
publish_scrutiny = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = publish_scrutiny
spec.loader.exec_module(publish_scrutiny)


def _plan(root: Path) -> Path:
    path = root / "PLAN.md"
    path.write_text(
        "# Test Plan\n\n"
        "## Tasks\n"
        "- [in_progress] 5.3.0n Publish self-scrutiny preflight.\n",
        encoding="utf-8",
    )
    return path


def _reviews() -> list[object]:
    return [
        publish_scrutiny.ReviewPass(
            "invariant",
            "pass",
            "plan row, ledger eid, drift check, files claimed, and resume point present",
        ),
        publish_scrutiny.ReviewPass(
            "regression",
            "pass",
            "python3 -m unittest tests.test_publish_scrutiny",
        ),
        publish_scrutiny.ReviewPass(
            "adversarial",
            "pass",
            "no overclaim, stale proof, duplicate plan, unsafe publish, or policy drift found",
        ),
    ]


def _packet(plan: Path, **overrides: object) -> dict[str, object]:
    packet: dict[str, object] = {
        "lane": "vidux-self-improvement",
        "task": "5.3.0n",
        "summary": "publish self-scrutiny preflight",
        "plan_path": str(plan),
        "proof": "python3 -m unittest tests.test_publish_scrutiny",
        "ledger": "evt_selfscrutiny",
        "handoff_status": "done",
        "files_claimed": [
            "scripts/vidux-publish-scrutiny.py",
            "tests/test_publish_scrutiny.py",
        ],
        "claims": [
            "PLAN.md",
            "scripts/vidux-publish-scrutiny.py",
            "tests/test_publish_scrutiny.py",
        ],
        "resume": "continue 5.3.1 once acme gh pr create overlap is unblocked",
        "review_passes": _reviews(),
    }
    packet.update(overrides)
    return packet


class PublishScrutinyTests(unittest.TestCase):
    def test_ready_when_publish_packet_and_all_reviews_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = publish_scrutiny.scrutinize_publish(**_packet(_plan(Path(tmp))))

        self.assertTrue(report["ready"], report)
        self.assertEqual(report["missing_fields"], [])
        self.assertEqual(report["missing_review_passes"], [])
        self.assertEqual(report["failed_review_passes"], [])
        self.assertTrue(report["checks"]["plan_exists"])
        self.assertTrue(report["checks"]["task_in_plan"])
        self.assertEqual(report["review_passes"]["adversarial"]["status"], "pass")

    def test_missing_summary_blocks_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = publish_scrutiny.scrutinize_publish(
                **_packet(_plan(Path(tmp)), summary="")
            )

        self.assertFalse(report["ready"])
        self.assertIn("summary", report["missing_fields"])

    def test_blank_summary_blocks_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = publish_scrutiny.scrutinize_publish(
                **_packet(_plan(Path(tmp)), summary="   ")
            )

        self.assertFalse(report["ready"])
        self.assertIn("summary", report["missing_fields"])

    def test_missing_required_review_pass_blocks_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reviews = _reviews()[:2]
            report = publish_scrutiny.scrutinize_publish(
                **_packet(_plan(Path(tmp)), review_passes=reviews)
            )

        self.assertFalse(report["ready"])
        self.assertEqual(report["missing_review_passes"], ["adversarial"])

    def test_ledger_must_be_publish_eid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = publish_scrutiny.scrutinize_publish(
                **_packet(_plan(Path(tmp)), ledger="will emit later")
            )

        self.assertFalse(report["ready"])
        self.assertEqual(report["invalid_fields"][0]["field"], "ledger")
        self.assertIn("publish ledger eid", report["invalid_fields"][0]["reason"])

    def test_failed_review_pass_blocks_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reviews = _reviews()
            reviews[-1] = publish_scrutiny.ReviewPass(
                "adversarial",
                "fail",
                "PLAN progress claims done before ledger eid is recorded",
            )
            report = publish_scrutiny.scrutinize_publish(
                **_packet(_plan(Path(tmp)), review_passes=reviews)
            )

        self.assertFalse(report["ready"])
        self.assertEqual(report["failed_review_passes"][0]["name"], "adversarial")
        self.assertIn("ledger eid", report["failed_review_passes"][0]["evidence"])

    def test_duplicate_review_pass_blocks_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reviews = _reviews()
            reviews.append(
                publish_scrutiny.ReviewPass("regression", "pass", "duplicate proof")
            )
            report = publish_scrutiny.scrutinize_publish(
                **_packet(_plan(Path(tmp)), review_passes=reviews)
            )

        self.assertFalse(report["ready"])
        self.assertEqual(report["duplicate_review_passes"], ["regression"])

    def test_task_must_be_present_in_owning_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = publish_scrutiny.scrutinize_publish(
                **_packet(_plan(Path(tmp)), task="5.3.0z")
            )

        self.assertFalse(report["ready"])
        self.assertFalse(report["checks"]["task_in_plan"])
        self.assertEqual(report["invalid_fields"][0]["field"], "task")
        self.assertIn("task row", report["invalid_fields"][0]["reason"])

    def test_task_mention_in_plan_prose_is_not_enough(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = _plan(Path(tmp))
            plan.write_text(
                plan.read_text(encoding="utf-8")
                + "\n## Drift Log\n"
                "- Actual: publish scrutiny previously accepted --task NO-SUCH-TASK "
                "because it appeared in prose.\n",
                encoding="utf-8",
            )
            report = publish_scrutiny.scrutinize_publish(
                **_packet(plan, task="NO-SUCH-TASK")
            )

        self.assertFalse(report["ready"])
        self.assertFalse(report["checks"]["task_in_plan"])
        self.assertEqual(report["invalid_fields"][0]["field"], "task")
        self.assertIn("task row", report["invalid_fields"][0]["reason"])

    def test_task_mention_in_progress_date_bullet_is_not_enough(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = _plan(Path(tmp))
            plan.write_text(
                "# Test Plan\n\n"
                "## Progress\n"
                "- [2026-06-02] GHOST-TASK completed in progress prose.\n",
                encoding="utf-8",
            )
            report = publish_scrutiny.scrutinize_publish(
                **_packet(plan, task="GHOST-TASK")
            )

        self.assertFalse(report["ready"])
        self.assertFalse(report["checks"]["task_in_plan"])
        self.assertEqual(report["invalid_fields"][0]["field"], "task")
        self.assertIn("task row", report["invalid_fields"][0]["reason"])

    def test_claims_must_be_file_paths_not_prose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = publish_scrutiny.scrutinize_publish(
                **_packet(
                    _plan(Path(tmp)),
                    claims=[
                        "M62 FirstBite failed-execute diagnosis helper: 11 failed lanes"
                    ],
                )
            )

        self.assertFalse(report["ready"])
        self.assertEqual(report["invalid_fields"][0]["field"], "claims")
        self.assertIn("not prose summaries", report["invalid_fields"][0]["reason"])

    def test_file_claimed_entries_must_be_file_paths_not_prose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = publish_scrutiny.scrutinize_publish(
                **_packet(_plan(Path(tmp)), files_claimed=["changed the docs and tests"])
            )

        self.assertFalse(report["ready"])
        self.assertEqual(report["invalid_fields"][0]["field"], "files_claimed")
        self.assertIn("changed the docs and tests", report["invalid_fields"][0]["reason"])

    def test_missing_claim_path_blocks_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = publish_scrutiny.scrutinize_publish(
                **_packet(_plan(Path(tmp)), claims=["docs/no-such-file.md"])
            )

        self.assertFalse(report["ready"])
        self.assertEqual(report["invalid_fields"][0]["field"], "claims")
        self.assertIn("existing paths", report["invalid_fields"][0]["reason"])

    def test_missing_file_claimed_path_blocks_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = publish_scrutiny.scrutinize_publish(
                **_packet(
                    _plan(Path(tmp)),
                    files_claimed=["scripts/no-such-publish-helper.py"],
                )
            )

        self.assertFalse(report["ready"])
        self.assertEqual(report["invalid_fields"][0]["field"], "files_claimed")
        self.assertIn(
            "scripts/no-such-publish-helper.py",
            report["checks"]["files_claimed_unresolved"],
        )

    def test_claims_must_include_file_claimed_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = publish_scrutiny.scrutinize_publish(
                **_packet(
                    _plan(Path(tmp)),
                    files_claimed=[
                        "scripts/vidux-publish-scrutiny.py",
                        "tests/test_publish_scrutiny.py",
                    ],
                    claims=["scripts/vidux-publish-scrutiny.py"],
                )
            )

        self.assertFalse(report["ready"])
        self.assertEqual(report["invalid_fields"][0]["field"], "claims")
        self.assertIn("must include every", report["invalid_fields"][0]["reason"])
        self.assertIn(
            str(ROOT / "tests/test_publish_scrutiny.py"),
            report["checks"]["claims_missing_files_claimed"],
        )

    def test_git_known_deleted_claim_path_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = _plan(root)
            deleted = root / "deleted-doc.md"
            deleted.write_text("removed doc\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                ["git", "add", "PLAN.md", "deleted-doc.md"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            deleted.unlink()

            report = publish_scrutiny.scrutinize_publish(
                **_packet(
                    plan,
                    plan_path="PLAN.md",
                    files_claimed=["deleted-doc.md"],
                    claims=["deleted-doc.md"],
                    cwd=root,
                )
            )

        self.assertTrue(report["ready"], report)
        self.assertEqual(report["checks"]["files_claimed_unresolved"], [])
        self.assertEqual(report["checks"]["claims_unresolved"], [])

    def test_cli_outputs_json_and_nonzero_when_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = _plan(Path(tmp))
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--lane",
                    "vidux-self-improvement",
                    "--task",
                    "5.3.0n",
                    "--summary",
                    "publish self-scrutiny preflight",
                    "--plan-path",
                    str(plan),
                    "--proof",
                    "python3 -m unittest tests.test_publish_scrutiny",
                    "--ledger",
                    "evt_selfscrutiny",
                    "--handoff-status",
                    "done",
                    "--file-claimed",
                    "scripts/vidux-publish-scrutiny.py",
                    "--claim",
                    "PLAN.md",
                    "--claim",
                    "scripts/vidux-publish-scrutiny.py",
                    "--resume",
                    "continue 5.3.1",
                    "--review-pass",
                    "invariant-audit:pass:plan and ledger propagated",
                    "--review-pass",
                    "regression-runner:pass:tests passed",
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["ready"])
        self.assertEqual(report["missing_review_passes"], ["adversarial"])

    def test_cli_reports_missing_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = _plan(Path(tmp))
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--lane",
                    "vidux-self-improvement",
                    "--task",
                    "5.3.0n",
                    "--plan-path",
                    str(plan),
                    "--proof",
                    "python3 -m unittest tests.test_publish_scrutiny",
                    "--ledger",
                    "evt_selfscrutiny",
                    "--handoff-status",
                    "done",
                    "--file-claimed",
                    "scripts/vidux-publish-scrutiny.py",
                    "--claim",
                    "PLAN.md",
                    "--claim",
                    "scripts/vidux-publish-scrutiny.py",
                    "--resume",
                    "continue 5.3.1",
                    "--review-pass",
                    "invariant-audit:pass:plan and ledger propagated",
                    "--review-pass",
                    "regression-runner:pass:tests passed",
                    "--review-pass",
                    "adversarial-reviewer:pass:no missing publish fields",
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["ready"])
        self.assertEqual(report["missing_fields"], ["summary"])

    def test_main_empty_argv_does_not_read_process_argv(self) -> None:
        """Programmatic main([]) must not fall back to ambient sys.argv."""
        with tempfile.TemporaryDirectory() as tmp:
            plan = _plan(Path(tmp))
            original_argv = sys.argv[:]
            sys.argv = [
                "probe",
                "--lane",
                "vidux-self-improvement",
                "--task",
                "5.3.0n",
                "--summary",
                "publish self-scrutiny preflight",
                "--plan-path",
                str(plan),
                "--proof",
                "python3 -m unittest tests.test_publish_scrutiny",
                "--ledger",
                "evt_selfscrutiny",
                "--handoff-status",
                "done",
                "--file-claimed",
                "scripts/vidux-publish-scrutiny.py",
                "--claim",
                "PLAN.md",
                "--claim",
                "scripts/vidux-publish-scrutiny.py",
                "--resume",
                "continue 5.3.1",
                "--review-pass",
                "invariant-audit:pass:plan and ledger propagated",
                "--review-pass",
                "regression-runner:pass:tests passed",
                "--review-pass",
                "adversarial-reviewer:pass:no missing publish fields",
                "--json",
            ]
            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                with (
                    self.assertRaises(SystemExit) as raised,
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    publish_scrutiny.main([])
            finally:
                sys.argv = original_argv

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("the following arguments are required", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
