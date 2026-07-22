"""
Tests for scripts/vidux-step-journal.sh and its checkpoint/loop wiring.

The step journal itself shipped with zero test coverage (CHANGELOG
[Unreleased]); this closes that gap and covers the two integration points
added alongside it:
  - vidux-loop.sh surfaces `step_journal.available` + `row` when resuming an
    [in_progress] task with an existing journal.
  - vidux-checkpoint.sh archives (clears) the journal on true completion
    (`done`/`done_with_concerns`), but leaves it alone on `blocked` since a
    blocked task may resume later.

Style matches test_plan_guard.py: stdlib unittest, no pip, subprocess against
the real scripts. VIDUX_JOURNAL_DIR is always pinned to a tempdir so these
tests never touch the real ~/.vidux/journals.

Run:
    python3 -m unittest tests.test_step_journal -v
"""

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
STEP_JOURNAL = SCRIPTS_DIR / "vidux-step-journal.sh"
LOOP = SCRIPTS_DIR / "vidux-loop.sh"
CHECKPOINT = SCRIPTS_DIR / "vidux-checkpoint.sh"


class StepJournalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.journal_dir = Path(self._tmp.name) / "journals"
        self.env = {**os.environ, "VIDUX_JOURNAL_DIR": str(self.journal_dir)}

    def run_sj(self, *args):
        result = subprocess.run(
            ["bash", str(STEP_JOURNAL), *args],
            capture_output=True, text=True, timeout=10, env=self.env,
        )
        return result.returncode, result.stdout, result.stderr

    # -- primitive: record / is-done / resume-point / status / clear -------- #

    def test_record_and_is_done(self):
        rc, _out, _err = self.run_sj("record", "row1", "step_a", "done")
        self.assertEqual(rc, 0)
        rc, _out, _err = self.run_sj("is-done", "row1", "step_a")
        self.assertEqual(rc, 0)

    def test_is_done_false_for_unrecorded_step(self):
        rc, _out, _err = self.run_sj("is-done", "row1", "never_recorded")
        self.assertNotEqual(rc, 0)

    def test_is_done_false_for_started_not_done(self):
        self.run_sj("record", "row1", "step_a", "started")
        rc, _out, _err = self.run_sj("is-done", "row1", "step_a")
        self.assertNotEqual(rc, 0)

    def test_resume_point_returns_first_not_done_step(self):
        self.run_sj("record", "row1", "step_a", "done")
        self.run_sj("record", "row1", "step_b", "started")
        rc, out, _err = self.run_sj("resume-point", "row1", "step_a,step_b,step_c")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "step_b")

    def test_resume_point_all_done_returns_done_marker(self):
        self.run_sj("record", "row1", "step_a", "done")
        self.run_sj("record", "row1", "step_b", "done")
        rc, out, _err = self.run_sj("resume-point", "row1", "step_a,step_b")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "DONE")

    def test_last_status_wins_on_re_record(self):
        # A step recorded 'started' then later 'done' must resolve to done --
        # is-done reads the LAST matching event, not the first.
        self.run_sj("record", "row1", "step_a", "started")
        self.run_sj("record", "row1", "step_a", "done")
        rc, _out, _err = self.run_sj("is-done", "row1", "step_a")
        self.assertEqual(rc, 0)

    def test_clear_archives_journal_with_bak_suffix(self):
        self.run_sj("record", "row1", "step_a", "done")
        journal_file = self.journal_dir / "row1.jsonl"
        self.assertTrue(journal_file.exists())
        rc, out, _err = self.run_sj("clear", "row1")
        self.assertEqual(rc, 0)
        self.assertIn("archived", out)
        self.assertFalse(journal_file.exists())
        backups = list(self.journal_dir.glob("row1.jsonl.*.bak"))
        self.assertEqual(len(backups), 1)

    def test_row_sanitization_handles_slashes_and_spaces(self):
        # Row names come from free-text PLAN.md task descriptions -- slashes
        # and spaces must not create nested paths or break the filename.
        rc, _out, _err = self.run_sj("record", "Ship the widget/v2", "step_a", "done")
        self.assertEqual(rc, 0)
        self.assertTrue((self.journal_dir / "Ship_the_widget_v2.jsonl").exists())

    def test_row_normalization_strips_trailing_bracket_tag(self):
        # Real PLAN.md task lines carry trailing annotation tags
        # ([Evidence: ...], [ETA: ...], [Depends: ...]) that get added/edited
        # WHILE a task is in_progress. A tagged row and its bare counterpart
        # must resolve to the same journal file, or a checkpoint clear called
        # with bare text silently orphans the tagged journal (adversarial
        # review, 2026-07-08).
        rc, _out, _err = self.run_sj("record", "Ship the widget [Evidence: fixture]", "step_a", "done")
        self.assertEqual(rc, 0)
        self.assertTrue((self.journal_dir / "Ship_the_widget.jsonl").exists())
        self.assertFalse((self.journal_dir / "Ship_the_widget_[Evidence:_fixture].jsonl").exists())

    def test_row_normalization_strips_multiple_trailing_tags(self):
        rc, _out, _err = self.run_sj("record", "Fix the bug [Depends: X] [ETA: 1h]", "step_a", "done")
        self.assertEqual(rc, 0)
        self.assertTrue((self.journal_dir / "Fix_the_bug.jsonl").exists())

    def test_row_normalization_leaves_bracket_free_text_unchanged(self):
        rc, _out, _err = self.run_sj("record", "Ship the widget", "step_a", "done")
        self.assertEqual(rc, 0)
        self.assertTrue((self.journal_dir / "Ship_the_widget.jsonl").exists())


