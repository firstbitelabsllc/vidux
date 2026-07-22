"""
Tests for scripts/vidux-init.sh.

Style matches test_write_verify.py: stdlib unittest, no pip, subprocess
against the real script with an isolated VIDUX_ROOT/cwd per test.

Run:
    python3 -m unittest tests.test_vidux_init -v
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "vidux-init.sh"


def run_init(vidux_root, cwd, *args, env_overrides=None):
    env = dict(os.environ)
    env["VIDUX_ROOT"] = str(vidux_root)
    env["HOME"] = str(Path(cwd).parent / "home")
    env["XDG_CONFIG_HOME"] = str(Path(cwd).parent / "xdg-config")
    env.pop("VIDUX_CONFIG", None)
    env.pop("VIDUX_PLAN_STORE", None)
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


class ViduxInitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.vidux_root = Path(self._tmp.name) / "vidux-checkout"
        self.vidux_root.mkdir()
        self.elsewhere = Path(self._tmp.name) / "my-real-app"
        self.elsewhere.mkdir()

    def test_slug_requires_explicit_persistent_store_and_never_writes_install_root(self):
        before = list(self.vidux_root.iterdir())

        rc, _out, err = run_init(self.vidux_root, self.elsewhere, "my-project")

        self.assertEqual(rc, 2)
        self.assertIn("requires an explicit persistent plan store", err)
        self.assertIn("vidux init --here", err)
        self.assertEqual(list(self.vidux_root.iterdir()), before)
        self.assertFalse((self.vidux_root / "projects").exists())

    def test_slug_explicit_plan_store_creates_outside_install_root(self):
        store = Path(self._tmp.name) / "plans"

        rc, out, err = run_init(
            self.vidux_root,
            self.elsewhere,
            "my-project",
            "--plan-store",
            str(store),
        )

        target = store / "my-project" / "PLAN.md"
        self.assertEqual(rc, 0, f"stderr={err}")
        self.assertTrue(target.is_file())
        self.assertIn(str(target), out)
        self.assertFalse((self.vidux_root / "projects").exists())

    def test_slug_uses_live_xdg_config_plan_store(self):
        store = Path(self._tmp.name) / "central-plans"
        config = Path(self._tmp.name) / "xdg-config" / "vidux" / "vidux.config.json"
        config.parent.mkdir(parents=True)
        config.write_text(
            '{"plan_store":{"mode":"external","path":"../../central-plans"}}',
            encoding="utf-8",
        )

        rc, _out, err = run_init(self.vidux_root, self.elsewhere, "my-project")

        self.assertEqual(rc, 0, f"stderr={err}")
        self.assertTrue((store / "my-project" / "PLAN.md").is_file())

    def test_slug_allows_explicit_repo_local_config_but_store_stays_external(self):
        store = Path(self._tmp.name) / "configured-plans"
        config = self.vidux_root / "vidux.config.json"
        config.write_text(
            '{"plan_store":{"mode":"local","path":"../configured-plans"}}',
            encoding="utf-8",
        )

        rc, _out, err = run_init(
            self.vidux_root,
            self.elsewhere,
            "my-project",
            env_overrides={"VIDUX_CONFIG": str(config)},
        )

        self.assertEqual(rc, 0, f"stderr={err}")
        self.assertTrue((store / "my-project" / "PLAN.md").is_file())

    def test_slug_rejects_plan_store_inside_install_root(self):
        target = self.vidux_root / "plans"

        rc, _out, err = run_init(
            self.vidux_root,
            self.elsewhere,
            "my-project",
            "--plan-store",
            str(target),
        )

        self.assertEqual(rc, 2)
        self.assertIn("must be outside the Vidux install", err)
        self.assertFalse(target.exists())

    def test_refuses_to_overwrite_in_explicit_store(self):
        store = Path(self._tmp.name) / "plans"
        args = ("my-project", "--plan-store", str(store))
        run_init(self.vidux_root, self.elsewhere, *args)
        rc, _out, err = run_init(self.vidux_root, self.elsewhere, *args)
        self.assertEqual(rc, 1)
        self.assertIn(str(store / "my-project" / "PLAN.md"), err)

    def test_template_has_canonical_sections(self):
        run_init(self.vidux_root, self.elsewhere, "--here")
        text = (self.elsewhere / "PLAN.md").read_text()
        for section in ("## Purpose", "## Evidence", "## Constraints",
                         "## Operator Brief", "## Outcome Scorecard", "## Tasks",
                         "## Decision Log", "## Progress"):
            self.assertIn(section, text)

        self.assertIn("- Outcome: Ship the first evidence-backed result for My Real App.", text)
        self.assertIn("| First evidence-backed result |", text)
        self.assertIn("| unproven | evidence/first-result.md |", text)

    def test_here_creates_cockpit_ready_plan_in_current_project(self):
        rc, out, err = run_init(self.vidux_root, self.elsewhere, "--here")

        self.assertEqual(rc, 0, f"stderr={err}")
        target = self.elsewhere / "PLAN.md"
        self.assertTrue(target.is_file())
        self.assertFalse((self.vidux_root / "projects").exists())
        self.assertIn(str(target), out)
        text = target.read_text(encoding="utf-8")
        self.assertIn("# My Real App", text)
        self.assertIn("## Operator Brief", text)
        self.assertIn("- Status: watching", text)

    def test_here_refuses_to_overwrite_repo_plan(self):
        target = self.elsewhere / "PLAN.md"
        target.write_text("# Existing\n", encoding="utf-8")

        rc, _out, err = run_init(self.vidux_root, self.elsewhere, "--here")

        self.assertEqual(rc, 1)
        self.assertIn(str(target), err)
        self.assertEqual(target.read_text(encoding="utf-8"), "# Existing\n")

    def test_here_refuses_dangling_plan_symlink(self):
        target = self.elsewhere / "PLAN.md"
        outside = Path(self._tmp.name) / "outside-plan.md"
        target.symlink_to(outside)

        rc, _out, err = run_init(self.vidux_root, self.elsewhere, "--here")

        self.assertEqual(rc, 1)
        self.assertIn(str(target), err)
        self.assertTrue(target.is_symlink())
        self.assertFalse(outside.exists())

    def test_invalid_slug_rejected(self):
        rc, _out, err = run_init(self.vidux_root, self.elsewhere, "Not Valid!")
        self.assertEqual(rc, 2)
        self.assertIn("invalid slug", err)

    def test_here_succeeds_with_read_only_packaged_root(self):
        self.vidux_root.chmod(0o555)
        try:
            rc, out, err = run_init(self.vidux_root, self.elsewhere, "--here")
        finally:
            self.vidux_root.chmod(0o755)

        self.assertEqual(rc, 0, f"stderr={err}")
        self.assertIn(str(self.elsewhere / "PLAN.md"), out)
        self.assertTrue((self.elsewhere / "PLAN.md").is_file())
        self.assertEqual(list(self.vidux_root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
