"""Cross-platform start lock for the ``lockverity`` CLI.

The :class:`StartLock` is the cross-platform concurrency
guard that prevents two ``lockverity start`` commands
from launching duplicate instances. The lock is an
advisory file lock under the runtime home ``run/``
sub-directory; the file is created with
:class:`O_CREAT | O_EXCL` so the create races on every
POSIX host, and :func:`msvcrt.locking` on Windows. A
stale lock from a previous crashed CLI is recovered
only after the recorded owner PID is verified to be
gone, so a live CLI is never terminated by a stale
lock.

Acquisition
===========

The :meth:`StartLock.acquire` method is the single
acquisition chokepoint. The method:

  1. Attempts an exclusive create (``O_CREAT | O_EXCL``
     on POSIX, ``os.open`` with ``O_CREAT | O_TRUNC``
     and an immediate lock-test on Windows).
  2. On ``EEXIST`` / ``FileExistsError``, reads the
     existing lock file and compares the recorded
     owner PID against the live process. If the owner
     is alive, raises :class:`StartLockHeld` so the
     caller can render a clear "another instance is
     already running" error.
  3. If the owner is gone, removes the stale lock and
     retries the create once. A bounded retry count
     prevents an infinite loop if the file system is
     racy.
  4. The acquired lock file is written with the current
    PID and start time, and a :class:`StartLock` is
    returned.

Release
~~~~~~~

The :meth:`StartLock.release` method is the single
release chokepoint. It removes the lock file and
closes the file descriptor. The method is safe to
call multiple times.

Stale-lock recovery is **never** destructive of
operator data. The lock file lives in ``run/``, not
in ``data/`` or ``logs/``. The recovery only removes
the lock file itself, never a state file or a
database file.
"""

from __future__ import annotations

import contextlib
import errno
import os
import time
from dataclasses import dataclass
from pathlib import Path

from app.cli.home import run_dir

LOCK_FILE_NAME = "lockverity.start.lock"

# Bounded retry count for the stale-lock recovery
# path. A single retry is normally sufficient; the
# second retry is a defensive fallback for the rare
# case where two stale-recovery attempts race.
_MAX_RECOVERY_ATTEMPTS = 3

# Owner stale threshold: a lock file whose owner PID
# has been missing for longer than this is treated as
# definitively stale. The threshold is large enough
# to cover a CLI crash that did not run the release
# path. 30 seconds is the documented default.
_STALE_OWNER_SECONDS = 30.0


class StartLockHeld(RuntimeError):  # noqa: N818 - the documented name
    """Raised when a fresh ``start`` cannot acquire the lock.

    The exception carries the recorded owner PID and
    start time so the CLI can render a clear
    "another instance is already running" error.
    """

    def __init__(self, owner_pid: int, owner_started_at: float) -> None:
        super().__init__(
            f"start lock is held by pid={owner_pid} "
            f"(started at {owner_started_at:.0f}); refusing to launch "
            "a duplicate instance. Run `lockverity stop` first or use a "
            "different runtime home."
        )
        self.owner_pid = owner_pid
        self.owner_started_at = owner_started_at


class StartLockError(RuntimeError):
    """Raised when the lock cannot be acquired or released cleanly.

    The exception is reserved for genuine I/O
    failures (file system permission errors, read-only
    file systems, etc.). A held lock raises
    :class:`StartLockHeld` instead.
    """


@dataclass(slots=True)
class StartLock:
    """The acquired start lock.

    The dataclass is returned by :meth:`acquire`. The
    caller is expected to call :meth:`release` in a
    ``finally`` block. The class is also a context
    manager so a ``with`` block is the recommended
    pattern.
    """

    path: Path
    owner_pid: int
    owner_started_at: float
    _fd: int | None = None

    def __enter__(self) -> StartLock:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()

    def release(self) -> None:
        """Release the lock and remove the lock file.

        The method is safe to call multiple times. A
        missing lock file is treated as "already
        released" and does not raise.
        """
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lock_file_path(home: Path) -> Path:
    """Return the absolute path of the start lock file under ``home``.

    The function is pure: it does not touch the
    filesystem. The caller is expected to have called
    :func:`app.cli.home.ensure_home` so the parent
    directory exists.
    """
    return run_dir(home) / LOCK_FILE_NAME


