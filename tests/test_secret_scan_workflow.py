"""Regression contract for the automatic Secret scan admission policy."""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "secret-scan.yml"


class SecretScanWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def top_level_block(self, name):
        match = re.search(
            rf"(?ms)^{re.escape(name)}:\n(?P<body>.*?)(?=^[^\s][^:]*:\n|\Z)",
            self.workflow,
        )
        self.assertIsNotNone(match, f"missing top-level {name!r} block")
        return match.group("body")

    def test_retains_default_pr_synchronize_coverage_and_main_pushes_only(self):
        trigger_lines = [
            line
            for line in self.top_level_block("on").splitlines()
            if line and not line.lstrip().startswith("#")
        ]
        self.assertEqual(
            trigger_lines,
            [
                "  push:",
                "    branches:",
                "      - main",
                "  pull_request:",
                "  workflow_dispatch:",
            ],
        )

    def test_cancels_only_duplicate_runs_for_the_same_sha(self):
        concurrency_lines = [
            line
            for line in self.top_level_block("concurrency").splitlines()
            if line and not line.lstrip().startswith("#")
        ]
        self.assertEqual(
            concurrency_lines,
            [
                "  group: secret-scan-${{ github.sha }}",
                "  cancel-in-progress: true",
            ],
        )

    def test_transient_secret_history_is_scanned_after_a_pr_rerun(self):
        self.assertRegex(self.workflow, r"(?m)^          fetch-depth: 0$")
        self.assertRegex(
            self.workflow,
            r'(?m)^          if \[\[ "\$EVENT_NAME" == "pull_request" \]\]; then\n'
            r'^            log_opts="--diff-merges=first-parent '
            r'\$\{PULL_REQUEST_BASE_SHA\}\.\.\$\{PULL_REQUEST_HEAD_SHA\}"$',
        )
        self.assertIn(
            "gitleaks git --log-opts=\"$log_opts\" --config .gitleaks.toml --redact --verbose",
            self.workflow,
        )
        self.assertNotIn("gitleaks detect --no-git", self.workflow)

    @unittest.skipUnless(shutil.which("gitleaks"), "gitleaks is not installed")
    def test_history_range_detects_a_secret_removed_before_pr_head(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)

            def git(*args):
                return subprocess.run(
                    ["git", *args],
                    cwd=repository,
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout.strip()

            git("init", "-q")
            git("config", "user.name", "Secret scan test")
            git("config", "user.email", "secret-scan-test@example.invalid")
            scanner_config = repository / "transient-gitleaks.toml"
            scanner_config.write_text(
                """title = "transient secret test"

[[rules]]
id = "transient-secret"
description = "Temporary range-scanning test rule"
regex = '''transient_[A-Za-z0-9]{40}'''
keywords = ["transient_"]
""",
                encoding="utf-8",
            )
            (repository / "README.md").write_text("base\n", encoding="utf-8")
            git("add", "README.md")
            git("commit", "-qm", "base")
            base_sha = git("rev-parse", "HEAD")

            # Construct the token at runtime so this test source remains clean.
            transient_token = "transient_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"
            (repository / "transient.txt").write_text(
                f"{transient_token}\n", encoding="utf-8"
            )
            git("add", "transient.txt")
            git("commit", "-qm", "add transient secret")
            (repository / "transient.txt").unlink()
            git("commit", "-am", "remove transient secret", "-q")
            head_sha = git("rev-parse", "HEAD")

            scan = subprocess.run(
                [
                    "gitleaks",
                    "git",
                    f"--log-opts={base_sha}..{head_sha}",
                    "--config",
                    str(scanner_config),
                    "--redact",
                    "--no-banner",
                ],
                cwd=repository,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(
                scan.returncode,
                0,
                f"transient secret was not detected: {scan.stdout}\n{scan.stderr}",
            )

    def test_keeps_direct_main_ranges_read_only_and_redacted(self):
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertIn(
            "log_opts=\"--diff-merges=first-parent ${PUSH_BEFORE_SHA}..${PUSH_AFTER_SHA}\"",
            self.workflow,
        )

    @unittest.skipUnless(shutil.which("gitleaks"), "gitleaks is not installed")
    def test_history_range_detects_a_secret_added_by_merge_resolution(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)

            def git(*args, check=True):
                return subprocess.run(
                    ["git", *args],
                    cwd=repository,
                    check=check,
                    text=True,
                    capture_output=True,
                )

            git("init", "-q")
            git("config", "user.name", "Secret scan test")
            git("config", "user.email", "secret-scan-test@example.invalid")
            scanner_config = repository / "merge-gitleaks.toml"
            scanner_config.write_text(
                """title = "merge secret test"

[[rules]]
id = "merge-secret"
description = "Temporary merge-scanning test rule"
regex = '''merge_secret_[A-Za-z0-9]{40}'''
keywords = ["merge_secret_"]
""",
                encoding="utf-8",
            )
            conflict_file = repository / "conflict.txt"
            conflict_file.write_text("base\n", encoding="utf-8")
            git("add", "conflict.txt")
            git("commit", "-qm", "base")
            base_sha = git("rev-parse", "HEAD").stdout.strip()
            main_branch = git("branch", "--show-current").stdout.strip()

            git("switch", "-qc", "feature")
            conflict_file.write_text("feature\n", encoding="utf-8")
            git("commit", "-am", "feature change", "-q")
            git("switch", main_branch)
            conflict_file.write_text("main\n", encoding="utf-8")
            git("commit", "-am", "main change", "-q")
            merge = git("merge", "feature", check=False)
            self.assertNotEqual(merge.returncode, 0, "fixture should require resolution")

            resolution_token = "merge_secret_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"
            conflict_file.write_text(f"resolved\n{resolution_token}\n", encoding="utf-8")
            git("add", "conflict.txt")
            git("commit", "-qm", "resolve merge")
            merge_sha = git("rev-parse", "HEAD").stdout.strip()

            scan = subprocess.run(
                [
                    "gitleaks",
                    "git",
                    f"--log-opts=--diff-merges=first-parent {base_sha}..{merge_sha}",
                    "--config",
                    str(scanner_config),
                    "--redact",
                    "--no-banner",
                ],
                cwd=repository,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(
                scan.returncode,
                0,
                f"merge-resolution secret was not detected: {scan.stdout}\n{scan.stderr}",
            )


if __name__ == "__main__":
    unittest.main()
