"""Guard against restoring the removed external-board adapter package."""

from __future__ import annotations

import importlib.machinery
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class NoAdaptersImportPathTests(unittest.TestCase):
    def test_adapters_package_does_not_resolve_from_repo_root(self):
        spec = importlib.machinery.PathFinder.find_spec("adapters", [str(ROOT)])

        self.assertIsNone(spec)

    def test_only_sunset_archive_may_contain_adapters_directory(self):
        offenders = [
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("adapters")
            if path.is_dir()
            and "_sunset" not in path.relative_to(ROOT).parts
            and "node_modules" not in path.relative_to(ROOT).parts
        ]

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