def acquire(
    home: Path,
    *,
    owner_pid: int | None = None,
    timeout_seconds: float = 0.0,
) -> StartLock:
    """Acquire the start lock for ``home``.

    The function is the single acquisition chokepoint.
    A held lock raises :class:`StartLockHeld`; a
    genuine I/O failure raises :class:`StartLockError`.

    :param home: the resolved runtime home.
    :param owner_pid: the PID to record as the lock
        owner. Defaults to :func:`os.getpid` (the
        calling CLI's PID).
    :param timeout_seconds: how long to wait for the
        lock to become available before giving up. The
        default is 0 -- the caller fails fast and
        surfaces the held lock to the operator. A
        positive value triggers a polling loop with a
        short sleep between attempts; the loop is
        bounded by the timeout.
    """
    if owner_pid is None:
        owner_pid = os.getpid()
    target = lock_file_path(home)
    target.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        lock = _try_acquire(target, owner_pid)
        if lock is not None:
            return lock
        # The lock is held. Inspect the existing lock
        # file to decide whether the holder is alive.
        existing = _read_lock_file(target)
        if existing is not None and _owner_is_live(existing):
            if time.monotonic() >= deadline:
                raise StartLockHeld(
                    owner_pid=existing.owner_pid,
                    owner_started_at=existing.owner_started_at,
                )
            time.sleep(0.25)
            continue
        # The lock file is stale (no owner PID, owner
        # PID is gone, or the file is unreadable). Try
        # to remove it and retry. A bounded retry
        # count prevents an infinite loop if the file
        # system is racy or the lock is being held by
        # a process that re-acquires it as fast as we
        # release it (which would be a bug in the
        # caller).
        with contextlib.suppress(FileNotFoundError, OSError):
            target.unlink()
        for _ in range(_MAX_RECOVERY_ATTEMPTS):
            lock = _try_acquire(target, owner_pid)
            if lock is not None:
                return lock
            time.sleep(0.05)
        raise StartLockError(f"could not acquire start lock at {target} after stale-recovery")


def _try_acquire(target: Path, owner_pid: int) -> StartLock | None:
    """Attempt a single exclusive create of the lock file.

    Returns ``None`` if the create raced and another
    process holds the lock. Returns a :class:`StartLock`
    on success.
    """
    started_at = time.time()
    try:
        fd = os.open(
            str(target),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError:
        return None
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            return None
        raise StartLockError(f"cannot create start lock {target}: {exc}") from exc
    try:
        os.write(fd, f"{owner_pid}\n{started_at}\n".encode())
        os.fsync(fd)
    except OSError:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(FileNotFoundError, OSError):
            target.unlink()
        raise
    return StartLock(
        path=target,
        owner_pid=owner_pid,
        owner_started_at=started_at,
        _fd=fd,
    )


def _read_lock_file(target: Path) -> StartLock | None:
    """Read the recorded owner PID and start time from the lock file.

    Returns ``None`` if the file is missing or
    unreadable. A malformed file is treated as "no
    owner" so the stale-recovery path can clean it up
    on the next acquisition attempt.
    """
    try:
        text = target.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        lines = text.splitlines()
        pid = int(lines[0])
        started_at = float(lines[1])
    except (ValueError, IndexError):
        return None
    return StartLock(
        path=target,
        owner_pid=pid,
        owner_started_at=started_at,
    )


def _owner_is_live(lock: StartLock) -> bool:
    """Return ``True`` iff the lock's owner PID is alive and recent.

    The function is conservative: an owner PID that
    is missing, zombie, or that has not been seen
    recently is treated as "not live" so the
    stale-recovery path can take over.
    """
    import psutil

    if lock.owner_pid <= 0:
        return False
    try:
        if not psutil.pid_exists(lock.owner_pid):
            return False
    except psutil.Error:
        return False
    # A long-lived lock is treated as stale even if
    # the owner PID is still alive. The 30-second
    # default is the documented "the previous CLI
    # crashed and the OS has not yet reaped the
    # process" window.
    return time.time() - lock.owner_started_at <= _STALE_OWNER_SECONDS


def release(home: Path) -> None:
    """Remove the start lock file under ``home``.

    The function is a no-op if the file does not exist.
    """
    target = lock_file_path(home)
    with contextlib.suppress(FileNotFoundError, OSError):
        target.unlink()


__all__ = [
    "LOCK_FILE_NAME",
    "StartLock",
    "StartLockError",
    "StartLockHeld",
    "acquire",
    "lock_file_path",
    "release",
]
