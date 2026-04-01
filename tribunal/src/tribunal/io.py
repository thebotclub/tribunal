"""Atomic file I/O with advisory locking.

Provides safe read/write operations for Tribunal's state files to prevent
corruption from concurrent Claude Code sessions writing simultaneously.
Uses fcntl advisory locking on POSIX, msvcrt on Windows.
"""

from __future__ import annotations

import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Any


def _lock_exclusive(fd: int) -> None:
    """Acquire exclusive advisory lock on file descriptor."""
    if platform.system() == "Windows":
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock(fd: int) -> None:
    """Release advisory lock on file descriptor."""
    if platform.system() == "Windows":
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically with advisory file locking.

    Uses a lock file to serialize access, writes to a temp file, then
    atomically replaces the target via os.replace (POSIX atomic).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")

    fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT)
    try:
        _lock_exclusive(fd)
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=str(path.parent), suffix=".tmp", delete=False
            ) as tmp:
                json.dump(data, tmp, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = tmp.name
            os.replace(tmp_path, str(path))
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def locked_read_json(path: Path) -> dict[str, Any]:
    """Read a JSON file with shared advisory locking.

    Returns empty dict if file doesn't exist or is invalid.
    """
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
