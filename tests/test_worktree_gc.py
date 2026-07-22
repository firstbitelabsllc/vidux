import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "vidux-worktree-gc.py"


def run(command, cwd=None, env=None, check=True):
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"{command} failed with {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def git(repo, *args, check=True):
    return run(["git", "-C", str(repo), *args], check=check)


class WorktreeGcTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.worktrees_dir = self.root / "worktrees"
        self.worktrees_dir.mkdir()

        run(["git", "init", "-b", "main", str(self.repo)])
        git(self.repo, "config", "user.email", "vidux@example.com")
        git(self.repo, "config", "user.name", "Vidux Test")
        (self.repo / "README.md").write_text("vidux\n", encoding="utf-8")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "initial")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")

        self.add_worktree("merged-clean")
        self.add_worktree("open-pr")
        self.add_detached_open_pr_worktree()
        dirty = self.add_worktree("dirty-branch")
        (dirty / "dirty.txt").write_text("local-only\n", encoding="utf-8")
        self.add_unmerged_worktree("closed-unmerged")
        self.add_unmerged_worktree("unmerged-no-pr")

        self.env = os.environ.copy()
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        self.write_fake_gh(fake_bin / "gh")
        self.env["PATH"] = f"{fake_bin}{os.pathsep}{self.env['PATH']}"

    def tearDown(self):
        self.tmp.cleanup()

    def add_worktree(self, branch):
        path = self.worktrees_dir / branch
        git(self.repo, "worktree", "add", "-b", branch, str(path), "HEAD")
        return path

    def add_unmerged_worktree(self, branch):
        path = self.add_worktree(branch)
        filename = f"{branch}.txt"
        (path / filename).write_text(branch + "\n", encoding="utf-8")
        git(path, "add", filename)
        git(path, "commit", "-m", f"change {branch}")
        return path

    def add_detached_open_pr_worktree(self):
        branch = "detached-open-pr-source"
        git(self.repo, "switch", "-c", branch)
        filename = f"{branch}.txt"
        (self.repo / filename).write_text(branch + "\n", encoding="utf-8")
        git(self.repo, "add", filename)
        git(self.repo, "commit", "-m", "change detached open pr")
        head = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        git(self.repo, "switch", "main")
        path = self.worktrees_dir / "detached-open-pr"
        git(self.repo, "worktree", "add", "--detach", str(path), head)
        return path

    def write_fake_gh(self, path, extra=()):
        payload = list(extra) + [
            {
                "number": 12,
                "state": "OPEN",
                "title": "open work",
                "headRefName": "open-pr",
                "isDraft": False,
                "url": "https://example.test/pull/12",
                "headRefOid": git(self.repo, "rev-parse", "open-pr").stdout.strip(),
                "mergedAt": None,
                "closedAt": None,
            },
            {
                "number": 14,
                "state": "OPEN",
                "title": "detached open work",
                "headRefName": "detached-open-pr-source",
                "isDraft": False,
                "url": "https://example.test/pull/14",
                "headRefOid": git(self.repo, "rev-parse", "detached-open-pr-source").stdout.strip(),
                "mergedAt": None,
                "closedAt": None,
            },
            {
                "number": 13,
                "state": "CLOSED",
                "title": "closed work",
                "headRefName": "closed-unmerged",
                "isDraft": False,
                "url": "https://example.test/pull/13",
                "headRefOid": git(self.repo, "rev-parse", "closed-unmerged").stdout.strip(),
                "mergedAt": None,
                "closedAt": "2026-04-26T00:00:00Z",
            },
        ]
        path.write_text(
            "#!/bin/sh\ncat <<'JSON'\n" + json.dumps(payload) + "\nJSON\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def run_gc(self, *args, check=True):
        return run(
            [sys.executable, str(SCRIPT), "--base", "origin/main", "--json", *args, str(self.repo)],
            env=self.env,
            check=check,
        )

    def test_reused_branch_name_with_old_merged_pr_stays_unmerged(self):
        # Branch names are reusable: an old MERGED PR whose head OID no longer
        # matches the worktree's HEAD must not classify current, genuinely
        # unmerged commits as merged_clean (the guarded-removal bucket).
        self.add_unmerged_worktree("reused-merged")
        stale_oid = git(self.repo, "rev-parse", "origin/main").stdout.strip()
        old_merged_pr = {
            "number": 20,
            "state": "MERGED",
            "title": "earlier life of this branch name",
            "headRefName": "reused-merged",
            "isDraft": False,
            "url": "https://example.test/pull/20",
            "headRefOid": stale_oid,
            "mergedAt": "2026-04-01T00:00:00Z",
            "closedAt": "2026-04-01T00:00:00Z",
        }
        self.write_fake_gh(self.root / "bin" / "gh", extra=[old_merged_pr])

        result = self.run_gc()
        payload = json.loads(result.stdout)
        by_branch = {item["branch"]: item for item in payload["worktrees"]}

        item = by_branch["reused-merged"]
        self.assertEqual("unmerged_no_pr", item["bucket"])
        self.assertFalse(item["removable"])
        self.assertIsNone(item["pr_number"])

    def test_merged_pr_still_at_tip_keeps_merged_clean(self):
        # The legitimate case must keep working: a worktree still sitting
        # exactly at its MERGED PR's head OID (squash-merge keeps that OID out
        # of base) classifies merged_clean via the OID-confirmed name match.
        path = self.add_unmerged_worktree("merged-at-tip")
        tip_oid = git(path, "rev-parse", "HEAD").stdout.strip()
        merged_pr = {
            "number": 21,
            "state": "MERGED",
            "title": "squash-merged work",
            "headRefName": "merged-at-tip",
            "isDraft": False,
            "url": "https://example.test/pull/21",
            "headRefOid": tip_oid,
            "mergedAt": "2026-07-01T00:00:00Z",
            "closedAt": "2026-07-01T00:00:00Z",
        }
        self.write_fake_gh(self.root / "bin" / "gh", extra=[merged_pr])

        result = self.run_gc()
        payload = json.loads(result.stdout)
        by_branch = {item["branch"]: item for item in payload["worktrees"]}

        item = by_branch["merged-at-tip"]
        self.assertEqual("merged_clean", item["bucket"])
        self.assertTrue(item["removable"])
        self.assertEqual(21, item["pr_number"])

    def test_classifies_worktree_lifecycle_buckets(self):
        result = self.run_gc()
        payload = json.loads(result.stdout)
        by_branch = {item["branch"]: item for item in payload["worktrees"]}
        detached = next(item for item in payload["worktrees"] if item["path"].endswith("detached-open-pr"))

        self.assertEqual("primary", by_branch["main"]["bucket"])
        self.assertIn("protected", by_branch["main"]["next_owner_action"])
        self.assertEqual("merged_clean", by_branch["merged-clean"]["bucket"])
        self.assertTrue(by_branch["merged-clean"]["removable"])
        self.assertIn("--apply --yes", by_branch["merged-clean"]["next_owner_action"])
        self.assertEqual("open_pr", by_branch["open-pr"]["bucket"])
        self.assertEqual(12, by_branch["open-pr"]["pr_number"])
        self.assertIn("review the PR", by_branch["open-pr"]["next_owner_action"])
        self.assertIn("gh pr view 12", by_branch["open-pr"]["review_command"])
        self.assertIsNone(detached["branch"])
        self.assertEqual("open_pr", detached["bucket"])
        self.assertEqual(14, detached["pr_number"])
        self.assertIn("gh pr view 14", detached["review_command"])
        self.assertEqual("dirty", by_branch["dirty-branch"]["bucket"])
        self.assertIn("preserve WIP", by_branch["dirty-branch"]["next_owner_action"])
        self.assertIn("git -C", by_branch["dirty-branch"]["review_command"])
        self.assertIn("status --short", by_branch["dirty-branch"]["review_command"])
        self.assertEqual("closed_unmerged", by_branch["closed-unmerged"]["bucket"])
        self.assertEqual(13, by_branch["closed-unmerged"]["pr_number"])
        self.assertEqual(1, by_branch["closed-unmerged"]["commits_not_in_base"])
        self.assertEqual("change closed-unmerged", by_branch["closed-unmerged"]["last_commit_subject"])
        self.assertRegex(by_branch["closed-unmerged"]["last_commit_date"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertIsInstance(by_branch["closed-unmerged"]["last_commit_age_days"], int)
        self.assertIn("owner review required", by_branch["closed-unmerged"]["next_owner_action"])
        self.assertIn("gh pr view 13", by_branch["closed-unmerged"]["review_command"])
        self.assertEqual("unmerged_no_pr", by_branch["unmerged-no-pr"]["bucket"])
        self.assertEqual(1, by_branch["unmerged-no-pr"]["commits_not_in_base"])
        self.assertEqual("change unmerged-no-pr", by_branch["unmerged-no-pr"]["last_commit_subject"])
        self.assertRegex(by_branch["unmerged-no-pr"]["last_commit_date"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertIsInstance(by_branch["unmerged-no-pr"]["last_commit_age_days"], int)
        self.assertIn("open a PR", by_branch["unmerged-no-pr"]["next_owner_action"])
        self.assertIn("log --oneline", by_branch["unmerged-no-pr"]["review_command"])
        self.assertIn("origin/main..HEAD", by_branch["unmerged-no-pr"]["review_command"])
        self.assertEqual(1, payload["summary"]["removable"])
        self.assertEqual(7, payload["summary"]["total"])
        self.assertTrue(payload["cleanup_decision"]["automated_removal_allowed"])
        self.assertTrue(payload["cleanup_decision"]["guarded_removal_available"])
        self.assertTrue(payload["cleanup_decision"]["owner_approval_required_before_apply"])
        self.assertEqual(1, payload["cleanup_decision"]["removable_count"])
        self.assertEqual(5, payload["cleanup_decision"]["owner_review_required_count"])
        self.assertEqual(
            {
                "closed_unmerged": 1,
                "dirty": 1,
                "open_pr": 2,
                "unmerged_no_pr": 1,
            },
            payload["cleanup_decision"]["blocked_by_buckets"],
        )
        self.assertTrue(payload["cleanup_decision"]["cleanup_approval_required"])
        self.assertEqual(
            "required_before_apply",
            payload["cleanup_decision"]["cleanup_approval_status"],
        )
        self.assertEqual(
            "owner_approval_required_before_apply; owner review required for non-removable buckets",
            payload["cleanup_decision"]["next_action"],
        )
        self.assertEqual(
            ["closed_unmerged", "dirty", "open_pr", "open_pr", "unmerged_no_pr"],
            [item["bucket"] for item in payload["owner_review_items"]],
        )
        self.assertEqual(
            ["closed-unmerged", "dirty-branch", None, "open-pr", "unmerged-no-pr"],
            [item["branch"] for item in payload["owner_review_items"]],
        )
        self.assertNotIn("main", [item["branch"] for item in payload["owner_review_items"]])
        self.assertNotIn("merged-clean", [item["branch"] for item in payload["owner_review_items"]])
        self.assertIn("review_command", payload["owner_review_items"][0])
        self.assertIn("last_commit_date", payload["owner_review_items"][0])
        self.assertIn("last_commit_age_days", payload["owner_review_items"][0])
        self.assertEqual(1, len(payload["safe_cleanup_items"]))
        self.assertEqual("merged_clean", payload["safe_cleanup_items"][0]["bucket"])
        self.assertEqual("merged-clean", payload["safe_cleanup_items"][0]["branch"])
        self.assertIn("HEAD is contained in origin/main", payload["safe_cleanup_items"][0]["reason"])
        self.assertIn("last_commit_date", payload["safe_cleanup_items"][0])
        self.assertIn("last_commit_age_days", payload["safe_cleanup_items"][0])
        self.assertTrue(payload["safe_cleanup_items"][0]["cleanup_approval_required"])
        self.assertEqual(
            "required_before_apply",
            payload["safe_cleanup_items"][0]["cleanup_approval_status"],
        )

    def test_text_output_includes_next_owner_action(self):
        result = run(
            [sys.executable, str(SCRIPT), "--base", "origin/main", str(self.repo)],
            env=self.env,
        )

        self.assertIn("next: eligible for guarded removal after owner approval with --apply --yes", result.stdout)
        self.assertIn("evidence: commits_not_in_base=1; last_commit_date=", result.stdout)
        self.assertIn("last_commit_age_days=", result.stdout)
        self.assertIn("last_commit=change closed-unmerged", result.stdout)
        self.assertIn("review: gh pr view 13", result.stdout)
        self.assertIn("review: gh pr view 14", result.stdout)
        self.assertIn("review: git -C", result.stdout)
        self.assertIn("next: review the PR; merge or close it before cleanup", result.stdout)
        self.assertIn("next: owner review required; open a PR, merge, or archive the branch", result.stdout)
        self.assertIn(
            "cleanup decision: owner approval required before applying 1 merged_clean worktree(s)",
            result.stdout,
        )
        self.assertIn("owner review required for 5 non-removable worktree(s)", result.stdout)

    def test_owner_review_markdown_packet(self):
        result = run(
            [
                sys.executable,
                str(SCRIPT),
                "--base",
                "origin/main",
                "--owner-review-markdown",
                str(self.repo),
            ],
            env=self.env,
        )

        self.assertIn("# Worktree Owner Review", result.stdout)
        self.assertIn("- Guarded removal available: `true`", result.stdout)
        self.assertIn("- Owner approval required before apply: `true`", result.stdout)
        self.assertNotIn("- Automated removal allowed:", result.stdout)
        self.assertIn("- Cleanup approval status: `required_before_apply`", result.stdout)
        self.assertIn(
            "| Bucket | Branch | PR | Commits not in base | Last activity | Last commit | Path | Reason | Next owner action | Review command |",
            result.stdout,
        )
        self.assertIn("open-pr", result.stdout)
        self.assertIn("[#12](https://example.test/pull/12)", result.stdout)
        self.assertIn("(detached)", result.stdout)
        self.assertIn("[#14](https://example.test/pull/14)", result.stdout)
        self.assertRegex(
            result.stdout,
            r"\| closed_unmerged \| closed-unmerged \| \[#13\]\(https://example\.test/pull/13\) \| 1 \| [^|]+T[^|]+ \| change closed-unmerged \|",
        )
        self.assertIn("gh pr view 13", result.stdout)
        self.assertIn("git -C", result.stdout)
        self.assertIn("preserve WIP", result.stdout)
        self.assertNotIn("| primary | main |", result.stdout)
        self.assertNotIn("| merged_clean | merged-clean |", result.stdout)
        self.assertIn("## Guarded Cleanup Candidates", result.stdout)
        self.assertIn(
            "These rows are read-only evidence; run the apply command only after owner approval for these concrete paths.",
            result.stdout,
        )
        self.assertIn(
            "| Branch | Approval | Commits not in base | Last activity | Last commit | Path | Reason |",
            result.stdout,
        )
        self.assertIn("| merged-clean | required before apply | 0 |", result.stdout)
        self.assertIn("HEAD is contained in origin/main", result.stdout)
        self.assertIn("python3 scripts/vidux-worktree-gc.py --base origin/main --apply --yes", result.stdout)

    def test_apply_requires_yes(self):
        result = run(
            [sys.executable, str(SCRIPT), "--base", "origin/main", "--apply", str(self.repo)],
            env=self.env,
            check=False,
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("--apply requires --yes", result.stderr)

    def test_apply_removes_only_merged_clean_worktrees(self):
        result = self.run_gc("--apply", "--yes")
        payload = json.loads(result.stdout)

        self.assertEqual([str((self.worktrees_dir / "merged-clean").resolve())], payload["removed"])
        self.assertEqual(6, payload["summary"]["total"])
        self.assertEqual(0, payload["summary"]["removable"])
        self.assertFalse(payload["cleanup_decision"]["automated_removal_allowed"])
        self.assertFalse(payload["cleanup_decision"]["guarded_removal_available"])
        self.assertFalse(payload["cleanup_decision"]["owner_approval_required_before_apply"])
        self.assertEqual(0, payload["cleanup_decision"]["removable_count"])
        self.assertEqual(5, payload["cleanup_decision"]["owner_review_required_count"])
        self.assertEqual("owner_review_required_before_cleanup", payload["cleanup_decision"]["next_action"])
        self.assertFalse(payload["cleanup_decision"]["cleanup_approval_required"])
        self.assertEqual("not_required", payload["cleanup_decision"]["cleanup_approval_status"])
        self.assertEqual(5, len(payload["owner_review_items"]))
        self.assertEqual([], payload["safe_cleanup_items"])
        self.assertFalse((self.worktrees_dir / "merged-clean").exists())
        self.assertTrue((self.worktrees_dir / "open-pr").exists())
        self.assertTrue((self.worktrees_dir / "detached-open-pr").exists())
        self.assertTrue((self.worktrees_dir / "dirty-branch").exists())
        self.assertTrue((self.worktrees_dir / "closed-unmerged").exists())
        self.assertTrue((self.worktrees_dir / "unmerged-no-pr").exists())

    def test_gitignored_non_regenerable_files_block_merged_clean_removal(self):
        # git status --porcelain misses gitignored paths; git worktree remove
        # can still delete them. A merged_clean tree with a stray .env must
        # classify dirty and stay off safe_cleanup_items / --apply.
        path = self.worktrees_dir / "merged-clean"
        (path / ".gitignore").write_text(".env\n__pycache__/\n", encoding="utf-8")
        git(path, "add", ".gitignore")
        git(path, "commit", "-m", "ignore env")
        # Re-sync origin/main to this tip so HEAD is still "merged" into base;
        # the dirty signal should come from ignored risk, not unmerged commits.
        git(self.repo, "update-ref", "refs/remotes/origin/main", "merged-clean")
        (path / ".env").write_text("SECRET=1\n", encoding="utf-8")
        # Regenerable ignored noise must not poison the risk list.
        (path / "__pycache__").mkdir()
        (path / "__pycache__" / "x.pyc").write_text("x", encoding="utf-8")

        # Sanity: porcelain (no --ignored) stays clean; only --ignored sees .env.
        porcelain = git(path, "status", "--porcelain").stdout.strip()
        self.assertEqual("", porcelain, f"unexpected tracked dirt: {porcelain!r}")

        result = self.run_gc()
        payload = json.loads(result.stdout)
        by_branch = {item["branch"]: item for item in payload["worktrees"]}
        item = by_branch["merged-clean"]

        self.assertEqual("dirty", item["bucket"])
        self.assertFalse(item["removable"])
        self.assertEqual(0, item["dirty_files"])
        self.assertIn(".env", item["ignored_risk_files"])
        self.assertTrue(
            all("pycache" not in p and not p.endswith(".pyc") for p in item["ignored_risk_files"]),
            item["ignored_risk_files"],
        )
        self.assertIn("gitignored file", item["reason"])
        self.assertEqual([], payload["safe_cleanup_items"])

        apply = self.run_gc("--apply", "--yes")
        apply_payload = json.loads(apply.stdout)
        self.assertEqual([], apply_payload["removed"])
        self.assertTrue(path.exists(), "worktree with gitignored .env must survive --apply")

    def test_hand_authored_file_inside_regenerable_named_dir_blocks_removal(self):
        # A directory whose NAME matches a regenerable-artifact convention
        # (build/, dist/, target/, vendor/ -- all common English/business
        # words too) was trusted wholesale regardless of its actual
        # contents. A hand-authored file living inside it was silently
        # deleted with zero warning. An earlier suffix-based override still
        # had gaps (extensionless files, case-sensitive matching) -- the fix
        # removes directory-name trust for ambiguous names entirely rather
        # than trying to enumerate every possible human-authored suffix.
        # This test still exercises the original scenario; see the two
        # sibling tests below for the specific gaps that motivated the
        # redesign.
        path = self.worktrees_dir / "merged-clean"
        (path / ".gitignore").write_text("build/\n", encoding="utf-8")
        git(path, "add", ".gitignore")
        git(path, "commit", "-m", "ignore build")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "merged-clean")
        (path / "build").mkdir()
        (path / "build" / "client-handoff-notes.txt").write_text(
            "irreplaceable text", encoding="utf-8",
        )

        result = self.run_gc()
        payload = json.loads(result.stdout)
        item = {i["branch"]: i for i in payload["worktrees"]}["merged-clean"]

        self.assertEqual("dirty", item["bucket"])
        self.assertFalse(item["removable"])
        self.assertIn("build/client-handoff-notes.txt", item["ignored_risk_files"])

        apply = self.run_gc("--apply", "--yes")
        apply_payload = json.loads(apply.stdout)
        self.assertEqual([], apply_payload["removed"])
        self.assertTrue(
            (path / "build" / "client-handoff-notes.txt").exists(),
            "hand-authored file inside a regenerable-named dir must survive --apply",
        )

    def test_ds_store_alone_does_not_block_merged_clean_removal(self):
        # `.DS_Store` was listed in
        # REGENERABLE_IGNORED_FILE_SUFFIXES, but Path('.DS_Store').suffix is
        # '' (pathlib treats a leading-dot-only filename as extensionless),
        # so the entry could never match -- every worktree ever opened in
        # macOS Finder was permanently misclassified dirty and blocked from
        # legitimate automated cleanup.
        path = self.worktrees_dir / "merged-clean"
        (path / ".gitignore").write_text(".DS_Store\n", encoding="utf-8")
        git(path, "add", ".gitignore")
        git(path, "commit", "-m", "ignore ds_store")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "merged-clean")
        (path / ".DS_Store").write_text("binary-ish", encoding="utf-8")

        result = self.run_gc()
        payload = json.loads(result.stdout)
        item = {i["branch"]: i for i in payload["worktrees"]}["merged-clean"]

        self.assertEqual("merged_clean", item["bucket"])
        self.assertTrue(item["removable"])
        self.assertEqual([], item["ignored_risk_files"])

    def test_missing_gh_cli_fails_cleanly_instead_of_crashing(self):
        # load_prs() shells out to `gh pr list`
        # unconditionally; with no `gh` executable on PATH this raised an
        # unhandled FileNotFoundError and a raw Python traceback before any
        # classification was attempted -- a first-time-open-source-cloner
        # trap, since the script is documented for direct invocation with
        # zero mention that `gh` (and auth) is a prerequisite.
        #
        # `git` and `gh` are frequently installed into the SAME bin
        # directory (e.g. Homebrew's /opt/homebrew/bin) -- stripping PATH
        # down to that directory would not actually remove `gh`. Instead,
        # build a scratch bin/ containing only a symlink to the real git
        # binary.
        import shutil

        real_git = Path(shutil.which("git")).resolve()
        fake_bin = self.root / "gh-free-bin"
        fake_bin.mkdir()
        (fake_bin / "git").symlink_to(real_git)
        env = os.environ.copy()
        env["PATH"] = str(fake_bin)

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--base", "origin/main", "--json", str(self.repo)],
            cwd=str(self.repo),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(
            any("gh" in w for w in payload.get("warnings", [])),
            payload.get("warnings"),
        )

    def test_extensionless_file_in_ambiguous_dir_blocks_removal(self):
        # An earlier HUMAN_AUTHORED_SUFFIXES override only matched files WITH
        # one of a fixed set of extensions -- Path('AUTHORS').suffix == '',
        # so a Makefile-style extensionless hand-authored file (AUTHORS,
        # NOTES, Dockerfile, ...) fell straight through to directory-name
        # trust and was permanently deleted. Reproduced 3 times (top-level,
        # 3-levels-deep, unicode filename); this test covers the same class.
        path = self.worktrees_dir / "merged-clean"
        (path / ".gitignore").write_text("vendor/\n", encoding="utf-8")
        git(path, "add", ".gitignore")
        git(path, "commit", "-m", "ignore vendor")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "merged-clean")
        (path / "vendor").mkdir()
        (path / "vendor" / "AUTHORS").write_text("irreplaceable text", encoding="utf-8")

        result = self.run_gc()
        payload = json.loads(result.stdout)
        item = {i["branch"]: i for i in payload["worktrees"]}["merged-clean"]

        self.assertEqual("dirty", item["bucket"])
        self.assertFalse(item["removable"])
        self.assertIn("vendor/AUTHORS", item["ignored_risk_files"])

        apply = self.run_gc("--apply", "--yes")
        apply_payload = json.loads(apply.stdout)
        self.assertEqual([], apply_payload["removed"])
        self.assertTrue(
            (path / "vendor" / "AUTHORS").exists(),
            "extensionless hand-authored file inside an ambiguous dir must survive --apply",
        )

    def test_uppercase_extension_file_in_ambiguous_dir_blocks_removal(self):
        # An earlier HUMAN_AUTHORED_SUFFIXES check was a case-sensitive set
        # lookup -- Path('Terms.PDF').suffix == '.PDF', not in the
        # (all-lowercase) set, so an uppercase-extension file also fell
        # through to directory-name trust and was permanently deleted.
        # Reproduced live.
        path = self.worktrees_dir / "merged-clean"
        (path / ".gitignore").write_text("dist/\n", encoding="utf-8")
        git(path, "add", ".gitignore")
        git(path, "commit", "-m", "ignore dist")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "merged-clean")
        (path / "dist").mkdir()
        (path / "dist" / "Client-Deal-Terms.PDF").write_text(
            "irreplaceable deal terms", encoding="utf-8",
        )

        result = self.run_gc()
        payload = json.loads(result.stdout)
        item = {i["branch"]: i for i in payload["worktrees"]}["merged-clean"]

        self.assertEqual("dirty", item["bucket"])
        self.assertFalse(item["removable"])
        self.assertIn("dist/Client-Deal-Terms.PDF", item["ignored_risk_files"])

        apply = self.run_gc("--apply", "--yes")
        apply_payload = json.loads(apply.stdout)
        self.assertEqual([], apply_payload["removed"])
        self.assertTrue(
            (path / "dist" / "Client-Deal-Terms.PDF").exists(),
            "uppercase-extension hand-authored file inside an ambiguous dir must survive --apply",
        )

    def test_nested_unambiguous_dir_name_under_an_untrusted_parent_still_blocks_removal(self):
        # Reproduced live, causing permanent deletion: the directory-trust
        # check used to match a trusted name ANYWHERE
        # in the path (`parts[:-1]`), so `stuff/node_modules/IMPORTANT.txt`
        # -- where `stuff/` is itself gitignored and is NOT a trusted name
        # -- was fully trusted purely because "node_modules" appears
        # somewhere in its ancestry. The actual ignored boundary here is
        # `stuff/`, an untrusted name; trust must be judged by the
        # OUTERMOST path segment only.
        path = self.worktrees_dir / "merged-clean"
        (path / ".gitignore").write_text("stuff/\n", encoding="utf-8")
        git(path, "add", ".gitignore")
        git(path, "commit", "-m", "ignore stuff")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "merged-clean")
        (path / "stuff" / "node_modules").mkdir(parents=True)
        (path / "stuff" / "node_modules" / "IMPORTANT.txt").write_text(
            "irreplaceable text", encoding="utf-8",
        )

        result = self.run_gc()
        payload = json.loads(result.stdout)
        item = {i["branch"]: i for i in payload["worktrees"]}["merged-clean"]

        self.assertEqual("dirty", item["bucket"])
        self.assertFalse(item["removable"])
        self.assertIn("stuff/node_modules/IMPORTANT.txt", item["ignored_risk_files"])

        apply = self.run_gc("--apply", "--yes")
        apply_payload = json.loads(apply.stdout)
        self.assertEqual([], apply_payload["removed"])
        self.assertTrue(
            (path / "stuff" / "node_modules" / "IMPORTANT.txt").exists(),
            "a trusted dir name nested under an untrusted ignored parent must survive --apply",
        )

    def test_log_suffix_outside_trusted_dir_blocks_removal(self):
        # `.log` was globally trusted regardless of
        # location, but a hand-authored `cache/diary.log` (a very plausible
        # real filename -- a diary, meeting notes) inside a correctly
        # untrusted ambiguous directory was silently treated as regenerable
        # by suffix match alone and permanently deleted.
        path = self.worktrees_dir / "merged-clean"
        (path / ".gitignore").write_text("cache/\n", encoding="utf-8")
        git(path, "add", ".gitignore")
        git(path, "commit", "-m", "ignore cache")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "merged-clean")
        (path / "cache").mkdir()
        (path / "cache" / "diary.log").write_text(
            "DO NOT DELETE - unpublished pricing analysis", encoding="utf-8",
        )

        result = self.run_gc()
        payload = json.loads(result.stdout)
        item = {i["branch"]: i for i in payload["worktrees"]}["merged-clean"]

        self.assertEqual("dirty", item["bucket"])
        self.assertFalse(item["removable"])
        self.assertIn("cache/diary.log", item["ignored_risk_files"])

        apply = self.run_gc("--apply", "--yes")
        apply_payload = json.loads(apply.stdout)
        self.assertEqual([], apply_payload["removed"])
        self.assertTrue(
            (path / "cache" / "diary.log").exists(),
            "a hand-authored .log file outside a trusted dir must survive --apply",
        )

    def test_log_suffix_inside_trusted_dir_still_auto_cleans(self):
        # .log files remain trusted when they genuinely sit inside an
        # unambiguous tool-managed directory -- only the blanket,
        # location-independent trust for `.log` was removed.
        path = self.worktrees_dir / "merged-clean"
        (path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
        git(path, "add", ".gitignore")
        git(path, "commit", "-m", "ignore pycache")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "merged-clean")
        (path / "__pycache__").mkdir()
        (path / "__pycache__" / "build.log").write_text("pip install log", encoding="utf-8")

        result = self.run_gc()
        payload = json.loads(result.stdout)
        item = {i["branch"]: i for i in payload["worktrees"]}["merged-clean"]

        self.assertEqual("merged_clean", item["bucket"])
        self.assertTrue(item["removable"])
        self.assertEqual([], item["ignored_risk_files"])

    def test_unambiguous_tool_dir_still_auto_cleans_without_per_file_check(self):
        # Sanity check for the redesign's OTHER direction: dirs no
        # human ever hand-populates (node_modules, __pycache__, .venv, ...)
        # must keep blanket directory-level trust -- a real node_modules
        # tree has thousands of files with every extension imaginable
        # (including extensionless bin scripts), and per-file suffix
        # checking would make it permanently unremovable.
        path = self.worktrees_dir / "merged-clean"
        (path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
        git(path, "add", ".gitignore")
        git(path, "commit", "-m", "ignore node_modules")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "merged-clean")
        (path / "node_modules" / "some-pkg").mkdir(parents=True)
        (path / "node_modules" / "some-pkg" / "index.js").write_text("module.exports = {}", encoding="utf-8")
        (path / "node_modules" / "some-pkg" / "bin").write_text("#!/usr/bin/env node", encoding="utf-8")
        (path / "node_modules" / "some-pkg" / "README.md").write_text("pkg readme", encoding="utf-8")

        result = self.run_gc()
        payload = json.loads(result.stdout)
        item = {i["branch"]: i for i in payload["worktrees"]}["merged-clean"]

        self.assertEqual("merged_clean", item["bucket"])
        self.assertTrue(item["removable"])
        self.assertEqual([], item["ignored_risk_files"])

    def test_invocation_worktree_is_never_removed(self):
        linked = self.worktrees_dir / "merged-clean"
        result = run(
            [
                sys.executable,
                str(SCRIPT),
                "--base",
                "origin/main",
                "--json",
                "--apply",
                "--yes",
                str(linked),
            ],
            env=self.env,
        )
        payload = json.loads(result.stdout)
        by_branch = {item["branch"]: item for item in payload["worktrees"]}

        self.assertEqual("primary", by_branch["merged-clean"]["bucket"])
        self.assertFalse(by_branch["merged-clean"]["removable"])
        self.assertTrue(linked.exists())


if __name__ == "__main__":
    unittest.main()
