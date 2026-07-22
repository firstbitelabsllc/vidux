"""Contract coverage for the installable Vidux release candidate."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "vidux-release-package.py"
SPEC = importlib.util.spec_from_file_location("vidux_release_package", SCRIPT)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def baseline() -> tuple[dict, dict, set[str]]:
    package = {
        "name": "vidux",
        "version": "1.0.0",
        "private": False,
        "bin": {"vidux": "bin/vidux"},
        "files": ["bin/", "scripts/"],
        "engines": {"node": ">=20"},
        "publishConfig": {"access": "public", "provenance": True},
        "scripts": {
            "release:verify": "python3 scripts/vidux-release-package.py",
            "release:verify:dev": "python3 scripts/vidux-release-package.py --allow-dirty",
        },
    }
    paths = set(mod.REQUIRED_FILES)
    pack = {
        "name": "vidux",
        "version": "1.0.0",
        "unpackedSize": 100_000,
        "files": [{"path": path, "size": 1} for path in sorted(paths)],
    }
    return package, pack, paths


class ReleasePackageTests(unittest.TestCase):
    def test_steering_and_coordination_runtime_is_release_required(self) -> None:
        self.assertTrue(
            {
                "browser/coordination_claims.py",
                "browser/steering_mailbox.py",
                "browser/static/coordination-panel.js",
                "browser/static/steering-inbox.js",
                "scripts/vidux-claims.py",
                "scripts/vidux-steer.py",
            }.issubset(mod.REQUIRED_FILES)
        )

    def errors(self, package: dict, pack: dict, tracked: set[str]) -> list[str]:
        return mod.validate_release_candidate(
            package,
            pack,
            version="1.0.0",
            tracked_paths=tracked,
            plugin_version="1.0.0",
        )

    def test_baseline_contract_passes(self) -> None:
        package, pack, tracked = baseline()
        self.assertEqual(self.errors(package, pack, tracked), [])

    def test_rejects_private_or_version_drifted_package(self) -> None:
        package, pack, tracked = baseline()
        package["private"] = True
        package["version"] = "2.22.0"
        errors = self.errors(package, pack, tracked)
        self.assertTrue(any("private" in error for error in errors), errors)
        self.assertTrue(any("package.json version" in error for error in errors), errors)

    def test_rejects_plugin_version_drift(self) -> None:
        package, pack, tracked = baseline()
        errors = mod.validate_release_candidate(
            package,
            pack,
            version="1.0.0",
            tracked_paths=tracked,
            plugin_version="2.22.0",
        )
        self.assertTrue(any("plugin version" in error for error in errors), errors)

    def test_expected_version_cannot_mask_stale_source_version(self) -> None:
        package, pack, tracked = baseline()
        errors = mod.validate_release_candidate(
            package,
            pack,
            version="2.99.0",
            tracked_paths=tracked,
            plugin_version="1.0.0",
            expected_version="1.0.0",
        )
        self.assertTrue(any("VERSION source" in error for error in errors), errors)

    def test_rejects_missing_cli_and_broad_local_material(self) -> None:
        package, pack, tracked = baseline()
        pack["files"] = [entry for entry in pack["files"] if entry["path"] != "bin/vidux"]
        for path in [
            "agent/runtime.ts",
            "commands/vidux.md",
            "evaluations/run.json",
            ".opencode/agent.md",
            "evidence/private.jsonl",
        ]:
            pack["files"].append({"path": path, "size": 1})
            tracked.add(path)
        errors = self.errors(package, pack, tracked)
        self.assertTrue(any("missing required" in error and "bin/vidux" in error for error in errors), errors)
        self.assertTrue(any("forbidden files" in error for error in errors), errors)

    def test_rejects_nested_or_missing_skill_surface(self) -> None:
        package, pack, tracked = baseline()
        nested = "agent/skills/private/SKILL.md"
        pack["files"].append({"path": nested, "size": 1})
        tracked.add(nested)

        errors = self.errors(package, pack, tracked)
        self.assertTrue(any("exactly the root SKILL.md" in error for error in errors), errors)

        package, pack, tracked = baseline()
        pack["files"] = [entry for entry in pack["files"] if entry["path"] != "SKILL.md"]
        errors = self.errors(package, pack, tracked)
        self.assertTrue(any("exactly the root SKILL.md" in error for error in errors), errors)

    def test_rejects_untracked_or_oversized_artifact(self) -> None:
        package, pack, tracked = baseline()
        pack["files"].append({"path": "scripts/local-only.sh", "size": 1})
        pack["unpackedSize"] = mod.MAX_UNPACKED_BYTES + 1
        errors = self.errors(package, pack, tracked)
        self.assertTrue(any("not tracked by git" in error for error in errors), errors)
        self.assertTrue(any("unpacked bytes" in error for error in errors), errors)

    def test_rejects_any_benchmark_files(self) -> None:
        # The local benchmark harness (v2/v3/v4) was removed; a purist build
        # ships no benchmarks/ surface at all, so any such file is rejected.
        package, pack, tracked = baseline()
        pack["files"].append({"path": "benchmarks/v4/private-evaluator.json", "size": 1})
        tracked.add("benchmarks/v4/private-evaluator.json")

        errors = self.errors(package, pack, tracked)

        self.assertTrue(
            any("benchmark files" in error for error in errors),
            errors,
        )

    def test_rejects_removed_extractor_and_receipt_lab_files(self) -> None:
        package, pack, tracked = baseline()
        removed_paths = [
            "browser/" + "run_extract_pass.py",
            "browser/" + "receipts/handler.py",
        ]
        for path in removed_paths:
            pack["files"].append({"path": path, "size": 1})
            tracked.add(path)

        errors = self.errors(package, pack, tracked)

        self.assertTrue(any("forbidden files" in error for error in errors), errors)
        self.assertTrue(all(any(path in error for error in errors) for path in removed_paths), errors)

    def test_dirty_packaged_bytes_are_rejected_or_explicitly_development_only(self) -> None:
        package, pack, tracked = baseline()
        dirty = {"README.md", "PLAN.md"}
        errors = mod.validate_release_candidate(
            package,
            pack,
            version="1.0.0",
            tracked_paths=tracked,
            plugin_version="1.0.0",
            dirty_packaged_paths=dirty,
        )
        self.assertTrue(any("dirty working-tree bytes" in error for error in errors), errors)
        self.assertIn("README.md", "\n".join(errors))
        self.assertNotIn("PLAN.md", "\n".join(errors), "unpackaged dirt must not poison the receipt")

        allowed = mod.validate_release_candidate(
            package,
            pack,
            version="1.0.0",
            tracked_paths=tracked,
            plugin_version="1.0.0",
            dirty_packaged_paths=dirty,
            allow_dirty=True,
        )
        self.assertEqual(allowed, [])

    def test_dirty_file_detection_reads_staged_unstaged_and_untracked_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Test"],
                check=True,
            )
            (root / "README.md").write_text("committed\n", encoding="utf-8")
            (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "initial"], check=True)

            (root / "README.md").write_text("unstaged\n", encoding="utf-8")
            (root / "VERSION").write_text("1.0.1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "VERSION"], check=True)
            (root / "local.txt").write_text("untracked\n", encoding="utf-8")

            self.assertEqual(
                mod.dirty_files(root),
                {"README.md", "VERSION", "local.txt"},
            )

    def test_exact_head_comparison_ignores_assume_unchanged_false_green(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Test"],
                check=True,
            )
            readme = root / "README.md"
            readme.write_text("committed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "initial"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "update-index", "--assume-unchanged", "README.md"],
                check=True,
            )
            readme.write_text("different packed bytes\n", encoding="utf-8")

            status = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(status.stdout.strip(), "")
            self.assertEqual(
                mod.packaged_paths_different_from_head(root, {"README.md"}),
                {"README.md"},
            )

    def test_rejects_unsafe_publish_configuration(self) -> None:
        package, pack, tracked = baseline()
        package["publishConfig"] = {"access": "restricted"}
        errors = self.errors(package, pack, tracked)
        self.assertTrue(any("provenance" in error for error in errors), errors)

    def test_current_checkout_package_passes(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(ROOT),
                "--allow-dirty",
                "--json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        receipt = json.loads(result.stdout)
        if receipt["dirty_packaged_files"]:
            self.assertEqual(receipt["dirty_policy"], "allowed_for_development_only")
            self.assertFalse(receipt["publishable"])
        else:
            self.assertEqual(receipt["dirty_policy"], "clean")
            self.assertTrue(receipt["publishable"])


if __name__ == "__main__":
    unittest.main()
