"""Tests for scripts/vidux-config.py."""

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
SCRIPT = ROOT / "scripts" / "vidux-config.py"

spec = importlib.util.spec_from_file_location("vidux_config", SCRIPT)
assert spec is not None
vidux_config = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = vidux_config
spec.loader.exec_module(vidux_config)


def write_config(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def minimal_config() -> dict[str, object]:
    return {
        "plan_store": {
            "mode": "local",
            "path": "projects",
        }
    }


class ViduxConfigCliTests(unittest.TestCase):
    def run_config(
        self,
        tmp: Path,
        *args: str,
        env_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["VIDUX_ROOT"] = str(tmp)
        env["HOME"] = str(tmp / "home")
        env["XDG_CONFIG_HOME"] = str(tmp / "xdg-config")
        env.pop("VIDUX_CONFIG", None)
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_check_falls_back_to_example_without_requiring_live_config(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            write_config(tmp / "vidux.config.example.json", minimal_config())

            result = self.run_config(tmp, "check", "--json")

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["source"], "example")
            self.assertTrue(payload["using_example"])
            self.assertFalse(payload["live_config_present"])
            self.assertEqual(payload["plan_store"]["mode"], "local")

    def test_default_resolution_checks_xdg_then_example_not_repo_local_config(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            write_config(tmp / "vidux.config.example.json", minimal_config())
            write_config(tmp / "vidux.config.json", {"plan_store": {"mode": "local", "path": "wrong"}})

            result = self.run_config(tmp, "check", "--json")

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["source"], "example")
            self.assertNotIn(str((tmp / "vidux.config.json").resolve()), payload["checked"])
            self.assertEqual(
                payload["checked"][0],
                str((tmp / "xdg-config" / "vidux" / "vidux.config.json").resolve()),
            )

    def test_xdg_live_config_is_the_default_and_repo_local_is_explicit_only(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            write_config(tmp / "vidux.config.example.json", minimal_config())
            xdg = tmp / "xdg-config" / "vidux" / "vidux.config.json"
            xdg.parent.mkdir(parents=True)
            write_config(xdg, {"plan_store": {"mode": "external", "path": "plans"}})
            repo_local = tmp / "vidux.config.json"
            write_config(repo_local, minimal_config())

            default = self.run_config(tmp, "path", "--json")
            explicit = self.run_config(tmp, "path", "--json", "--config", str(repo_local))

            self.assertEqual(default.returncode, 0, default.stderr)
            self.assertEqual(explicit.returncode, 0, explicit.stderr)
            default_payload = json.loads(default.stdout)
            explicit_payload = json.loads(explicit.stdout)
            self.assertEqual(default_payload["source"], "xdg")
            self.assertEqual(default_payload["path"], str(xdg.resolve()))
            self.assertEqual(explicit_payload["source"], "explicit")
            self.assertEqual(explicit_payload["path"], str(repo_local.resolve()))

    def test_checked_in_example_config_passes_schema_without_leaking_private_values(self):
        example = json.loads((ROOT / "vidux.config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(example["plan_store"]["path"], "~/.local/share/vidux/plans")

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "check", "--config", str(ROOT / "vidux.config.example.json"), "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("github-owner", result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")

    def test_strict_check_requires_live_config(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            write_config(tmp / "vidux.config.example.json", minimal_config())

            result = self.run_config(tmp, "check", "--strict", "--json")

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "fail")
            self.assertIn("live_config_missing", {issue["code"] for issue in payload["issues"]})

    def test_explicit_malformed_config_reports_json_parse_error(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            bad = tmp / "bad.json"
            bad.write_text("{not-json", encoding="utf-8")

            result = self.run_config(tmp, "check", "--config", str(bad), "--json")

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(payload["issues"][0]["code"], "json_parse_error")

    def test_init_writes_config_and_refuses_accidental_overwrite(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            write_config(tmp / "vidux.config.example.json", minimal_config())
            destination = tmp / "local.json"

            first = self.run_config(tmp, "init", "--path", str(destination))
            second = self.run_config(tmp, "init", "--path", str(destination))
            forced = self.run_config(tmp, "init", "--path", str(destination), "--force")

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(destination.exists())
            self.assertEqual(second.returncode, 1)
            self.assertIn("already exists", second.stderr)
            self.assertEqual(forced.returncode, 0, forced.stderr)

    def test_init_defaults_to_xdg_and_does_not_mutate_packaged_root(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            package_root = tmp / "node_modules" / "vidux"
            package_root.mkdir(parents=True)
            example = package_root / "vidux.config.example.json"
            write_config(example, minimal_config())
            before = sorted(path.name for path in package_root.iterdir())
            package_root.chmod(0o555)
            try:
                result = self.run_config(
                    package_root,
                    "init",
                    env_overrides={
                        "HOME": str(tmp / "home"),
                        "XDG_CONFIG_HOME": str(tmp / "xdg-config"),
                    },
                )
            finally:
                package_root.chmod(0o755)

            destination = tmp / "xdg-config" / "vidux" / "vidux.config.json"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(destination.is_file())
            self.assertEqual(sorted(path.name for path in package_root.iterdir()), before)
            self.assertFalse((package_root / "vidux.config.json").exists())

    def test_init_rejects_even_explicit_destination_inside_node_modules_install(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            package_root = tmp / "node_modules" / "vidux"
            package_root.mkdir(parents=True)
            write_config(package_root / "vidux.config.example.json", minimal_config())

            result = self.run_config(
                package_root,
                "init",
                "--path",
                str(package_root / "vidux.config.json"),
                env_overrides={"XDG_CONFIG_HOME": str(tmp / "xdg-config")},
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("refusing to write inside packaged install root", result.stderr)
            self.assertFalse((package_root / "vidux.config.json").exists())

    def test_show_is_redacted_and_warns_on_inline_secret_values(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            live = tmp / "vidux.config.json"
            payload = minimal_config()
            payload["defaults"] = {"api_token": "super-secret-value"}
            write_config(live, payload)

            result = self.run_config(tmp, "show", "--json", "--config", str(live))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("super-secret-value", result.stdout)
            report = json.loads(result.stdout)
            self.assertIn("inline_secret_value", {issue["code"] for issue in report["issues"]})

    def test_show_expands_paths_and_redacts_token_file_details(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            (tmp / "projects").mkdir()
            (tmp / "external").mkdir()
            (tmp / "tokens").mkdir()
            (tmp / "tokens" / "gh.token").write_text("secret-token\n", encoding="utf-8")
            live = tmp / "vidux.config.json"
            payload = minimal_config()
            payload["external_plan_roots"] = ["external"]
            payload["defaults"] = {
                "owner": "demo-owner",
                "token": "super-secret-value",
                "token_file": "tokens/gh.token",
            }
            write_config(live, payload)

            result = self.run_config(tmp, "show", "--json", "--config", str(live))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("super-secret-value", result.stdout)
            self.assertNotIn("demo-owner", result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["plan_store"]["resolved_path"], str((tmp / "projects").resolve()))
            self.assertEqual(report["external_plan_roots"], [str((tmp / "external").resolve())])
            self.assertTrue(report["external_plan_roots_detail"][0]["path_exists"])
            self.assertIn("inline_secret_value", {issue["code"] for issue in report["issues"]})

    def test_malformed_schema_reports_structured_errors(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            live = tmp / "vidux.config.json"
            write_config(
                live,
                {
                    "version": 1,
                    "defaults": [],
                    "external_plan_roots": ["ok", 42],
                },
            )

            result = self.run_config(tmp, "check", "--json", "--config", str(live))

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "fail")
            codes = {issue["code"] for issue in payload["issues"]}
            self.assertIn("plan_store_missing", codes)
            self.assertIn("version_not_string", codes)
            self.assertIn("defaults_not_object", codes)
            self.assertIn("external_plan_roots_bad_item", codes)

    def test_explicit_config_pointing_at_a_directory_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as dirname:
            tmp = Path(dirname)
            a_directory = tmp / "not-a-file"
            a_directory.mkdir()

            result = self.run_config(tmp, "check", "--json", "--config", str(a_directory))

            self.assertEqual(result.returncode, 1)
            self.assertNotIn("Traceback", result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "fail")
            codes = {issue["code"] for issue in payload["issues"]}
            self.assertIn("config_is_directory", codes)

    def test_main_empty_argv_does_not_read_process_argv(self):
        original_argv = sys.argv[:]
        stderr = io.StringIO()
        try:
            sys.argv = ["pytest", "path"]
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    vidux_config.main([])
        finally:
            sys.argv = original_argv

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("the following arguments are required", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