class StepJournalWiringTests(unittest.TestCase):
    """Integration: vidux-loop.sh resume surfacing + vidux-checkpoint.sh retirement."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo_dir = Path(self._tmp.name)
        self.journal_dir = self.repo_dir / ".journals"
        self.env = {**os.environ, "VIDUX_JOURNAL_DIR": str(self.journal_dir)}
        subprocess.run(["git", "init", "-q"], cwd=self.repo_dir, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=self.repo_dir, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo_dir, check=True)
        self.plan = self.repo_dir / "PLAN.md"

    def write_plan(self, task_state="in_progress"):
        self.plan.write_text(textwrap.dedent(f"""\
            # Test Plan
            ## Purpose
            Fixture.
            ## Tasks
            - [{task_state}] Ship the widget
            ## Decision Log
            - [DIRECTION] [2026-01-01] fixture
            ## Progress
            - [2026-01-01] Cycle 1: fixture setup.
        """))
        subprocess.run(["git", "add", "-A"], cwd=self.repo_dir, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=self.repo_dir, check=True)

    def run_loop(self):
        result = subprocess.run(
            ["bash", str(LOOP), str(self.plan)],
            capture_output=True, text=True, timeout=10, env=self.env,
        )
        return result.returncode, result.stdout, result.stderr

    def run_checkpoint(self, task, summary, *extra_args):
        result = subprocess.run(
            ["bash", str(CHECKPOINT), str(self.plan), task, summary, *extra_args],
            capture_output=True, text=True, timeout=10, env=self.env, cwd=self.repo_dir,
        )
        return result.returncode, result.stdout, result.stderr

    def test_loop_reports_unavailable_when_no_journal_exists(self):
        self.write_plan(task_state="in_progress")
        rc, out, _err = self.run_loop()
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertFalse(data["step_journal"]["available"])

    def test_loop_surfaces_available_journal_on_resume(self):
        self.write_plan(task_state="in_progress")
        subprocess.run(
            ["bash", str(STEP_JOURNAL), "record", "Ship the widget", "fetch", "done"],
            env=self.env, check=True,
        )
        rc, out, _err = self.run_loop()
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertTrue(data["step_journal"]["available"])
        self.assertEqual(data["step_journal"]["row"], "Ship the widget")

    def test_loop_does_not_surface_journal_for_pending_task(self):
        # Availability is only meaningful for a resumed in_progress task --
        # a pending task hasn't started, so there's nothing to resume.
        self.write_plan(task_state="pending")
        subprocess.run(
            ["bash", str(STEP_JOURNAL), "record", "Ship the widget", "fetch", "done"],
            env=self.env, check=True,
        )
        rc, out, _err = self.run_loop()
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertFalse(data["step_journal"]["available"])

    def test_checkpoint_done_archives_journal(self):
        self.write_plan(task_state="in_progress")
        subprocess.run(
            ["bash", str(STEP_JOURNAL), "record", "Ship the widget", "fetch", "done"],
            env=self.env, check=True,
        )
        journal_file = self.journal_dir / "Ship_the_widget.jsonl"
        self.assertTrue(journal_file.exists())
        rc, _out, err = self.run_checkpoint("Ship the widget", "shipped it", "--status", "done")
        self.assertEqual(rc, 0, err)
        self.assertFalse(journal_file.exists())
        self.assertEqual(len(list(self.journal_dir.glob("Ship_the_widget.jsonl.*.bak"))), 1)

    def test_checkpoint_blocked_preserves_journal(self):
        self.write_plan(task_state="in_progress")
        subprocess.run(
            ["bash", str(STEP_JOURNAL), "record", "Ship the widget", "fetch", "done"],
            env=self.env, check=True,
        )
        journal_file = self.journal_dir / "Ship_the_widget.jsonl"
        rc, _out, err = self.run_checkpoint("Ship the widget", "waiting on API key", "--status", "blocked")
        self.assertEqual(rc, 0, err)
        self.assertTrue(journal_file.exists(), "blocked tasks may resume later -- journal must survive")

    def write_plan_with_tag(self, task_state="in_progress"):
        self.plan.write_text(textwrap.dedent(f"""\
            # Test Plan
            ## Purpose
            Fixture.
            ## Tasks
            - [{task_state}] Ship the widget [Evidence: fixture]
            ## Decision Log
            - [DIRECTION] [2026-01-01] fixture
            ## Progress
            - [2026-01-01] Cycle 1: fixture setup.
        """))
        subprocess.run(["git", "add", "-A"], cwd=self.repo_dir, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=self.repo_dir, check=True)

    def test_tagged_task_line_and_bare_checkpoint_key_to_same_journal(self):
        # Reproduces the orphaning failure mode: loop surfaces the tag-bearing
        # row (TASK_DESC keeps trailing tags), but the agent checkpoints with
        # the bare description -- the common real call shape, and a valid one
        # since checkpoint's own line-match is a substring grep. The two must
        # resolve to the same journal file so clear actually archives it
        # instead of leaving it permanently orphaned.
        self.write_plan_with_tag(task_state="in_progress")
        subprocess.run(
            ["bash", str(STEP_JOURNAL), "record", "Ship the widget [Evidence: fixture]", "fetch", "done"],
            env=self.env, check=True,
        )
        rc, out, _err = self.run_loop()
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertTrue(data["step_journal"]["available"])
        self.assertEqual(data["step_journal"]["row"], "Ship the widget [Evidence: fixture]")

        journal_file = self.journal_dir / "Ship_the_widget.jsonl"
        self.assertTrue(journal_file.exists())

        rc, _out, err = self.run_checkpoint("Ship the widget", "shipped it", "--status", "done")
        self.assertEqual(rc, 0, err)
        self.assertFalse(journal_file.exists(), "checkpoint clear must archive the tagged journal, not orphan it")
        self.assertEqual(len(list(self.journal_dir.glob("Ship_the_widget.jsonl.*.bak"))), 1)


if __name__ == "__main__":
    unittest.main()
