"""Hermetic install-truth coverage for ``vidux doctor``.

The fixtures isolate HOME, PATH, cached Git refs, pid state, and every common
skill mount. They deliberately provide no network remote; a logging Git shim
proves the doctor uses only read-only cached-ref commands.

Run with:
    python3 -m unittest tests.test_install_doctor -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
REAL_GIT = shutil.which("git")
COMMON_MOUNTS = (
    ".claude/skills/vidux",
    ".codex/skills/vidux",
    ".agents/skills/vidux",
    ".ai/skills-active/vidux",
    ".ai/skills-active-dir/vidux",
)


class InstallDoctorTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        if not REAL_GIT:
            self.skipTest("git is required for cached-ref fixtures")

    def _git(self, repo: Path, *args: str, capture: bool = False) -> str:
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": "Vidux Fixture",
                "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "Vidux Fixture",
                "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            }
        )
        result = subprocess.run(
            [str(REAL_GIT), "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        return result.stdout.strip() if capture else ""

    def _make_install(self, base: Path, *, source: bool = True, upstream: str = "main") -> Path:
        root = base / "vidux"
        (root / "bin").mkdir(parents=True)
        (root / "scripts").mkdir()
        shutil.copy2(ROOT / "bin" / "vidux", root / "bin" / "vidux")
        shutil.copy2(
            ROOT / "scripts" / "vidux-doctor-cli.sh",
            root / "scripts" / "vidux-doctor-cli.sh",
        )
        (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (root / "package.json").write_text('{"name":"vidux","version":"1.0.0"}\n', encoding="utf-8")
        (root / "scripts" / "vidux-config.py").write_text(
            textwrap.dedent(
                """\
                import json
                print(json.dumps({
                    "status": "ok",
                    "source": "fixture",
                    "live_config_present": False,
                    "using_example": True,
                }))
                """
            ),
            encoding="utf-8",
        )
        (root / "bin" / "vidux").chmod(0o755)
        (root / "scripts" / "vidux-doctor-cli.sh").chmod(0o755)

        if source:
            subprocess.run([str(REAL_GIT), "init", "-q", "-b", "main", str(root)], check=True)
            self._git(root, "add", ".")
            self._git(root, "commit", "-q", "-m", "fixture base")
            head = self._git(root, "rev-parse", "HEAD", capture=True)
            self._git(root, "update-ref", f"refs/remotes/origin/{upstream}", head)
            self._git(
                root,
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                f"refs/remotes/origin/{upstream}",
            )
        return root

    def _commit_local(self, root: Path, name: str) -> str:
        marker = root / f"{name}.txt"
        marker.write_text(f"{name}\n", encoding="utf-8")
        self._git(root, "add", marker.name)
        self._git(root, "commit", "-q", "-m", name)
        return self._git(root, "rev-parse", "HEAD", capture=True)

    def _commit_from(self, root: Path, parent: str, message: str) -> str:
        tree = self._git(root, "rev-parse", f"{parent}^{{tree}}", capture=True)
        return self._git(root, "commit-tree", tree, "-p", parent, "-m", message, capture=True)

    def _environment(self, base: Path, root: Path, *, path_root: Path | None = None) -> tuple[dict[str, str], Path]:
        home = base / "home"
        fakebin = base / "fakebin"
        tmpdir = base / "tmp"
        (home / "Development").mkdir(parents=True)
        fakebin.mkdir()
        tmpdir.mkdir()

        (fakebin / "vidux").symlink_to((path_root or root) / "bin" / "vidux")
        gh = fakebin / "gh"
        gh.write_text("#!/usr/bin/env bash\necho 'Logged in to github.com as fixture'\n", encoding="utf-8")
        gh.chmod(0o755)

        git_log = base / "git-calls.log"
        git_shim = fakebin / "git"
        git_shim.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                printf '%s\\n' "$*" >> "$VIDUX_TEST_GIT_LOG"
                exec {REAL_GIT} "$@"
                """
            ),
            encoding="utf-8",
        )
        git_shim.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                # Must be pinned, not just inherited: the doctor resolves its
                # config home as ${XDG_CONFIG_HOME:-$HOME/.config}, so an
                # ambient XDG_CONFIG_HOME outranks the fixture's HOME and sends
                # the token-permission check at a directory the test never
                # created. That check then passes vacuously and the doctor exits
                # 0. Unset on macOS, set on CI — which is exactly how this
                # passed locally while failing on Linux.
                "XDG_CONFIG_HOME": str(home / ".config"),
                "PATH": f"{fakebin}{os.pathsep}{env.get('PATH', '')}",
                "TMPDIR": str(tmpdir),
                "VIDUX_DEV_ROOT": str(home / "Development"),
                "VIDUX_DOCTOR_SKIP_NPM_TEST": "1",
                "VIDUX_TEST_GIT_LOG": str(git_log),
            }
        )
        env.pop("VIDUX_ROOT", None)
        return env, git_log

    def _run(self, root: Path, env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            [str(root / "bin" / "vidux"), "doctor", "--json"],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - richer failure
            self.fail(f"doctor did not emit JSON: {exc}\nstdout={result.stdout}\nstderr={result.stderr}")
        return result, payload

    def _mount_all(self, home: Path, target: Path) -> None:
        for relative in COMMON_MOUNTS:
            mount = home / relative
            mount.parent.mkdir(parents=True, exist_ok=True)
            mount.symlink_to(target)

    def _ref_snapshot(self, root: Path) -> str:
        refs = self._git(root, "for-each-ref", "--format=%(refname) %(objectname) %(symref)", capture=True)
        head = self._git(root, "rev-parse", "HEAD", capture=True)
        status = self._git(root, "status", "--porcelain=v2", "--branch", capture=True)
        return f"{head}\n{refs}\n{status}"

    def test_same_root_symlink_reports_full_parity_without_mutating_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._make_install(base)
            env, git_log = self._environment(base, root)
            self._mount_all(Path(env["HOME"]), root)
            before = self._ref_snapshot(root)

            result, payload = self._run(root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["summary"], {"total": 7, "passed": 7, "warnings": 0, "failures": 0})
            install = payload["install"]
            self.assertEqual(install["kind"], "source_checkout")
            self.assertEqual(install["branch"], "main")
            self.assertEqual(install["cached_upstream"], {"ref": "origin/main", "state": "same", "ahead": 0, "behind": 0})
            self.assertEqual(install["path"]["state"], "same_source")
            self.assertTrue(all(row["state"] == "same_source" for row in install["skill_mounts"]))
            self.assertEqual(before, self._ref_snapshot(root))

            calls = git_log.read_text(encoding="utf-8")
            for forbidden in (" fetch", " pull", " remote ", " update-ref", " checkout", " reset"):
                self.assertNotIn(forbidden, f" {calls}")

    def test_same_repo_worktree_mirror_is_same_source_until_stale(self) -> None:
        # The documented clean-mirror layout mounts skills from a detached
        # linked worktree of the same repository. Same object store + same
        # clean HEAD = byte-identical to the source, so the doctor must not
        # report it as a foreign source. Once the source advances past the
        # pinned mirror, the bytes genuinely differ and a warning is correct.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._make_install(base / "current")
            env, _ = self._environment(base, root)
            home = Path(env["HOME"])
            self._mount_all(home, root)
            mirror = base / "mirror"
            self._git(root, "worktree", "add", "--detach", str(mirror), "origin/main")
            mirror_mount = home / COMMON_MOUNTS[0]
            mirror_mount.unlink()
            mirror_mount.symlink_to(mirror)

            result, payload = self._run(root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "pass", payload)
            mounts = {row["path"]: row for row in payload["install"]["skill_mounts"]}
            self.assertEqual(mounts[str(mirror_mount)]["state"], "same_source")

            # Advance the source checkout: the pinned mirror is now stale.
            self._commit_local(root, "advance-past-mirror")

            result, payload = self._run(root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "warn", payload)
            mounts = {row["path"]: row for row in payload["install"]["skill_mounts"]}
            self.assertEqual(mounts[str(mirror_mount)]["state"], "same_repo_stale")

    def test_same_repo_worktree_mirror_is_stale_when_source_is_dirty(self) -> None:
        # Byte-identity requires BOTH checkouts clean. When the mirror sits on
        # the same clean HEAD but the source checkout has uncommitted changes,
        # the mounted bytes are stale relative to the source being audited, so
        # the same-repo exemption must not fire.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._make_install(base / "current")
            env, _ = self._environment(base, root)
            home = Path(env["HOME"])
            self._mount_all(home, root)
            mirror = base / "mirror"
            self._git(root, "worktree", "add", "--detach", str(mirror), "origin/main")
            mirror_mount = home / COMMON_MOUNTS[0]
            mirror_mount.unlink()
            mirror_mount.symlink_to(mirror)

            # Dirty the source checkout without advancing HEAD: the mirror is
            # clean and on the same commit, but the source working tree now
            # carries changes the mirror cannot serve. Use an untracked file so
            # the doctor CLI the source runs stays intact.
            (root / "uncommitted.txt").write_text("scratch\n", encoding="utf-8")

            result, payload = self._run(root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "warn", payload)
            mounts = {row["path"]: row for row in payload["install"]["skill_mounts"]}
            self.assertEqual(mounts[str(mirror_mount)]["state"], "same_repo_stale")

    def test_subdirectory_of_mirror_is_not_same_source(self) -> None:
        # A mount pointing inside the repository serves only a subtree; it
        # must not ride the same-repo identity to same_source.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._make_install(base / "current")
            env, _ = self._environment(base, root)
            home = Path(env["HOME"])
            self._mount_all(home, root)
            mirror = base / "mirror"
            self._git(root, "worktree", "add", "--detach", str(mirror), "origin/main")
            sub_mount = home / COMMON_MOUNTS[0]
            sub_mount.unlink()
            sub_mount.symlink_to(mirror / "scripts")

            result, payload = self._run(root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "warn", payload)
            mounts = {row["path"]: row for row in payload["install"]["skill_mounts"]}
            self.assertEqual(mounts[str(sub_mount)]["state"], "different_source")

    def test_different_path_and_mount_source_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._make_install(base / "current")
            other = self._make_install(base / "other")
            env, _ = self._environment(base, root, path_root=other)
            home = Path(env["HOME"])
            self._mount_all(home, root)
            wrong_mount = home / COMMON_MOUNTS[0]
            wrong_mount.unlink()
            wrong_mount.symlink_to(other)

            result, payload = self._run(root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "warn")
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["install"]["path"]["state"], "different_source")
            mounts = {row["path"]: row for row in payload["install"]["skill_mounts"]}
            self.assertEqual(mounts[str(wrong_mount)]["state"], "different_source")

    def test_packaged_install_has_no_git_freshness_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._make_install(base, source=False)
            env, git_log = self._environment(base, root)

            result, payload = self._run(root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["install"]["kind"], "packaged")
            self.assertIsNone(payload["install"]["sha"])
            self.assertEqual(payload["install"]["branch"], "packaged")
            self.assertEqual(payload["install"]["cached_upstream"]["state"], "not_applicable")
            self.assertFalse(git_log.exists(), "packaged install should not invoke git")

    def test_origin_head_alternate_branch_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._make_install(base, upstream="trunk")
            env, _ = self._environment(base, root)

            result, payload = self._run(root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            upstream = payload["install"]["cached_upstream"]
            self.assertEqual(upstream, {"ref": "origin/trunk", "state": "same", "ahead": 0, "behind": 0})

    def test_origin_main_is_fallback_when_origin_head_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._make_install(base)
            self._git(root, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
            env, _ = self._environment(base, root)

            result, payload = self._run(root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            upstream = payload["install"]["cached_upstream"]
            self.assertEqual(upstream, {"ref": "origin/main", "state": "same", "ahead": 0, "behind": 0})

    def test_cached_ahead_behind_diverged_and_detached_states(self) -> None:
        scenarios = {
            "ahead": ("ahead", 1, 0, "pass"),
            "behind": ("behind", 0, 1, "warn"),
            "diverged": ("diverged", 1, 1, "warn"),
            "detached": ("same", 0, 0, "warn"),
        }
        for scenario, expected in scenarios.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = self._make_install(base)
                base_sha = self._git(root, "rev-parse", "HEAD", capture=True)
                if scenario == "ahead":
                    self._commit_local(root, "local-ahead")
                elif scenario == "behind":
                    upstream_sha = self._commit_from(root, base_sha, "upstream-ahead")
                    self._git(root, "update-ref", "refs/remotes/origin/main", upstream_sha)
                elif scenario == "diverged":
                    self._commit_local(root, "local-diverged")
                    upstream_sha = self._commit_from(root, base_sha, "upstream-diverged")
                    self._git(root, "update-ref", "refs/remotes/origin/main", upstream_sha)
                elif scenario == "detached":
                    self._git(root, "checkout", "-q", "--detach", "HEAD")

                env, _ = self._environment(base, root)
                result, payload = self._run(root, env)

                self.assertEqual(result.returncode, 0, result.stderr)
                upstream = payload["install"]["cached_upstream"]
                self.assertEqual(upstream["state"], expected[0])
                self.assertEqual(upstream["ahead"], expected[1])
                self.assertEqual(upstream["behind"], expected[2])
                self.assertEqual(payload["status"], expected[3])
                if scenario == "detached":
                    self.assertEqual(payload["install"]["branch"], "detached")

    def test_linked_worktree_gitfile_is_source_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            primary = self._make_install(base / "primary")
            linked = base / "linked"
            self._git(primary, "worktree", "add", "-q", "-b", "linked-fixture", str(linked), "HEAD")
            self.assertTrue((linked / ".git").is_file())
            env, _ = self._environment(base, linked)

            result, payload = self._run(linked, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["install"]["kind"], "git_worktree")
            self.assertEqual(payload["install"]["branch"], "linked-fixture")
            self.assertEqual(payload["install"]["cached_upstream"]["state"], "same")

    def test_dead_pid_residue_is_warning_not_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._make_install(base, source=False)
            env, _ = self._environment(base, root)
            state_dir = Path(env["HOME"]) / ".local" / "state" / "vidux"
            state_dir.mkdir(parents=True)
            (state_dir / "browser.pid").write_text("99999999\n", encoding="utf-8")

            result, payload = self._run(root, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "warn")
            self.assertTrue(payload["warning_only"])
            self.assertIn("stale residue", " ".join(row["message"] for row in payload["checks"]))

    def test_plaintext_summary_names_failure_count_not_warnings_only(self) -> None:
        # A hard [FAIL] must reach the bottom-line human summary, not just the
        # (already-correct) exit code. A non-600 token file is a deterministic
        # hard failure (check 3). Before the fix the summary printed only the
        # warning tally, so a bottom-line glance read "N checks passed, K
        # warning(s)" as clean while the process was actually exiting 1.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._make_install(base, source=False)
            env, _ = self._environment(base, root)
            token_dir = Path(env["HOME"]) / ".config" / "vidux"
            token_dir.mkdir(parents=True)
            bad_token = token_dir / "leak.token"
            bad_token.write_text("secret\n", encoding="utf-8")
            bad_token.chmod(0o644)

            result = subprocess.run(
                [str(root / "bin" / "vidux"), "doctor"],
                capture_output=True,
                text=True,
                timeout=20,
                env=env,
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            summary = result.stdout.strip().splitlines()[-1]
            self.assertIn("checks passed", summary)
            self.assertIn("failure(s)", summary)


if __name__ == "__main__":
    unittest.main()
