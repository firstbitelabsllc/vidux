"""Tests for scripts/vidux-pr-body.py."""

from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "vidux-pr-body.py"

# A fixture plan, not the repository's live PLAN.md: these tests only need a
# plan file containing the expected task rows, and must keep passing when the
# repo's own plan content changes. Absolute, so `ROOT / VALID_PLAN` joins
# collapse to this path at every existing call site.
_PLAN_FIXTURE_DIR = tempfile.TemporaryDirectory()
VALID_PLAN = str(Path(_PLAN_FIXTURE_DIR.name) / "PLAN.md")
VALID_TASK = "5.3.0am"
DEFAULT_SUMMARY = "update templates"
TEAM_PLAN = VALID_PLAN
TEAM_TASK = "5.3.0ad"
Path(VALID_PLAN).write_text(
    "# Plan fixture\n\n## Tasks\n"
    f"- [in_progress] {VALID_TASK} harden the PR body script\n"
    f"- [in_progress] {TEAM_TASK} pr-body team hardening\n",
    encoding="utf-8",
)
REVIEW_PASSES = [
    "invariant-audit:pass:plan row, ledger eid, proof, files, and resume point recorded",
    "regression-runner:pass:python3 -m unittest tests.test_pr_body",
    "adversarial-reviewer:pass:no overclaim, stale proof, duplicate plan, or unsafe publish found",
]

spec = importlib.util.spec_from_file_location("vidux_pr_body", SCRIPT)
assert spec is not None
pr_body = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = pr_body
spec.loader.exec_module(pr_body)


class PrBodyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_vidux_ledger_file = os.environ.get("VIDUX_LEDGER_FILE")
        cls._ledger_tmp = tempfile.TemporaryDirectory()
        ledger_root = Path(cls._ledger_tmp.name)
        ledger_path = ledger_root / "activity.jsonl"
        rows = [
            {
                "eid": "evt_123abc",
                "event": "publish",
                "lane": "codex/pr-body-hardening",
                "task_id": TEAM_TASK,
                "summary": DEFAULT_SUMMARY,
                "plan_path": str(ROOT / TEAM_PLAN),
                "proof": "python3 -m unittest tests.test_pr_body",
                "handoff_status": "needs_review",
                "next_agent_resume": "nurse CI and reply to review findings",
                "files_claimed": [
                    str(ROOT / "scripts/vidux-pr-body.py"),
                    str(ROOT / "tests/test_pr_body.py"),
                ],
            },
            {
                "eid": "evt_ok",
                "event": "publish",
                "lane": "codex/pr-body-hardening",
                "task_id": VALID_TASK,
                "summary": DEFAULT_SUMMARY,
                "plan_path": str(ROOT / VALID_PLAN),
                "proof": "proof",
                "handoff_status": "done",
                "next_agent_resume": "nurse CI",
                "files_claimed": [str(ROOT / VALID_PLAN)],
            },
            {
                "eid": "evt_456",
                "event": "publish",
                "lane": "codex/test",
                "task_id": VALID_TASK,
                "summary": "ship fix",
                "plan_path": str(ROOT / VALID_PLAN),
                "proof": "python3 -m unittest tests.test_pr_body",
                "handoff_status": "done",
                "next_agent_resume": "fix checks",
                "files_claimed": [str(ROOT / "scripts/vidux-pr-body.py")],
            },
            {
                "eid": "evt_wrong_task",
                "event": "publish",
                "lane": "codex/pr-body-hardening",
                "task_id": "5.3.0az",
                "summary": DEFAULT_SUMMARY,
                "plan_path": str(ROOT / VALID_PLAN),
                "proof": "proof",
                "handoff_status": "done",
                "next_agent_resume": "nurse CI",
                "files_claimed": [str(ROOT / VALID_PLAN)],
            },
            {
                "eid": "evt_wrong_proof",
                "event": "publish",
                "lane": "codex/pr-body-hardening",
                "task_id": VALID_TASK,
                "summary": DEFAULT_SUMMARY,
                "plan_path": str(ROOT / VALID_PLAN),
                "proof": "old proof",
                "handoff_status": "done",
                "next_agent_resume": "nurse CI",
                "files_claimed": [str(ROOT / VALID_PLAN)],
            },
            {
                "eid": "evt_wrong_resume",
                "event": "publish",
                "lane": "codex/pr-body-hardening",
                "task_id": VALID_TASK,
                "summary": DEFAULT_SUMMARY,
                "plan_path": str(ROOT / VALID_PLAN),
                "proof": "proof",
                "handoff_status": "done",
                "next_agent_resume": "resume a different packet",
                "files_claimed": [str(ROOT / VALID_PLAN)],
            },
            {
                "eid": "evt_wrong_summary",
                "event": "publish",
                "lane": "codex/pr-body-hardening",
                "task_id": VALID_TASK,
                "summary": "old summary",
                "plan_path": str(ROOT / VALID_PLAN),
                "proof": "proof",
                "handoff_status": "done",
                "next_agent_resume": "nurse CI",
                "files_claimed": [str(ROOT / VALID_PLAN)],
            },
            {
                "eid": "evt_wrong_event",
                "event": "stop",
                "lane": "codex/pr-body-hardening",
                "task_id": VALID_TASK,
                "summary": DEFAULT_SUMMARY,
                "plan_path": str(ROOT / VALID_PLAN),
                "proof": "proof",
                "handoff_status": "done",
                "next_agent_resume": "nurse CI",
                "files_claimed": [str(ROOT / VALID_PLAN)],
            },
            {
                "eid": "evt_wrong_files",
                "event": "publish",
                "lane": "codex/pr-body-hardening",
                "task_id": VALID_TASK,
                "summary": DEFAULT_SUMMARY,
                "plan_path": str(ROOT / VALID_PLAN),
                "proof": "proof",
                "handoff_status": "done",
                "next_agent_resume": "nurse CI",
                "files": [str(ROOT / "docs/reference/scripts.md")],
                "files_claimed": [str(ROOT / VALID_PLAN)],
            },
        ]
        for row in rows:
            row.setdefault("files", list(row["files_claimed"]))
        ledger_path.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
        archive_path = ledger_root / "archive" / "evicted.jsonl"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(
            json.dumps(
                {
                    "eid": "evt_archived_ok",
                    "event": "publish",
                    "lane": "codex/pr-body-hardening",
                    "task_id": VALID_TASK,
                    "summary": DEFAULT_SUMMARY,
                    "plan_path": str(ROOT / VALID_PLAN),
                    "proof": "proof",
                    "handoff_status": "done",
                    "next_agent_resume": "nurse CI",
                    "files": [str(ROOT / VALID_PLAN)],
                    "files_claimed": [str(ROOT / VALID_PLAN)],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["VIDUX_LEDGER_FILE"] = str(ledger_path)

    @classmethod
    def tearDownClass(cls):
        if cls._old_vidux_ledger_file is None:
            os.environ.pop("VIDUX_LEDGER_FILE", None)
        else:
            os.environ["VIDUX_LEDGER_FILE"] = cls._old_vidux_ledger_file
        cls._ledger_tmp.cleanup()

    def test_builds_ready_pr_body_with_publish_ref(self):
        body = pr_body.build_pr_body(
            lane="codex/pr-body-hardening",
            task=TEAM_TASK,
            summary=DEFAULT_SUMMARY,
            plan_path=TEAM_PLAN,
            proof="python3 -m unittest tests.test_pr_body",
            handoff_status="needs_review",
            ledger="evt_123abc",
            files_claimed=["scripts/vidux-pr-body.py", "tests/test_pr_body.py"],
            resume="nurse CI and reply to review findings",
            changes=["update templates", "add helper"],
            review_passes=REVIEW_PASSES,
        )

        self.assertIn("Lane: codex/pr-body-hardening", body)
        self.assertIn(f"Plan task: {TEAM_TASK}", body)
        self.assertIn("## Publish Propagation", body)
        self.assertIn(f"Summary: {DEFAULT_SUMMARY}", body)
        self.assertIn(f"Plan path: {TEAM_PLAN}", body)
        self.assertIn("Proof: python3 -m unittest tests.test_pr_body", body)
        self.assertIn("Ledger: evt_123abc", body)
        self.assertIn("Handoff status: needs_review", body)
        self.assertIn("- scripts/vidux-pr-body.py", body)
        self.assertIn("## Self-Scrutiny", body)
        self.assertIn("- Invariant audit: pass - plan row, ledger eid", body)
        self.assertIn("- Regression runner: pass - python3 -m unittest tests.test_pr_body", body)
        self.assertIn("- Adversarial reviewer: pass - no overclaim", body)
        self.assertIn("Resume point: nurse CI and reply to review findings", body)
        self.assertIn("- update templates", body)
        self.assertTrue(body.endswith("\n"))

    def test_rejects_missing_file_claims(self):
        with self.assertRaises(ValueError):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_ok",
                files_claimed=[],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_rejects_prose_file_claims(self):
        with self.assertRaisesRegex(ValueError, "file/path-like"):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_ok",
                files_claimed=["updated plan row and proof trail"],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_rejects_missing_file_claim_path(self):
        with self.assertRaisesRegex(ValueError, "existing path or git-known deleted path"):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_ok",
                files_claimed=["docs/no-such-pr-body-claim.md"],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_git_known_deleted_file_claim_path_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "PLAN.md").write_text(
                "# Plan\n- [pending] LI-5 deletion handoff\n",
                encoding="utf-8",
            )
            deleted_doc = root / "deleted-doc.md"
            deleted_doc.write_text("old doc\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(
                ["git", "add", "PLAN.md", "deleted-doc.md"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            deleted_doc.unlink()
            ledger = root / "activity.jsonl"
            ledger.write_text(
                json.dumps(
                    {
                        "eid": "evt_deleted_doc",
                        "event": "publish",
                        "lane": "codex/pr-body-hardening",
                        "task_id": "LI-5",
                        "summary": DEFAULT_SUMMARY,
                        "plan_path": str(root / "PLAN.md"),
                        "proof": "proof",
                        "handoff_status": "done",
                        "next_agent_resume": "nurse CI",
                        "files": [str(root / "deleted-doc.md")],
                        "files_claimed": [str(root / "deleted-doc.md")],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            body = pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task="LI-5",
                summary=DEFAULT_SUMMARY,
                plan_path="PLAN.md",
                proof="proof",
                handoff_status="done",
                ledger="evt_deleted_doc",
                files_claimed=["deleted-doc.md"],
                resume="nurse CI",
                changes=["delete obsolete doc"],
                review_passes=REVIEW_PASSES,
                cwd=root,
                ledger_paths=[ledger],
            )

        self.assertIn("- deleted-doc.md", body)

    def test_rejects_invalid_handoff_status(self):
        with self.assertRaises(ValueError):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="green",
                ledger="evt_ok",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_rejects_non_eid_ledger(self):
        with self.assertRaisesRegex(ValueError, "publish ledger eid"):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="will emit later",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_rejects_missing_ledger_eid(self):
        with self.assertRaisesRegex(ValueError, "hot/archive ledger"):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_missing_pr_body_test_20260602",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_rejects_existing_ledger_for_wrong_task(self):
        with self.assertRaisesRegex(ValueError, "ledger task_id must match"):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_wrong_task",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_rejects_existing_ledger_for_wrong_event(self):
        with self.assertRaisesRegex(ValueError, "ledger event must be publish"):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_wrong_event",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_rejects_existing_ledger_for_wrong_changed_files(self):
        with self.assertRaisesRegex(ValueError, "ledger files must include"):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_wrong_files",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_rejects_existing_ledger_for_wrong_summary(self):
        with self.assertRaisesRegex(ValueError, "ledger summary must match"):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_wrong_summary",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_rejects_existing_ledger_for_wrong_proof(self):
        with self.assertRaisesRegex(ValueError, "ledger proof must match"):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_wrong_proof",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_rejects_existing_ledger_for_wrong_resume(self):
        with self.assertRaisesRegex(ValueError, "ledger next_agent_resume must match"):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_wrong_resume",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_accepts_archived_ledger_eid(self):
        body = pr_body.build_pr_body(
            lane="codex/pr-body-hardening",
            task=VALID_TASK,
            summary=DEFAULT_SUMMARY,
            plan_path=VALID_PLAN,
            proof="proof",
            handoff_status="done",
            ledger="evt_archived_ok",
            files_claimed=[VALID_PLAN],
            resume="nurse CI",
            changes=["update templates"],
            review_passes=REVIEW_PASSES,
        )

        self.assertIn("Ledger: evt_archived_ok", body)

    def test_rejects_missing_review_passes(self):
        with self.assertRaises(ValueError):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_ok",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES[:2],
            )

    def test_rejects_failing_review_pass(self):
        with self.assertRaises(ValueError):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_ok",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=[
                    *REVIEW_PASSES[:2],
                    "adversarial-reviewer:fail:plan claims done before ledger eid exists",
                ],
            )

    def test_rejects_duplicate_review_pass(self):
        with self.assertRaises(ValueError):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_ok",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=[*REVIEW_PASSES, REVIEW_PASSES[0]],
            )

    def test_rejects_missing_plan_path(self):
        with self.assertRaisesRegex(ValueError, "existing plan file"):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task=VALID_TASK,
                summary=DEFAULT_SUMMARY,
                plan_path="docs/no-such-plan.md",
                proof="proof",
                handoff_status="done",
                ledger="evt_ok",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_rejects_task_missing_from_plan(self):
        with self.assertRaisesRegex(ValueError, "task must appear in plan_path"):
            pr_body.build_pr_body(
                lane="codex/pr-body-hardening",
                task="NO-SUCH-TASK",
                summary=DEFAULT_SUMMARY,
                plan_path=VALID_PLAN,
                proof="proof",
                handoff_status="done",
                ledger="evt_ok",
                files_claimed=[VALID_PLAN],
                resume="nurse CI",
                changes=["update templates"],
                review_passes=REVIEW_PASSES,
            )

    def test_rejects_task_mentioned_only_in_plan_prose(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "PLAN.md").write_text(
                "# Plan\n\n## Drift Log\n- Actual: --task GHOST-TASK in prose.\n",
                encoding="utf-8",
            )
            (root / "changed.md").write_text("change\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "task must appear in plan_path"):
                pr_body.build_pr_body(
                    lane="codex/pr-body-hardening",
                    task="GHOST-TASK",
                    summary=DEFAULT_SUMMARY,
                    plan_path="PLAN.md",
                    proof="proof",
                    handoff_status="done",
                    ledger="evt_ok",
                    files_claimed=["changed.md"],
                    resume="nurse CI",
                    changes=["update templates"],
                    review_passes=REVIEW_PASSES,
                    cwd=root,
                )

    def test_rejects_task_mentioned_only_in_progress_date_bullet(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "PLAN.md").write_text(
                "# Plan\n\n"
                "## Progress\n"
                "- [2026-06-02] GHOST-TASK completed in progress prose.\n",
                encoding="utf-8",
            )
            (root / "changed.md").write_text("change\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "task must appear in plan_path"):
                pr_body.build_pr_body(
                    lane="codex/pr-body-hardening",
                    task="GHOST-TASK",
                    summary=DEFAULT_SUMMARY,
                    plan_path="PLAN.md",
                    proof="proof",
                    handoff_status="done",
                    ledger="evt_ok",
                    files_claimed=["changed.md"],
                    resume="nurse CI",
                    changes=["update templates"],
                    review_passes=REVIEW_PASSES,
                    cwd=root,
                )

    def test_cli_prints_canonical_body(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--lane",
                "codex/test",
                "--task",
                VALID_TASK,
                "--summary",
                "ship fix",
                "--plan-path",
                VALID_PLAN,
                "--proof",
                "python3 -m unittest tests.test_pr_body",
                "--handoff-status",
                "done",
                "--ledger",
                "evt_456",
                "--file-claimed",
                "scripts/vidux-pr-body.py",
                "--review-pass",
                REVIEW_PASSES[0],
                "--review-pass",
                REVIEW_PASSES[1],
                "--review-pass",
                REVIEW_PASSES[2],
                "--resume",
                "fix checks",
                "--change",
                "ship fix",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Plan task: {VALID_TASK}", result.stdout)
        self.assertIn("Summary: ship fix", result.stdout)
        self.assertIn(f"Plan path: {VALID_PLAN}", result.stdout)
        self.assertIn("Ledger: evt_456", result.stdout)
        self.assertIn("## Self-Scrutiny", result.stdout)
        self.assertIn("- ship fix", result.stdout)

    def test_cli_help_names_ledger_eid_only(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Matching publish ledger eid", result.stdout)
        self.assertIn("hot/archive", result.stdout)
        self.assertNotIn("dry-run payload", result.stdout)
        self.assertNotIn("proof path", result.stdout)

    def test_cli_fails_without_summary(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--lane",
                "codex/test",
                "--task",
                VALID_TASK,
                "--plan-path",
                VALID_PLAN,
                "--proof",
                "python3 -m unittest tests.test_pr_body",
                "--handoff-status",
                "done",
                "--ledger",
                "evt_456",
                "--file-claimed",
                "scripts/vidux-pr-body.py",
                "--review-pass",
                REVIEW_PASSES[0],
                "--review-pass",
                REVIEW_PASSES[1],
                "--review-pass",
                REVIEW_PASSES[2],
                "--resume",
                "fix checks",
                "--change",
                "ship fix",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--summary", result.stderr)

    def test_cli_fails_for_missing_ledger_eid(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--lane",
                "codex/test",
                "--task",
                VALID_TASK,
                "--summary",
                "ship fix",
                "--plan-path",
                VALID_PLAN,
                "--proof",
                "python3 -m unittest tests.test_pr_body",
                "--handoff-status",
                "done",
                "--ledger",
                "evt_missing_pr_body_cli_test_20260602",
                "--file-claimed",
                "scripts/vidux-pr-body.py",
                "--review-pass",
                REVIEW_PASSES[0],
                "--review-pass",
                REVIEW_PASSES[1],
                "--review-pass",
                REVIEW_PASSES[2],
                "--resume",
                "fix checks",
                "--change",
                "ship fix",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("hot/archive ledger", result.stderr)

    def test_cli_fails_without_review_packet(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--lane",
                "codex/test",
                "--task",
                VALID_TASK,
                "--summary",
                "ship fix",
                "--plan-path",
                VALID_PLAN,
                "--proof",
                "python3 -m unittest tests.test_pr_body",
                "--handoff-status",
                "done",
                "--ledger",
                "evt_456",
                "--file-claimed",
                "scripts/vidux-pr-body.py",
                "--resume",
                "fix checks",
                "--change",
                "ship fix",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("missing review pass", result.stderr)

    def test_cli_fails_for_missing_file_claim_path(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--lane",
                "codex/test",
                "--task",
                VALID_TASK,
                "--summary",
                "ship fix",
                "--plan-path",
                VALID_PLAN,
                "--proof",
                "python3 -m unittest tests.test_pr_body",
                "--handoff-status",
                "done",
                "--ledger",
                "evt_456",
                "--file-claimed",
                "docs/no-such-pr-body-claim.md",
                "--review-pass",
                REVIEW_PASSES[0],
                "--review-pass",
                REVIEW_PASSES[1],
                "--review-pass",
                REVIEW_PASSES[2],
                "--resume",
                "fix checks",
                "--change",
                "ship fix",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("existing path or git-known deleted path", result.stderr)

    def test_cli_fails_for_missing_plan_path(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--lane",
                "codex/test",
                "--task",
                VALID_TASK,
                "--summary",
                "ship fix",
                "--plan-path",
                "docs/no-such-plan.md",
                "--proof",
                "python3 -m unittest tests.test_pr_body",
                "--handoff-status",
                "done",
                "--ledger",
                "evt_456",
                "--file-claimed",
                "scripts/vidux-pr-body.py",
                "--review-pass",
                REVIEW_PASSES[0],
                "--review-pass",
                REVIEW_PASSES[1],
                "--review-pass",
                REVIEW_PASSES[2],
                "--resume",
                "fix checks",
                "--change",
                "ship fix",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("existing plan file", result.stderr)

    def test_cli_fails_for_task_missing_from_plan(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--lane",
                "codex/test",
                "--task",
                "NO-SUCH-TASK",
                "--summary",
                "ship fix",
                "--plan-path",
                VALID_PLAN,
                "--proof",
                "python3 -m unittest tests.test_pr_body",
                "--handoff-status",
                "done",
                "--ledger",
                "evt_456",
                "--file-claimed",
                "scripts/vidux-pr-body.py",
                "--review-pass",
                REVIEW_PASSES[0],
                "--review-pass",
                REVIEW_PASSES[1],
                "--review-pass",
                REVIEW_PASSES[2],
                "--resume",
                "fix checks",
                "--change",
                "ship fix",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("task must appear in plan_path", result.stderr)

    def test_main_empty_argv_does_not_read_process_argv(self):
        """Programmatic main([]) must not render a body from ambient sys.argv."""
        original_argv = sys.argv[:]
        sys.argv = [
            "probe",
            "--lane",
            "codex/test",
            "--task",
            VALID_TASK,
            "--summary",
            "ship fix",
            "--plan-path",
            VALID_PLAN,
            "--proof",
            "python3 -m unittest tests.test_pr_body",
            "--handoff-status",
            "done",
            "--ledger",
            "evt_456",
            "--file-claimed",
            "scripts/vidux-pr-body.py",
            "--review-pass",
            REVIEW_PASSES[0],
            "--review-pass",
            REVIEW_PASSES[1],
            "--review-pass",
            REVIEW_PASSES[2],
            "--resume",
            "fix checks",
            "--change",
            "ship fix",
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with (
                self.assertRaises(SystemExit) as raised,
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                pr_body.main([])
        finally:
            sys.argv = original_argv

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("the following arguments are required", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
