"""Tests for scripts/vidux-public-ready-grep-gate.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "vidux-public-ready-grep-gate.py"


class PublicReadyGrepGateTests(unittest.TestCase):
    def test_tracked_only_scans_the_shipping_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "README.md").write_text("Vidux is markdown-plan-first.\n", encoding="utf-8")
            leak = root / "LOCAL-NOTES.md"
            leak.write_text("Use `/leo-flow` locally.\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)

            clean = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo-root",
                    str(root),
                    "--tracked-only",
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            subprocess.run(["git", "-C", str(root), "add", "LOCAL-NOTES.md"], check=True)
            leak.write_text("Clean worktree copy.\n", encoding="utf-8")
            leaking = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo-root",
                    str(root),
                    "--tracked-only",
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        clean_payload = json.loads(clean.stdout)
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertEqual(clean_payload["scope"], "tracked")
        self.assertEqual(clean_payload["scanned_files"], 1)
        self.assertEqual(leaking.returncode, 1)
        leaking_payload = json.loads(leaking.stdout)
        self.assertEqual(leaking_payload["matches"][0]["file"], "LOCAL-NOTES.md")

    def test_clean_current_surface_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Vidux is markdown-plan-first.\n", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs" / "config.md").write_text("Plans are files.\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["matches"], [])

    def test_privacy_leak_in_filename_is_caught_even_in_historical_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            evidence.mkdir()
            # A leak-class string in the FILENAME, with clean redacted body
            # content -- content-only scanning once missed a real leak
            # sitting in a tracked filename,
            # which renders unredacted in any GitHub directory listing
            # regardless of what's inside the file or its historical status.
            (evidence / "2026-06-08-leo-flow-anti-slop.md").write_text(
                "Redacted body, no leak here.\n", encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        match = payload["matches"][0]
        self.assertEqual(match["line"], 0)
        self.assertIn("in filename", match["pattern"])

    def test_forbidden_term_in_current_surface_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Add Linear sync back here.\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["matches"][0]["file"], "README.md")

    def test_plan_live_sections_are_scanned_but_append_only_history_is_exempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "PLAN.md").write_text(
                "# Plan\n"
                "## Current State\n"
                "Restore Linear sync now.\n"
                "## Decision Log\n"
                "### 2026-04-01\n"
                "Retired Linear sync.\n"
                "## Open work\n"
                "Keep plans in markdown.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["matches"]), 1, payload["matches"])
        self.assertEqual(payload["matches"][0]["line"], 3)
        self.assertEqual(payload["matches"][0]["pattern"], "retired board brand")

    def test_private_machine_ownership_assignment_variants_fail(self):
        phrases = [
            "The M4 Pro owns Project Atlas automation.\n",
            "Project Atlas is owned by the Mac Studio.\n",
            "Project Atlas is Studio-owned, not blocked waiting for this Mac.\n",
            "The M4 Pro does not probe or edit Project Atlas.\n",
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "README.md").write_text(phrase, encoding="utf-8")

                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 1)
                payload = json.loads(result.stdout)
                self.assertEqual(
                    payload["matches"][0]["pattern"],
                    "private machine ownership assignment",
                )

    def test_private_machine_ownership_ignores_benign_own_phrases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "The M1 Max has its own binary cache.\n"
                "Matrix M3 chassis with its own housing.\n"
                "M5 own goal in the 90th minute.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stdout)

    def test_plan_fenced_heading_does_not_change_history_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "PLAN.md").write_text(
                "# Plan\n"
                "## Current State\n"
                "```bash\n"
                "# progress\n"
                "```\n"
                "Restore Linear sync now.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual([match["line"] for match in payload["matches"]], [6])

    def test_plan_setext_heading_exits_append_only_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "PLAN.md").write_text(
                "# Plan\n"
                "## Decision Log\n"
                "Retired Linear sync.\n"
                "Open work\n"
                "---------\n"
                "Restore Linear sync now.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual([match["line"] for match in payload["matches"]], [6])

    def test_plan_append_only_history_still_scans_privacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "PLAN.md").write_text(
                "# Plan\n"
                "## Decision Log\n"
                "The M4 Pro owns Project Atlas automation.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["matches"][0]["pattern"],
            "private machine ownership assignment",
        )

    def test_unreadable_file_does_not_crash_the_gate(self):
        # an OSError (permissions, or a file deleted
        # mid-scan) other than UnicodeDecodeError propagated as an unhandled
        # traceback -- exit 1 either way, indistinguishable from a real
        # leak match by exit code alone, and --json mode emitted nothing
        # parseable on crash.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Clean.\n", encoding="utf-8")
            unreadable = root / "docs"
            unreadable.mkdir()
            blocked = unreadable / "blocked.md"
            blocked.write_text("Add Linear sync back here.\n", encoding="utf-8")
            blocked.chmod(0o000)

            try:
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                blocked.chmod(0o644)

        self.assertIn(result.returncode, (0, 1))
        payload = json.loads(result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(payload["status"], "passed")

    def test_ask_leo_is_in_scope_but_hygiene_exempt(self):
        # ASK-LEO.md was grouped with true history
        # files (ARCHIVE.md/CHANGELOG.md) and excluded from SCAN_TARGETS
        # entirely, hiding a real private-path leak. It's a LIVE, ongoing
        # queue (per its own header), not a closed record -- it must be
        # scanned. But its resolved Q&A entries are still historical enough
        # that HYGIENE_PATTERNS (e.g. "Linear") shouldn't retroactively fire.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Vidux is markdown-plan-first.\n", encoding="utf-8")
            (root / "ASK-LEO.md").write_text(
                "## Q1\nAnswer: migrated off Linear sync in 2026-04.\n"
                "Private path leak: /Users/leokwan/Development/x\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        files_matched = {m["file"] for m in payload["matches"]}
        self.assertEqual(files_matched, {"ASK-LEO.md"})
        patterns_matched = {m["pattern"] for m in payload["matches"]}
        self.assertEqual(patterns_matched, {"private username"})

    def test_leo_flow_pattern_catches_hyphenated_slash_command_form(self):
        # the original pattern only matched the
        # spaced "Leo Flow" form and missed "/leo-flow"/"leo-flow", which is
        # the form actually used in prose -- 6 live occurrences in SKILL.md
        # passed the gate green while sitting in a live, current section.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "Use `/leo-flow` for lane routing.\n", encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["matches"][0]["pattern"], "private Leo Flow lane")

    def test_username_pattern_catches_bare_mentions_not_just_home_paths(self):
        # the old pattern only matched the
        # /Users/leokwan PATH form. A historical evidence file leaked 26
        # bare `com.leokwan.<private-project>` macOS LaunchAgent labels
        # (naming several unrelated private repos), unscanned because none
        # of them is a /Users/ path.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "launchctl print gui/501/com.leokwan.some-private-service\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["matches"][0]["pattern"], "private username")

    def test_private_maintainer_account_note_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text(
                '{"_note": "Leo\'s work account requires private command policy."}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["matches"][0]["pattern"], "private maintainer account note")

    def test_spouse_first_name_pattern_catches_real_leak(self):
        # 4 evidence files named the maintainer's
        # real spouse by first name, once in a genuinely sensitive
        # confidential-job-search context, with no PRIVACY_PATTERNS rule
        # covering a family member's name at all.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "Make this simple enough for Nicole to use.\n", encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["matches"][0]["pattern"], "maintainer's spouse's first name")

    def test_spouse_first_name_pattern_is_case_insensitive(self):
        # an earlier version of this rule had no re.IGNORECASE, so
        # it silently missed the dominant lowercase/kebab-case form this
        # repo's own project-naming convention actually produces (e.g.
        # "nicole-fpa-ai" as a directory name) -- the exact bug that let
        # 7 real leaks ship past every prior grep-gate run.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "audit.jsonl").write_text(
                '{"path": "projects/nicole-fpa-ai/PLAN.md"}\n', encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["matches"][0]["pattern"], "maintainer's spouse's first name")

    def test_employer_source_path_pattern_was_a_silent_noop_now_catches_real_leaks(self):
        # the "employer source path" rule's regex had
        # been over-redacted to the literal placeholder text
        # "REDACTED-EMPLOYER-PATH" -- a string that never appears in real
        # content, so the rule matched nothing, ever. It missed a live leak:
        # this session's own evidence file quoting a real employer corporate
        # dev-tree path and email verbatim while documenting a
        # confidentiality finding about that exact content.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "Evidence: /Users/lkwan/Snapchat/Dev/ai/skills\n", encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["matches"][0]["pattern"], "employer source path")

    def test_employer_email_and_hostname_patterns_catch_real_leaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "Author: someone@snapchat.com; internal.snapchat.com and "
                "build-cache-1.sc-corp.net were referenced.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        patterns_matched = {m["pattern"] for m in payload["matches"]}
        self.assertIn("employer email or domain", patterns_matched)
        self.assertIn("employer internal hostname", patterns_matched)

    def test_employer_snap_tld_pattern_catches_real_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "Endpoint: http://internal-inference.snap/v1/embeddings\n", encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        patterns_matched = {m["pattern"] for m in payload["matches"]}
        self.assertIn("employer internal .snap TLD", patterns_matched)

    def test_gmail_and_other_business_name_patterns_catch_real_leaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "Author: trysnowcubes@gmail.com, business: trysnowcubes.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        patterns_matched = {m["pattern"] for m in payload["matches"]}
        self.assertIn(
            "gmail address other than the maintainer's public commit identity",
            patterns_matched,
        )
        self.assertIn("maintainer's other business name", patterns_matched)

    def test_maintainers_own_public_commit_identity_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "Every commit on origin/main is authored as leojkwan@gmail.com.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "passed")

    def test_project_plan_append_only_history_is_hygiene_exempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "projects" / "old-cleanup" / "PLAN.md"
            plan.parent.mkdir(parents=True)
            plan.write_text(
                "# Cleanup plan\n"
                "## Decisions\n"
                "Historical Linear removal notes stay here.\n",
                encoding="utf-8",
            )
            (root / "README.md").write_text("Current docs stay clean.\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "passed")

    def test_new_top_level_file_not_named_in_any_allowlist_is_still_scanned(self):
        # SCAN_TARGETS was a hand-maintained allowlist.
        # AGENTS.md and CHANGELOG.md were both tracked, shipped, and leaked
        # real private strings for weeks because neither was ever added to
        # the list. The fix replaces the allowlist with default-on scanning
        # (everything minus a documented denylist) -- this proves a brand
        # new, never-named file is caught automatically, not just the two
        # specific files that were found by hand.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Clean.\n", encoding="utf-8")
            (root / "NOTES-NOBODY-NAMED-YET.md").write_text(
                "Use `/leo-flow` for lane routing.\n", encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["matches"][0]["file"], "NOTES-NOBODY-NAMED-YET.md")

    def test_css_and_svg_linear_keyword_is_not_a_false_positive(self):
        # switching to default-on scanning surfaced 9
        # new HYGIENE_PATTERNS matches, all false positives -- "linear" as a
        # CSS gradient/timing-function keyword has nothing to do with the
        # retired Linear.app board integration the pattern exists to catch.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "style.css").write_text(
                "a { background: linear-gradient(180deg, #fff, #000); "
                "transition: all 1.5s linear infinite; }\n",
                encoding="utf-8",
            )
            (root / "banner.svg").write_text(
                "<style>.x { animation: flow 1.5s linear infinite; }</style>\n",
                encoding="utf-8",
            )
            (root / ".gitignore").write_text(".linear-state.json\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "passed")

    def test_css_file_still_catches_a_real_privacy_leak(self):
        # The hygiene exemption for CSS/SVG must not become a privacy
        # loophole -- PRIVACY_PATTERNS still apply to every scanned file.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "style.css").write_text(
                "/* generated from /vidux-leo/tokens.json */\n", encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["matches"][0]["pattern"], "private vidux overlay name")

    def test_changelog_is_privacy_scanned_but_hygiene_exempt(self):
        # CHANGELOG.md was excluded outright and
        # leaked '/leo-flow' and '/vidux-leo' in cleartext. The fix moves it
        # into HISTORICAL_TARGETS (like PLAN.md/ARCHIVE.md) rather than
        # excluding it: PRIVACY_PATTERNS still apply, HYGIENE_PATTERNS don't
        # (a changelog legitimately mentions retired terms in past tense).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Clean.\n", encoding="utf-8")
            (root / "CHANGELOG.md").write_text(
                "## [1.0.0]\n- Migrated off Linear.\n- Kept locally under /vidux-leo.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        matches = payload["matches"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["file"], "CHANGELOG.md")
        self.assertEqual(matches[0]["pattern"], "private vidux overlay name")

    def test_tests_dir_exemption_is_narrow_not_the_whole_directory(self):
        # the
        # exemption used to be the bare directory `Path("tests")`, which
        # exempted every tracked file under tests/ -- not just the 2 files
        # whose comments justify it (this file, for self-reference, and
        # test_vidux_contracts.py, for pinned fixture strings). A leak
        # pasted into any OTHER test file shipped with zero gate coverage.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Clean.\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            tests_dir.joinpath("test_vidux_contracts.py").write_text(
                "PINNED = '/leo-flow'  # required fixture, exempt\n", encoding="utf-8",
            )
            tests_dir.joinpath("test_some_unrelated_thing.py").write_text(
                "LEAK = '/leo-flow'  # should NOT be exempt\n", encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        files_matched = {m["file"] for m in payload["matches"]}
        self.assertEqual(files_matched, {"tests/test_some_unrelated_thing.py"})

    def test_docs_vitepress_dir_is_no_longer_bare_exempt(self):
        # EXCLUDED_RELATIVE_PATHS used to have a bare
        # `Path("docs/.vitepress")` entry -- the same whole-directory
        # exemption bug just fixed for tests/, one entry over -- that
        # exempted the entire tree from every FORBIDDEN_PATTERN. Nothing
        # leaked through it in the live repo (the only tracked file there,
        # config.ts, has no leak-class content, and dist/ is git-ignored),
        # but a new file dropped into that tree with a real leak string
        # would have shipped unscanned. Confirm it's now caught.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Clean.\n", encoding="utf-8")
            vitepress_dir = root / "docs" / ".vitepress"
            vitepress_dir.mkdir(parents=True)
            vitepress_dir.joinpath("config.ts").write_text(
                "export default { title: 'Vidux' }\n", encoding="utf-8",
            )
            vitepress_dir.joinpath("theme.ts").write_text(
                "// LEAK = '/leo-flow'\n", encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", str(root), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        files_matched = {m["file"] for m in payload["matches"]}
        self.assertEqual(files_matched, {"docs/.vitepress/theme.ts"})


class PublicReadyMetadataGateTests(unittest.TestCase):
    """--metadata scans commit identity + message trailers, which file-content
    scanning is structurally blind to (the exposures that survive a clean tree)."""

    @staticmethod
    def _commit(root, message, *, name, email):
        env = {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", message],
            check=True,
            env={**os.environ, **env},
        )

    def _run_metadata(self, root):
        return subprocess.run(
            [
                sys.executable, str(SCRIPT), "--repo-root", str(root),
                "--tracked-only", "--metadata", "--json",
            ],
            capture_output=True, text=True, check=False,
        )

    def test_clean_identity_and_message_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "README.md").write_text("Vidux.\n", encoding="utf-8")
            self._commit(
                root, "docs: initial", name="Leo Kwan", email="leojkwan@gmail.com"
            )
            result = self._run_metadata(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["scanned_commits"], 1)

    def test_codesmith_automation_identity_is_allowed(self):
        # Autofix is enabled on this repo, so Codesmith commits with the
        # maintainer as author and codesmith-bot as committer. That committer
        # uses GitHub's privacy-preserving users.noreply.github.com form and is
        # an intended participant, not a foreign leak, so the gate must pass it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "README.md").write_text("Vidux.\n", encoding="utf-8")
            env = {
                "GIT_AUTHOR_NAME": "leojkwan",
                "GIT_AUTHOR_EMAIL": "leojkwan@gmail.com",
                "GIT_COMMITTER_NAME": "Codesmith",
                "GIT_COMMITTER_EMAIL": "codesmith-bot@users.noreply.github.com",
            }
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-q", "-m", "fix: automated"],
                check=True,
                env={**os.environ, **env},
            )
            result = self._run_metadata(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "passed", payload)

    def test_foreign_author_identity_is_caught(self):
        # Reproduces the TESTPERSONAL exposure: a test@test.com author renders
        # a real, unrelated GitHub account as a public contributor.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "README.md").write_text("Vidux.\n", encoding="utf-8")
            self._commit(
                root, "chore: seed", name="Leo Kwan", email="test@test.com"
            )
            result = self._run_metadata(root)
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        patterns = {m["pattern"] for m in payload["matches"]}
        self.assertIn("disallowed author identity", patterns)
        self.assertTrue(
            any("test@test.com" in m["text"] for m in payload["matches"]),
            payload["matches"],
        )

    def test_snapchat_coauthor_trailer_in_message_is_caught(self):
        # Reproduces the surviving trailer leak: a Co-authored-by trailer
        # naming an employer email, present in commit metadata, not the tree.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "README.md").write_text("Vidux.\n", encoding="utf-8")
            self._commit(
                root,
                "feat: thing\n\nCo-authored-by: Leo Kwan <lkwan@snapchat.com>",
                name="Leo Kwan",
                email="leojkwan@gmail.com",
            )
            result = self._run_metadata(root)
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        # snapchat.com domain + lkwan employer-source pattern both fire on the
        # trailer line; either is sufficient proof the trailer was scanned.
        matched = " ".join(m["pattern"] for m in payload["matches"])
        self.assertTrue(
            "employer email or domain" in matched
            or "employer source path" in matched,
            payload["matches"],
        )


if __name__ == "__main__":
    unittest.main()
