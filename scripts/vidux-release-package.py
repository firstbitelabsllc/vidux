#!/usr/bin/env python3
"""Fail closed when the npm release candidate is incomplete or over-broad."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
MAX_FILE_COUNT = 320
MAX_UNPACKED_BYTES = 4_000_000

REQUIRED_FILES = {
    ".claude-plugin/plugin.json",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "SKILL.md",
    "VERSION",
    "bin/vidux",
    "bin/vidux-browse",
    "browser/coordination_claims.py",
    "browser/safe_files.py",
    "browser/server.py",
    "browser/static/app.js",
    "browser/static/coordination-panel.js",
    "browser/static/index.html",
    "browser/static/steering-inbox.js",
    "browser/static/style.css",
    "browser/static/work-queue.js",
    "browser/steering_mailbox.py",
    "package.json",
    "scripts/vidux-claims.py",
    "scripts/vidux-config.py",
    "scripts/vidux-doctor-cli.sh",
    "scripts/vidux-init.sh",
    "scripts/vidux-release-package.py",
    "scripts/vidux-status.py",
    "scripts/vidux-steer.py",
}

FORBIDDEN_ROOTS = {
    ".git",
    ".github",
    ".opencode",
    "agent",
    "commands",
    "evaluations",
    "evidence",
    "investigations",
    "node_modules",
    "projects",
    "prompts",
    "tests",
    "test-results",
    "playwright-report",
    "blob-report",
}
FORBIDDEN_FILES = {
    ".gitleaks.toml",
    ".gitleaksignore",
    "AGENTS.md",
    "ASK-OWNER.md",
    "ASK-LEO.md",
    "PLAN.md",
    "browser/run_extract_pass.py",
    "impeccable-vidux.md",
    "package-lock.json",
    "playwright.config.ts",
    "vitest.config.mjs",
}
FORBIDDEN_PREFIXES = ("browser/receipts/",)
FORBIDDEN_SUFFIXES = {".jsonl", ".key", ".log", ".pem", ".pyc", ".pyo", ".token"}


def source_version(root: Path) -> str:
    for raw_line in (root / "VERSION").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            return line
    raise ValueError("VERSION has no non-comment version line")


def normalize_pack_path(raw_path: str) -> str:
    path = raw_path.replace("\\", "/").removeprefix("package/")
    return PurePosixPath(path).as_posix()


def is_forbidden(path: str) -> bool:
    pure = PurePosixPath(path)
    if not pure.parts:
        return True
    if (
        pure.parts[0] in FORBIDDEN_ROOTS
        or path in FORBIDDEN_FILES
        or path.startswith(FORBIDDEN_PREFIXES)
    ):
        return True
    if "__pycache__" in pure.parts or any(part.startswith(".env") for part in pure.parts):
        return True
    return pure.suffix.lower() in FORBIDDEN_SUFFIXES


def validate_release_candidate(
    package: dict[str, Any],
    pack: dict[str, Any],
    *,
    version: str,
    tracked_paths: Iterable[str],
    plugin_version: str,
    expected_version: str | None = None,
    dirty_packaged_paths: Iterable[str] = (),
    allow_dirty: bool = False,
) -> list[str]:
    errors: list[str] = []
    files = {
        normalize_pack_path(str(entry.get("path", "")))
        for entry in pack.get("files", [])
        if entry.get("path")
    }
    tracked = {normalize_pack_path(path) for path in tracked_paths}
    dirty = sorted({normalize_pack_path(path) for path in dirty_packaged_paths} & files)
    candidate_version = expected_version or version

    if expected_version is not None and version != expected_version:
        errors.append(
            f"VERSION source {version!r} does not match expected version {expected_version!r}"
        )

    if package.get("name") != "vidux":
        errors.append("package name must be 'vidux'")
    if package.get("private") is not False:
        errors.append("package.private must be false for a public release candidate")
    if package.get("version") != candidate_version:
        errors.append(
            f"package.json version {package.get('version')!r} does not match {candidate_version!r}"
        )
    if pack.get("version") != candidate_version:
        errors.append(f"packed version {pack.get('version')!r} does not match {candidate_version!r}")
    if plugin_version != candidate_version:
        errors.append(
            f"Claude plugin version {plugin_version!r} does not match {candidate_version!r}"
        )
    if package.get("bin") != {"vidux": "bin/vidux"}:
        errors.append("package bin must map 'vidux' to 'bin/vidux'")
    if not package.get("files"):
        errors.append("package files allowlist must be present and non-empty")
    if package.get("engines", {}).get("node") != ">=20":
        errors.append("package engines.node must be '>=20'")
    publish_config = package.get("publishConfig", {})
    if publish_config.get("access") != "public" or publish_config.get("provenance") is not True:
        errors.append("publishConfig must require public access and provenance")
    if package.get("scripts", {}).get("release:verify") != "python3 scripts/vidux-release-package.py":
        errors.append("package scripts.release:verify must run the release package verifier")
    if (
        package.get("scripts", {}).get("release:verify:dev")
        != "python3 scripts/vidux-release-package.py --allow-dirty"
    ):
        errors.append(
            "package scripts.release:verify:dev must expose the explicit dirty-byte developer route"
        )

    missing = sorted(REQUIRED_FILES - files)
    if missing:
        errors.append("packed artifact is missing required files: " + ", ".join(missing))

    forbidden = sorted(path for path in files if is_forbidden(path))
    if forbidden:
        errors.append("packed artifact contains forbidden files: " + ", ".join(forbidden))

    skill_files = sorted(
        path for path in files if PurePosixPath(path).name == "SKILL.md"
    )
    if skill_files != ["SKILL.md"]:
        errors.append(
            "packed artifact must contain exactly the root SKILL.md: "
            + (", ".join(skill_files) if skill_files else "none")
        )

    unexpected_benchmarks = sorted(path for path in files if path.startswith("benchmarks/"))
    if unexpected_benchmarks:
        errors.append(
            "packed artifact contains benchmark files (the local harness was removed): "
            + ", ".join(unexpected_benchmarks)
        )

    untracked = sorted(files - tracked)
    if untracked:
        errors.append("packed artifact contains files not tracked by git: " + ", ".join(untracked))

    if dirty and not allow_dirty:
        errors.append(
            "packed artifact contains dirty working-tree bytes; commit them or use the "
            "non-publishable --allow-dirty developer proof route: " + ", ".join(dirty)
        )

    file_count = len(files)
    if file_count > MAX_FILE_COUNT:
        errors.append(f"packed artifact has {file_count} files; limit is {MAX_FILE_COUNT}")
    unpacked_size = int(pack.get("unpackedSize", 0) or 0)
    if unpacked_size > MAX_UNPACKED_BYTES:
        errors.append(
            f"packed artifact is {unpacked_size} unpacked bytes; limit is {MAX_UNPACKED_BYTES}"
        )
    return errors


def run_json(command: list[str], *, cwd: Path) -> Any:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"{' '.join(command)} failed: {detail}")
    return json.loads(result.stdout)


def tracked_files(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git ls-files failed: {detail or result.returncode}")
    return {
        normalize_pack_path(path.decode("utf-8"))
        for path in result.stdout.split(b"\0")
        if path
    }


def _git_path_set(root: Path, command: list[str]) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(root), *command],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(command)} failed: {detail or result.returncode}")
    return {
        normalize_pack_path(path.decode("utf-8", errors="surrogateescape"))
        for path in result.stdout.split(b"\0")
        if path
    }


def dirty_files(root: Path) -> set[str]:
    """Return tracked changes plus untracked files using working-tree bytes.

    `npm pack` reads the working tree, not HEAD. A reproducible tarball can
    therefore still contain uncommitted bytes; release verification rejects
    those bytes by default and reports their exact paths.
    """

    changed = _git_path_set(root, ["diff", "--name-only", "-z", "HEAD", "--"])
    untracked = _git_path_set(root, ["ls-files", "--others", "--exclude-standard", "-z"])
    return changed | untracked


def packaged_paths_different_from_head(root: Path, paths: Iterable[str]) -> set[str]:
    """Compare the exact working-tree bytes and Git mode with ``HEAD``.

    Git status/diff intentionally honors assume-unchanged and skip-worktree
    flags. A release proof cannot: npm reads the working tree, so every packed
    path is compared directly with its committed blob and mode.
    """

    different: set[str] = set()
    for raw_path in paths:
        path = normalize_pack_path(raw_path)
        tree = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "-z", "HEAD", "--", path],
            capture_output=True,
            check=False,
        )
        if tree.returncode != 0 or not tree.stdout:
            different.add(path)
            continue
        try:
            metadata, _tree_path = tree.stdout.rstrip(b"\0").split(b"\t", 1)
            head_mode, object_type, object_sha = metadata.split()
        except ValueError:
            different.add(path)
            continue
        if object_type != b"blob":
            different.add(path)
            continue
        blob = subprocess.run(
            ["git", "-C", str(root), "cat-file", "blob", object_sha.decode("ascii")],
            capture_output=True,
            check=False,
        )
        worktree_path = root / path
        try:
            if worktree_path.is_symlink():
                worktree_bytes = os.readlink(worktree_path).encode("utf-8")
                worktree_mode = b"120000"
            else:
                worktree_bytes = worktree_path.read_bytes()
                worktree_mode = (
                    b"100755" if worktree_path.stat().st_mode & 0o111 else b"100644"
                )
        except OSError:
            different.add(path)
            continue
        if blob.returncode != 0 or blob.stdout != worktree_bytes or head_mode != worktree_mode:
            different.add(path)
    return different


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack_once(root: Path, destination: Path) -> tuple[dict[str, Any], str]:
    rows = run_json(
        [
            "npm",
            "pack",
            "--json",
            "--ignore-scripts",
            "--pack-destination",
            str(destination),
        ],
        cwd=root,
    )
    if not isinstance(rows, list) or len(rows) != 1:
        raise RuntimeError("npm pack returned an unexpected JSON payload")
    pack = rows[0]
    tarball = destination / str(pack.get("filename", ""))
    if not tarball.is_file():
        raise RuntimeError(f"npm pack did not create the reported tarball: {tarball}")
    return pack, sha256_file(tarball)


def verify(
    root: Path,
    *,
    expected_version: str | None = None,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    version = source_version(root)
    with tempfile.TemporaryDirectory(prefix="vidux-pack-") as temp:
        temp_root = Path(temp)
        first = temp_root / "first"
        second = temp_root / "second"
        first.mkdir()
        second.mkdir()
        pack, first_sha = pack_once(root, first)
        second_pack, second_sha = pack_once(root, second)
    packaged_paths = {
        normalize_pack_path(str(entry.get("path", "")))
        for entry in pack.get("files", [])
        if entry.get("path")
    }
    dirty_packaged_paths = sorted(packaged_paths_different_from_head(root, packaged_paths))
    errors = validate_release_candidate(
        package,
        pack,
        version=version,
        tracked_paths=tracked_files(root),
        plugin_version=str(plugin.get("version", "")),
        expected_version=expected_version,
        dirty_packaged_paths=dirty_packaged_paths,
        allow_dirty=allow_dirty,
    )
    if first_sha != second_sha:
        errors.append(
            "repeated npm pack runs were not byte-reproducible: "
            f"{first_sha} != {second_sha}"
        )
    if pack.get("files") != second_pack.get("files"):
        errors.append("repeated npm pack runs produced different file manifests")
    dirty_policy = (
        "clean"
        if not dirty_packaged_paths
        else "allowed_for_development_only"
        if allow_dirty
        else "rejected"
    )
    return {
        "ok": not errors,
        "name": pack.get("name"),
        "version": pack.get("version"),
        "filename": pack.get("filename"),
        "file_count": len(pack.get("files", [])),
        "packed_bytes": int(pack.get("size", 0) or 0),
        "unpacked_bytes": int(pack.get("unpackedSize", 0) or 0),
        "sha256": first_sha,
        "reproducible": first_sha == second_sha,
        "dirty_packaged_files": dirty_packaged_paths,
        "dirty_policy": dirty_policy,
        "publishable": not dirty_packaged_paths and not errors,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--expect-version")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help=(
            "Allow and report dirty packaged bytes for local development proof. "
            "This receipt is explicitly non-publishable."
        ),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        receipt = verify(
            args.root.resolve(),
            expected_version=args.expect_version,
            allow_dirty=args.allow_dirty,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        receipt = {"ok": False, "errors": [str(exc)]}

    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    elif receipt["ok"]:
        print(
            "vidux release package: OK "
            f"({receipt['version']}, {receipt['file_count']} files, "
            f"{receipt['unpacked_bytes']} unpacked bytes, sha256={receipt['sha256']}, "
            f"dirty_policy={receipt['dirty_policy']}, "
            f"dirty_files={len(receipt['dirty_packaged_files'])})"
        )
    else:
        print("vidux release package: FAILED", file=sys.stderr)
        for error in receipt["errors"]:
            print(f"- {error}", file=sys.stderr)
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
