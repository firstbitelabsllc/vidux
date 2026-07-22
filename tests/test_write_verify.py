"""
Tests for scripts/vidux-write-verify.sh (Recipe 9: Edit-Then-Verify, mechanized).

Style matches test_plan_guard.py: stdlib unittest, no pip, subprocess against
the real script.

Run:
    python3 -m unittest tests.test_write_verify -v
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "vidux-write-verify.sh"


def run_check(*args):
    result = subprocess.run(
        ["bash", str(SCRIPT), "check", *args],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


class WriteVerifyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_missing_file_fails(self):
        rc, out, _err = run_check(str(self.dir / "nope.txt"), "--json")
        self.assertEqual(rc, 1)
        payload = json.loads(out)
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["reason"], "missing")

    def test_zero_byte_file_fails(self):
        f = self.dir / "empty.txt"
        f.touch()
        rc, out, _err = run_check(str(f), "--json")
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["reason"], "empty")

    def test_below_min_bytes_fails(self):
        f = self.dir / "small.txt"
        f.write_text("hi")
        rc, out, _err = run_check(str(f), "--min-bytes", "100", "--json")
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["reason"], "too_small")

    def test_meets_min_bytes_passes(self):
        f = self.dir / "small.txt"
        f.write_text("hi")
        rc, out, _err = run_check(str(f), "--min-bytes", "2", "--json")
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(out)["passed"])

    def test_missing_expected_content_fails(self):
        f = self.dir / "report.md"
        f.write_text("hello world\n")
        rc, out, _err = run_check(str(f), "--contains", "## Summary", "--json")
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["reason"], "missing_expected_content")

    def test_present_expected_content_passes(self):
        f = self.dir / "report.md"
        f.write_text("## Summary\nAll good.\n")
        rc, out, _err = run_check(str(f), "--contains", "## Summary", "--json")
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(out)["passed"])

    def test_default_min_bytes_is_one_nonempty_passes(self):
        f = self.dir / "x.txt"
        f.write_text("a")
        rc, _out, _err = run_check(str(f))
        self.assertEqual(rc, 0)

    def test_human_readable_output_without_json_flag(self):
        f = self.dir / "empty.txt"
        f.touch()
        rc, _out, err = run_check(str(f))
        self.assertEqual(rc, 1)
        self.assertIn("WRITE-VERIFY FAILED", err)
        self.assertIn("Recipe 9", err)

    # -- regressions found by adversarial (Claude subagent) review, 2026-07-08 #

    def test_contains_value_starting_with_dash_is_not_misparsed_as_grep_flag(self):
        # Realistic content legitimately starts with '-': a markdown rule
        # ("---"), a PEM header ("-----BEGIN"), a diff line. Without a `--`
        # sentinel before the pattern, grep -F consumes "-x" as a flag instead
        # of a literal search string and the check false-fails even though
        # the content is present.
        f = self.dir / "f.txt"
        f.write_text("hello -x world\n")
        rc, out, _err = run_check(str(f), "--contains", "-x", "--json")
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(out)["passed"])

    def test_missing_value_for_min_bytes_is_usage_error(self):
        f = self.dir / "f.txt"
        f.write_text("hi")
        rc, _out, err = run_check(str(f), "--min-bytes")
        self.assertEqual(rc, 2, err)

    def test_missing_value_for_contains_is_usage_error(self):
        f = self.dir / "f.txt"
        f.write_text("hi")
        rc, _out, err = run_check(str(f), "--contains")
        self.assertEqual(rc, 2, err)

    def test_non_integer_min_bytes_is_usage_error_not_silent_pass(self):
        # A malformed --min-bytes must fail loud (exit 2, usage error) --
        # not silently skip the size check while still reporting passed:true,
        # which is the dangerous direction: the guard didn't run but the
        # caller is told it did.
        f = self.dir / "f.txt"
        f.write_text("hi")
        rc, _out, err = run_check(str(f), "--min-bytes", "abc")
        self.assertEqual(rc, 2, err)
        self.assertIn("integer", err)


if __name__ == "__main__":
    unittest.main()
