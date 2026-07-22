"""
Tests for the schedulewakeup_doctrine_intact check + the json_escape fix in
scripts/vidux-doctor.sh.

json_escape bug: vidux-doctor.sh called json_escape (used by
_check_cadence_runtime's warn path) but never defined it -- only
vidux-loop.sh has it. The failure was silently swallowed by set -e's
command-substitution semantics, so warn-path "details" fields came back
empty instead of erroring loudly. Fixed by defining json_escape locally in
vidux-doctor.sh; these tests pin that fix and the new check that depends on
it working correctly.

Each test builds a minimal, disposable copy of just the files vidux-doctor.sh
needs (not a full repo clone) in a tempdir, so this stays fast and doesn't
touch the real repo's docs or any machine-local automation state.

Run:
    python3 -m unittest tests.test_doctor_checks -v
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCTOR = ROOT / "scripts" / "vidux-doctor.sh"


def build_fixture(
    tmp_dir,
    automation_doctrine_intact=True,
    lifecycle_doctrine_intact=True,
    delete_automation_doc=False,
    delete_lifecycle_doc=False,
):
    """Build a minimal vidux-root-shaped tree with just what vidux-doctor.sh needs."""
    root = Path(tmp_dir)
    (root / "guides").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "fleet").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)

    shutil.copy(DOCTOR, root / "scripts" / "vidux-doctor.sh")

    if not delete_automation_doc:
        automation_line = (
            "- `CronCreate` over `ScheduleWakeup` for >=10 fires (CronCreate = fresh session per fire)\n"
            if automation_doctrine_intact
            else "- some unrelated automation guidance\n"
        )
        (root / "guides" / "automation.md").write_text(f"# Automation\n\n{automation_line}")

    if not delete_lifecycle_doc:
        lifecycle_row = (
            "| JSONL growing fast | Ship cycles or ScheduleWakeup bloat | Prefer `CronCreate` over `ScheduleWakeup` for 10+ fires |\n"
            if lifecycle_doctrine_intact
            else "| JSONL growing fast | Ship cycles or ScheduleWakeup bloat | Prefer the faster scheduler |\n"
        )
        (root / "docs" / "fleet" / "claude-lifecycle.md").write_text(
            f"# Lifecycle\n\n## Troubleshooting\n\n| Symptom | Cause | Fix |\n|---|---|---|\n{lifecycle_row}"
        )
    return root


def run_doctor(root):
    result = subprocess.run(
        ["bash", str(root / "scripts" / "vidux-doctor.sh"), "--json", "--repo", str(root)],
        capture_output=True, text=True, timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


def find_check(payload, check_id):
    for c in payload["checks"]:
        if c["id"] == check_id:
            return c
    return None


class SchedulewakeupDoctrineCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_passes_when_both_canonical_locations_intact(self):
        root = build_fixture(self._tmp.name)
        rc, out, err = run_doctor(root)
        self.assertNotIn("json_escape: command not found", err)
        payload = json.loads(out)
        check = find_check(payload, "schedulewakeup_doctrine_intact")
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "pass")

    def test_warns_when_automation_doc_missing_doctrine(self):
        root = build_fixture(self._tmp.name, automation_doctrine_intact=False)
        _rc, out, err = run_doctor(root)
        self.assertNotIn("command not found", err)
        payload = json.loads(out)
        check = find_check(payload, "schedulewakeup_doctrine_intact")
        self.assertEqual(check["status"], "warn")
        self.assertIn("guides/automation.md", check["details"])

    def test_warns_when_lifecycle_doc_missing_doctrine(self):
        root = build_fixture(self._tmp.name, lifecycle_doctrine_intact=False)
        _rc, out, _err = run_doctor(root)
        payload = json.loads(out)
        check = find_check(payload, "schedulewakeup_doctrine_intact")
        self.assertEqual(check["status"], "warn")
        self.assertIn("claude-lifecycle.md", check["details"])

    def test_warns_and_names_both_when_both_missing(self):
        root = build_fixture(
            self._tmp.name, automation_doctrine_intact=False, lifecycle_doctrine_intact=False
        )
        _rc, out, _err = run_doctor(root)
        payload = json.loads(out)
        check = find_check(payload, "schedulewakeup_doctrine_intact")
        self.assertEqual(check["status"], "warn")
        self.assertIn("guides/automation.md", check["details"])
        self.assertIn("claude-lifecycle.md", check["details"])

    # -- regression found by adversarial (Claude subagent) review, 2026-07-08 #

    def test_warns_when_automation_doc_is_deleted_entirely(self):
        # `[[ -f "$doc" ]] &&` short-circuits false on a missing file, so a
        # whole-file deletion previously read as "doctrine intact" -- the
        # opposite of what the check's own comment promises ("catches silent
        # doctrine drift/deletion"). A deleted doc must flag, not pass.
        root = build_fixture(self._tmp.name, delete_automation_doc=True)
        _rc, out, _err = run_doctor(root)
        payload = json.loads(out)
        check = find_check(payload, "schedulewakeup_doctrine_intact")
        self.assertEqual(check["status"], "warn")
        self.assertIn("guides/automation.md", check["details"])

    def test_warns_when_lifecycle_doc_is_deleted_entirely(self):
        root = build_fixture(self._tmp.name, delete_lifecycle_doc=True)
        _rc, out, _err = run_doctor(root)
        payload = json.loads(out)
        check = find_check(payload, "schedulewakeup_doctrine_intact")
        self.assertEqual(check["status"], "warn")
        self.assertIn("claude-lifecycle.md", check["details"])


class JsonEscapeFunctionTests(unittest.TestCase):
    """Direct unit coverage of the json_escape fix, sourced from the real file
    (not a hand-copied duplicate) so this pins the actual shipped function."""

    def setUp(self):
        # Extract just the json_escape() { ... } block from the real script
        # into a real temp file and source that -- avoids running the full
        # doctor script (which would execute every check) just to unit-test
        # one function, and avoids process-substitution timing flakiness.
        extracted = subprocess.run(
            ["sed", "-n", "/^json_escape()/,/^}/p", str(DOCTOR)],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        self.assertTrue(extracted.strip(), "failed to extract json_escape from vidux-doctor.sh")
        self._fn_file = tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False)
        self._fn_file.write(extracted)
        self._fn_file.close()
        self.addCleanup(lambda: Path(self._fn_file.name).unlink(missing_ok=True))

    def _escape(self, raw):
        result = subprocess.run(
            ["bash", "-c", f'source {self._fn_file.name}; json_escape "$1"', "--", raw],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_escapes_double_quotes(self):
        self.assertEqual(self._escape('say "hi"'), 'say \\"hi\\"')

    def test_escapes_backslashes(self):
        self.assertEqual(self._escape("a\\b"), "a\\\\b")

    def test_plain_text_passes_through_unchanged(self):
        self.assertEqual(self._escape("guides/automation.md"), "guides/automation.md")


if __name__ == "__main__":
    unittest.main()
