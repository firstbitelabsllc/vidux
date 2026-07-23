"""Cross-surface contracts for the purist source and package boundary."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PUBLIC_GATE = ROOT / "scripts" / "vidux-public-ready-grep-gate.py"
SPEC = importlib.util.spec_from_file_location("vidux_public_ready_gate", PUBLIC_GATE)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


class PuristIntegrityTests(unittest.TestCase):
    def test_source_version_is_one_unpublished_1_0_contract(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        plugin = json.loads(
            (ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        version_lines = (ROOT / "VERSION").read_text(encoding="utf-8").splitlines()

        self.assertEqual(version_lines[0], "1.0.0")
        self.assertIn("no npm package is published", version_lines[1])
        self.assertEqual(package["version"], "1.0.0")
        self.assertEqual(lock["version"], "1.0.0")
        self.assertEqual(lock["packages"][""]["version"], "1.0.0")
        self.assertEqual(plugin["version"], "1.0.0")

    def test_package_allowlist_has_no_removed_browser_subsystem(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        allowlist = "\n".join(package["files"])
        self.assertNotIn("browser/" + "receipts", allowlist)
        self.assertNotIn("run_" + "extract_pass.py", allowlist)
        self.assertNotIn("commands/", allowlist)

    def test_source_has_exactly_one_root_skill_and_no_nested_runtime(self) -> None:
        discovered = sorted(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("SKILL.md")
            if not {".git", "node_modules"}.intersection(path.relative_to(ROOT).parts)
        )
        self.assertEqual(discovered, ["SKILL.md"])
        self.assertFalse((ROOT / "agent").exists())
        self.assertFalse((ROOT / "commands").exists())

    def test_manifest_and_lock_have_no_retired_direct_runtime_dependencies(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        package_deps = package.get("devDependencies", {})
        lock_deps = lock["packages"][""].get("devDependencies", {})

        self.assertEqual(lock_deps, package_deps)
        for dependency in ("ai", "eve", "zod"):
            self.assertNotIn(dependency, package_deps)
        self.assertNotIn("node_modules/eve", lock["packages"])

    def test_public_gate_rejects_removed_paths_and_private_release_overlay(self) -> None:
        cases = [
            (Path("agent") / "runtime.ts", "harmless\n"),
            (Path("browser") / ("run_" + "extract_pass.py"), "harmless\n"),
            (Path("browser") / "receipts" / "handler.py", "harmless\n"),
            (Path("commands") / "vidux.md", "harmless\n"),
            (Path("README.md"), "load " + "pilot" + "-leo for publishing\n"),
        ]
        for rel, body in cases:
            with self.subTest(path=rel), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")

                payload = gate.run_gate(root)

                self.assertEqual(payload["status"], "failed", payload)

    def test_readme_pins_actual_benchmark_stub_and_local_release_truth(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        normalized = " ".join(readme.split())
        self.assertIn("No benchmark harness", normalized)
        self.assertIn("source contract", normalized)
        self.assertIn("there is no npm package", normalized)
        self.assertIn("v1.0.0", normalized)
        self.assertIn("GitHub Release", normalized)

    def test_readme_keeps_the_public_first_read_thin_and_boundary_clear(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        normalized = " ".join(readme.split())
        self.assertLessEqual(len(readme.splitlines()), 100)
        self.assertIn("## Quick start", readme)
        self.assertIn("## Where Vidux stops", readme)
        self.assertIn("Vidux can record provider-neutral claims", normalized)
        self.assertIn("it never launches a provider or selects a model", normalized)
        self.assertIn("$HOME/.local/bin", readme)
        self.assertNotIn("/usr/local/bin", readme)


if __name__ == "__main__":
    unittest.main()
