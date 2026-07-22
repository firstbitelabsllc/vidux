"""Filesystem primitives for local browser state.

Mutation targets must be regular files with exactly one directory entry. Final
component symlinks and hard links are rejected before any bytes are written,
and rewrites land through an atomic rename in an already-opened parent directory.
"""

from __future__ import annotations

import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class UnsafeFileAliasError(OSError):
    """A local state path is an alias or a non-regular filesystem object."""


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_CREATE_OPEN_ATTEMPTS = 8


def _reject_unsafe_stat(path_stat: os.stat_result) -> None:
    if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_nlink != 1:
        raise UnsafeFileAliasError("unsafe filesystem alias")


@contextmanager
def _parent_fd(path: Path, *, create: bool) -> Iterator[int]:
    parent = path.parent
    if create:
        parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC
    try:
        fd = os.open(parent, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise UnsafeFileAliasError("unsafe parent directory") from exc
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise UnsafeFileAliasError("unsafe parent directory")
        yield fd
    finally:
        os.close(fd)


def _existing_target_stat(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        target_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    _reject_unsafe_stat(target_stat)
    return target_stat


@contextmanager
def open_regular_fd(
    path: str | Path,
    flags: int,
    *,
    mode: int = 0o600,
    create_parent: bool = False,
) -> Iterator[int]:
    """Open one regular, single-link file without following its final component."""
    target = Path(path)
    with _parent_fd(target, create=create_parent) as parent_fd:
        attempts = _CREATE_OPEN_ATTEMPTS if flags & os.O_CREAT else 1
        fd: int | None = None
        last_missing: FileNotFoundError | None = None
        for _ in range(attempts):
            try:
                fd = os.open(
                    target.name,
                    flags | _NOFOLLOW | _CLOEXEC,
                    mode,
                    dir_fd=parent_fd,
                )
                break
            except FileNotFoundError as exc:
                # Darwin can report a one-shot ENOENT when several processes
                # race to create the same O_NOFOLLOW target. Retrying only the
                # create case preserves fail-closed reads and alias rejection;
                # a genuinely detached parent continues to fail after the
                # bounded attempts.
                last_missing = exc
            except OSError as exc:
                raise UnsafeFileAliasError("unsafe filesystem target") from exc
        if fd is None:
            assert last_missing is not None
            raise last_missing
        try:
            _reject_unsafe_stat(os.fstat(fd))
            yield fd
        finally:
            os.close(fd)


def read_bytes(path: str | Path) -> bytes:
    with open_regular_fd(path, os.O_RDONLY) as fd:
        with os.fdopen(os.dup(fd), "rb") as handle:
            return handle.read()


def read_text(
    path: str | Path,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> str:
    return read_bytes(path).decode(encoding, errors=errors)


def atomic_write_bytes(
    path: str | Path,
    data: bytes,
    *,
    mode: int = 0o600,
) -> None:
    """Replace a local file atomically without mutating an existing alias target."""
    target = Path(path)
    with _parent_fd(target, create=True) as parent_fd:
        _existing_target_stat(parent_fd, target.name)
        temp_name = f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        temp_fd: int | None = None
        try:
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                mode,
                dir_fd=parent_fd,
            )
            _reject_unsafe_stat(os.fstat(temp_fd))
            view = memoryview(data)
            while view:
                written = os.write(temp_fd, view)
                if written <= 0:
                    raise OSError("short filesystem write")
                view = view[written:]
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None
            os.replace(
                temp_name,
                target.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            os.fsync(parent_fd)
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass


def atomic_write_text(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
    mode: int = 0o600,
) -> None:
    atomic_write_bytes(path, text.encode(encoding), mode=mode)
