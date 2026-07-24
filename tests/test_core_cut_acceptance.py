"""Hermetic acceptance for docs/CORE-CUT.md (install-first root + doctrine move)."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCTRINE = (
    "ARCHITECTURE.md",
    "DOCTRINE.md",
    "ENFORCEMENT.md",
    "INGREDIENTS.md",
    "LOOP.md",
    "WRITING-STYLE.md",
)


class CoreCutAcceptanceTests(unittest.TestCase):
    def test_root_doctrine_essays_removed(self):
        for name in DOCTRINE:
            self.assertFalse((ROOT / name).exists(), name)

    def test_doctrine_lives_under_docs_doctrine(self):
        for name in DOCTRINE:
            self.assertTrue((ROOT / "docs" / "doctrine" / name).is_file(), name)

    def test_skill_and_readme_point_at_docs_doctrine(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/doctrine/DOCTRINE.md", skill)
        self.assertIn("docs/doctrine/ARCHITECTURE.md", readme)

    def test_package_files_include_docs_glob_not_root_doctrine(self):
        import json

        files = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["files"]
        self.assertTrue(any(f.startswith("docs/") for f in files))
        for name in DOCTRINE:
            self.assertNotIn(name, files)


if __name__ == "__main__":
    unittest.main()
