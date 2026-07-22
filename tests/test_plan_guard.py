"""
Tests for scripts/vidux-plan-guard.sh.

Style matches test_plan_gc.py: stdlib unittest, no pip, subprocess against the
real script. Each test builds a disposable plan dir in a tempdir.

Run:
    python3 -m unittest tests.test_plan_guard -v
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "vidux-plan-guard.sh"


def run_guard(*args):
    """Run vidux-plan-guard.sh. Returns (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def write_plan(plan_path, tasks, decision_log=None):
    """Write a minimal PLAN.md fixture. `tasks` is a list of FSM states."""
    lines = ["# Test Plan", "", "## Tasks"]
    for i, state in enumerate(tasks, start=1):
        lines.append(f"- [{state}] Task {i}")
    lines += ["", "## Decision Log"]
    for entry in decision_log or []:
        lines.append(entry)
    lines += ["", "## Progress", "- [2026-01-01] Cycle 1: fixture setup."]
    plan_path.write_text("\n".join(lines) + "\n")


class PlanGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.plan_dir = Path(self._tmp.name)
        self.plan = self.plan_dir / "PLAN.md"
        self.sidecar = self.plan_dir / ".plan-taskcount"

    def test_snapshot_writes_sidecar_with_current_count(self):
        write_plan(self.plan, ["pending", "pending", "completed"])
        rc, _out, _err = run_guard("snapshot", str(self.plan))
        self.assertEqual(rc, 0)
        self.assertTrue(self.sidecar.exists())
        data = json.loads(self.sidecar.read_text())
        self.assertEqual(data["count"], 3)

    def test_snapshot_does_not_count_decision_log_or_progress_bullets(self):
        # Decision Log / Progress lines also start with "- [" -- must not
        # inflate the task count (the same false-positive class the
        # 2026-06-02 retrospective found in vidux-plan-bank-audit.py).
        write_plan(
            self.plan,
            ["pending"],
            decision_log=["- [DIRECTION] [2026-01-01] some note", "- [STUCK] [2026-01-02] blocked"],
        )
        run_guard("snapshot", str(self.plan))
        data = json.loads(self.sidecar.read_text())
        self.assertEqual(data["count"], 1)

    def test_verify_establishes_baseline_when_no_sidecar_exists(self):
        write_plan(self.plan, ["pending", "pending"])
        rc, out, _err = run_guard("verify", str(self.plan), "--json")
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertFalse(payload["integrity_warning"])
        self.assertEqual(payload["reason"], "no_baseline")
        self.assertTrue(self.sidecar.exists())

    def test_verify_clean_when_count_unchanged(self):
        write_plan(self.plan, ["pending"] * 5)
        run_guard("snapshot", str(self.plan))
        rc, out, _err = run_guard("verify", str(self.plan), "--json")
        self.assertEqual(rc, 0)
        self.assertFalse(json.loads(out)["integrity_warning"])

    def test_verify_flags_unauthorized_drop_beyond_threshold(self):
        write_plan(self.plan, ["pending"] * 6)
        run_guard("snapshot", str(self.plan))
        write_plan(self.plan, ["pending"])  # drop of 5 > default threshold 3
        rc, out, _err = run_guard("verify", str(self.plan), "--json")
        self.assertEqual(rc, 1)
        payload = json.loads(out)
        self.assertTrue(payload["integrity_warning"])
        self.assertEqual(payload["drop"], 5)

    def test_verify_allows_drop_within_threshold(self):
        write_plan(self.plan, ["pending"] * 6)
        run_guard("snapshot", str(self.plan))
        write_plan(self.plan, ["pending"] * 4)  # drop of 2, threshold is 3
        rc, out, _err = run_guard("verify", str(self.plan), "--json")
        self.assertEqual(rc, 0)
        self.assertFalse(json.loads(out)["integrity_warning"])

    def test_verify_authorized_by_same_or_later_dated_deletion_entry(self):
        write_plan(self.plan, ["pending"] * 6)
        run_guard("snapshot", str(self.plan))
        data = json.loads(self.sidecar.read_text())
        snapshot_date = data["timestamp"][:10]
        write_plan(
            self.plan,
            ["pending"],
            decision_log=[f"- [DELETION] [{snapshot_date}] intentional scope cut"],
        )
        rc, out, _err = run_guard("verify", str(self.plan), "--json")
        self.assertEqual(rc, 0)
        self.assertFalse(json.loads(out)["integrity_warning"])

    def test_verify_authorized_by_bare_date_deletion_entry(self):
        # docs/reference/plan-fields.md's own template table taught an
        # unbracketed "[DELETION] YYYY-MM-DD ..." form (now fixed to match
        # the canonical bracketed form), so has_authorizing_deletion() must
        # tolerate an entry written against either doc rather than
        # false-positive an integrity warning on it.
        write_plan(self.plan, ["pending"] * 6)
        run_guard("snapshot", str(self.plan))
        data = json.loads(self.sidecar.read_text())
        snapshot_date = data["timestamp"][:10]
        write_plan(
            self.plan,
            ["pending"],
            decision_log=[f"- [DELETION] {snapshot_date} intentional scope cut"],
        )
        rc, out, _err = run_guard("verify", str(self.plan), "--json")
        self.assertEqual(rc, 0)
        self.assertFalse(json.loads(out)["integrity_warning"])

    def test_verify_not_authorized_by_stale_deletion_entry(self):
        write_plan(self.plan, ["pending"] * 6)
        run_guard("snapshot", str(self.plan))
        write_plan(
            self.plan,
            ["pending"],
            decision_log=["- [DELETION] [2020-01-01] an unrelated deletion from years ago"],
        )
        rc, out, _err = run_guard("verify", str(self.plan), "--json")
        self.assertEqual(rc, 1)
        self.assertTrue(json.loads(out)["integrity_warning"])

    def test_verify_missing_plan_is_usage_error(self):
        rc, _out, err = run_guard("verify", str(self.plan_dir / "nope.md"))
        self.assertEqual(rc, 2)
        self.assertIn("not found", err)

    def test_threshold_is_configurable_via_env(self):
        write_plan(self.plan, ["pending"] * 6)
        run_guard("snapshot", str(self.plan))
        write_plan(self.plan, ["pending"] * 5)  # drop of 1
        result = subprocess.run(
            ["bash", str(SCRIPT), "verify", str(self.plan), "--json"],
            capture_output=True,
            text=True,
            env={"VIDUX_PLAN_GUARD_THRESHOLD": "0", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
        )
        self.assertEqual(result.returncode, 1)
        self.assertTrue(json.loads(result.stdout)["integrity_warning"])

    # -- regressions found by adversarial (Grok) review, 2026-07-08 --------- #

    def test_counts_in_review_verify_and_merged_states(self):
        # SKILL.md's generator/evaluator and convergence-ladder FSMs use
        # [in_review], [verify], [merged] as real task-line states -- a
        # clobber that only removes tasks sitting in these states must not
        # be invisible to the guard.
        write_plan(self.plan, ["pending", "in_review", "verify", "merged"])
        rc, _out, _err = run_guard("snapshot", str(self.plan))
        self.assertEqual(rc, 0)
        data = json.loads(self.sidecar.read_text())
        self.assertEqual(data["count"], 4)

    def test_status_transition_to_in_review_is_not_a_false_positive_drop(self):
        # Six tasks all legitimately advancing from [pending] to [in_review]
        # is a status change, not a clobber -- the count must stay the same.
        write_plan(self.plan, ["pending"] * 6)
        run_guard("snapshot", str(self.plan))
        write_plan(self.plan, ["in_review"] * 6)
        rc, out, _err = run_guard("verify", str(self.plan), "--json")
        self.assertEqual(rc, 0)
        self.assertFalse(json.loads(out)["integrity_warning"])

    def test_exit_criteria_checkboxes_are_excluded_from_task_count(self):
        # vidux-loop.sh already excludes ## Exit Criteria from its own
        # HOT/COLD task counts (they're gate checkboxes, not tasks) -- the
        # guard must match that convention, or Exit Criteria lines pad the
        # count and can both mask a real clobber and cause false positives.
        self.plan.write_text(
            "# Test Plan\n\n## Tasks\n- [pending] real task\n\n"
            "## Exit Criteria\n- [ ] tests pass\n- [ ] docs updated\n- [ ] shipped\n\n"
            "## Decision Log\n\n## Progress\n- [2026-01-01] setup.\n"
        )
        run_guard("snapshot", str(self.plan))
        data = json.loads(self.sidecar.read_text())
        self.assertEqual(data["count"], 1, "Exit Criteria checkboxes must not be counted as tasks")

    def test_exit_criteria_does_not_mask_a_real_task_wipe(self):
        # Concrete failure mode from the review: wipe all real tasks but leave
        # Exit Criteria intact -- without the exclusion, the padded count
        # keeps the drop under threshold and the wipe goes undetected.
        self.plan.write_text(
            "# Test Plan\n\n## Tasks\n"
            "- [pending] a\n- [pending] b\n- [pending] c\n- [pending] d\n- [pending] e\n- [pending] f\n\n"
            "## Exit Criteria\n- [ ] tests pass\n- [ ] docs updated\n- [ ] shipped\n- [ ] reviewed\n- [ ] signed off\n\n"
            "## Decision Log\n\n## Progress\n- [2026-01-01] setup.\n"
        )
        run_guard("snapshot", str(self.plan))
        self.plan.write_text(
            "# Test Plan\n\n## Tasks\n\n"
            "## Exit Criteria\n- [ ] tests pass\n- [ ] docs updated\n- [ ] shipped\n- [ ] reviewed\n- [ ] signed off\n\n"
            "## Decision Log\n\n## Progress\n- [2026-01-01] setup.\n"
        )
        rc, out, _err = run_guard("verify", str(self.plan), "--json")
        self.assertEqual(rc, 1)
        self.assertTrue(json.loads(out)["integrity_warning"])

    def test_corrupt_sidecar_does_not_fail_open(self):
        # A corrupt/unparseable sidecar must not silently read as
        # previous_count=0 (which would make drop=0 and never warn again --
        # a safety guard failing open on its own baseline loss).
        write_plan(self.plan, ["pending"] * 6)
        self.sidecar.write_text("not valid json{{{")
        rc, out, _err = run_guard("verify", str(self.plan), "--json")
        self.assertEqual(rc, 1)
        payload = json.loads(out)
        self.assertTrue(payload["integrity_warning"])
        self.assertEqual(payload["reason"], "corrupt_baseline")
        # A fresh baseline must be written so the NEXT verify isn't stuck warning forever.
        self.assertEqual(json.loads(self.sidecar.read_text())["count"], 6)


if __name__ == "__main__":
    unittest.main()
