"""
Tests for scripts/vidux-status.py focus bucketing.

Style matches test_plan_guard.py: stdlib unittest, no pip, subprocess against
the real script. Each test builds a disposable repo in a tempdir.

Run:
    python3 -m unittest tests.test_status_focus -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "vidux-status.py"

PLAN_BODY = """# My Project

## Purpose
Test plan.

## Tasks
- [pending] Task 1: do the thing [Evidence: seeded]

## Decision Log
## Progress
"""


def run_status(cwd, *args):
    """Run vidux-status.py from `cwd`. Returns (returncode, stdout, stderr)."""
    env = {k: v for k, v in os.environ.items() if k != "VIDUX_DEV_ROOT"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


class StatusFocusTests(unittest.TestCase):
    def _make_repo(self, root, name):
        repo = Path(root) / name
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "PLAN.md").write_text(PLAN_BODY, encoding="utf-8")
        return repo

    def test_relative_root_ties_cwd_repo_plan(self):
        # Regression: `vidux status --root .` inside a repo whose PLAN.md sits
        # at the repo root used to show that plan under "Other tracked plans"
        # with the literal short name "PLAN.md" — an unresolved relative root
        # has an empty `.name`, so the short-name fallback chain bottomed out
        # and the tied-bucket match against the cwd repo name never fired.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_repo(tmp, "myproject")
            rc, out, err = run_status(repo, "--root", ".", "--json")
        self.assertEqual(rc, 0, err)
        payload = json.loads(out)
        tied_shorts = [p["short"] for p in payload["tied"]]
        self.assertIn("myproject", tied_shorts, payload)
        self.assertEqual(payload["other"], [], payload)

    def test_absolute_root_ties_cwd_repo_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._make_repo(tmp, "myproject")
            rc, out, err = run_status(repo, "--root", str(repo), "--json")
        self.assertEqual(rc, 0, err)
        payload = json.loads(out)
        self.assertIn("myproject", [p["short"] for p in payload["tied"]], payload)


if __name__ == "__main__":
    unittest.main()
