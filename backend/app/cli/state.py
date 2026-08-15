"""Atomic, secret-free instance-state file for the ``lockverity`` CLI.

The state file is the durable, operator-visible record of a
single running Lockverity instance. It is written
atomically via :func:`tempfile.NamedTemporaryFile` +
:func:`os.replace` so a crash mid-write never produces a
half-written file. The file lives under the runtime home
``run/`` sub-directory and is named ``lockverity.state.json``.

Secret-safe schema
==================

The state file is a documented, *secret-free* projection
of the in-process state. The schema intentionally does
**not** persist:

  - the full Uvicorn command line (which would echo back
    every argument, including any ``--database-url`` that
    embeds credentials);
  - the database URL or any connection string that
    contains credentials;
  - provider tokens, request authorization headers, or
    other environment-derived secrets;
  - raw environment dumps;
  - passwords or secret values.

The state file is the canonical example of
"persistent state must be free of secrets". The CLI
generates a random non-secret :class:`uuid.UUID4`
``instance_id`` at start time, passes it to the private
child serve entry point as ``--instance-id``, and
records the UUID in the state file. The CLI's
identity-check module then asks the live OS process for
its command line at verification time and confirms the
``--instance-id <UUID>`` token is present -- the live
command line is *read* but never *written* to disk.

The schema
==========

The state file is a single JSON object with the following
stable top-level keys. The schema is the documented
contract used by the ``status`` and ``stop`` subcommands
and by future launchers; new keys are allowed in a
backward-compatible way, removed keys are not.

  - ``schema_version`` -- integer; the schema this file
    conforms to. Bumped on breaking changes only.
  - ``instance_id`` -- UUID4 string; unique per process.
    Stable for the lifetime of the process. The child
    server is started with ``--instance-id <UUID>`` and
    the live-process identity check confirms the token
    is present in the live command line at verification
    time.
  - ``pid`` -- integer; the OS process identifier of the
    Uvicorn worker.
  - ``created_at`` -- ISO 8601 UTC string; the recorded
    process creation time captured from the OS at start
    time. The verification compares this value against
    the live process creation time within a small
    tolerance to defeat PID reuse.
  - ``host`` -- string; the bound host (``127.0.0.1`` by
    default).
  - ``port`` -- integer; the bound port.
  - ``version`` -- string; the Lockverity product version.
  - ``home`` -- string; the absolute runtime-home path.
  - ``frontend_dist`` -- string; the absolute dist path
    the server is serving.
  - ``log_file`` -- string; the absolute path of the
    rotating log file.
  - ``started_at`` -- ISO 8601 UTC string; the time the
    CLI wrote the state file.
  - ``module`` -- string; the recorded Python module path
    the server is running from (``app.main:app``). Used
    as a soft identity hint; the strong identity is the
    ``instance_id`` token.
  - ``platform`` -- string; ``"windows"`` / ``"linux"`` /
    ``"darwin"``.
  - ``identity_token`` -- opaque short string derived from
    the recorded identity dimensions. Used as a fast
    pre-check before reading the live process; the full
    identity check is always re-run.

Atomic writes
=============

The writer uses a two-step ``tempfile + os.replace``
pattern. The temporary file is created in the same
directory as the final file (so the ``os.replace`` is
atomic on POSIX and best-effort on Windows). The writer
flushes and closes the temporary file before the replace
so a crash mid-write leaves the previous state file (or
no file) intact.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.cli.home import run_dir

STATE_FILE_NAME = "lockverity.state.json"
STATE_SCHEMA_VERSION = 1

# Bounded length for the recorded module path. The
# longest module path the runtime is expected to
# record is on the order of ``app.main:app``; 512
# is defensive.
MODULE_MAX_LEN = 512

# Tolerance for the recorded-vs-live process creation
# time comparison, in seconds. The recorded time is
# captured at start time and the live time is read at
# verification time. The two values must be within
# this tolerance; a mismatch beyond it indicates a
# PID-reuse and the identity check fails. The
# tolerance covers clock skew between the recording
# point and the verification point on the same host.
CREATION_TIME_TOLERANCE_SECONDS = 5.0


@dataclass(slots=True)
class InstanceState:
    """The durable, in-process view of a running instance.

    The dataclass is the canonical in-memory shape; the
    state file is a JSON projection of this dataclass.
    The :meth:`to_dict` and :meth:`from_dict` methods are
    the single conversion chokepoint so the JSON schema
    and the in-memory shape cannot drift apart.
    """

    schema_version: int
    instance_id: str
    pid: int
    created_at: str
    host: str
    port: int
    version: str
    home: str
    frontend_dist: str
    log_file: str
    started_at: str
    module: str
    platform: str
    identity_token: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-serialisable dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> InstanceState:
        """Build a :class:`InstanceState` from a parsed JSON dict.

        Unknown keys are silently dropped. Missing required
        keys raise :class:`ValueError` so a corrupt state
        file is detected at the boundary.
        """
        if not isinstance(payload, dict):
            raise ValueError("state file is not a JSON object; refusing to parse.")
        required = (
            "schema_version",
            "instance_id",
            "pid",
            "created_at",
            "host",
            "port",
            "version",
            "home",
            "frontend_dist",
            "log_file",
            "started_at",
            "module",
            "platform",
        )
        for key in required:
            if key not in payload:
                raise ValueError(
                    f"state file is missing required key: {key!r}. "
                    "The state file may be corrupt; remove it and "
                    "restart the server."
                )
        schema_version = int(payload["schema_version"])  # type: ignore[arg-type]
        pid = int(payload["pid"])  # type: ignore[arg-type]
        port = int(payload["port"])  # type: ignore[arg-type]
        return cls(
            schema_version=schema_version,
            instance_id=str(payload["instance_id"]),
            pid=pid,
            created_at=str(payload["created_at"]),
            host=str(payload["host"]),
            port=port,
            version=str(payload["version"]),
            home=str(payload["home"]),
            frontend_dist=str(payload["frontend_dist"]),
            log_file=str(payload["log_file"]),
            started_at=str(payload["started_at"]),
            module=str(payload["module"]),
            platform=str(payload["platform"]),
            identity_token=str(payload.get("identity_token", "")),
        )


def state_file_path(home: Path) -> Path:
    """Return the absolute path of the state file under ``home``.

    The function is pure: it does not touch the
    filesystem. The caller is expected to have called
    :func:`app.cli.home.ensure_home` so the parent
    directory exists.
    """
    return run_dir(home) / STATE_FILE_NAME


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_identity_token(
    *,
    pid: int,
    started_at: str,
    instance_id: str,
) -> str:
    """Return the opaque identity token for a running process.

    The token is a deterministic short string derived
    from the recorded identity dimensions. The token
    lets later commands confirm they are looking at
    the same instance the state file was written for
    without round-tripping through the kernel on every
    check.
    """
    payload = f"{pid}|{started_at}|{instance_id}"
    import hashlib

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def make_state(
    *,
    pid: int,
    created_at: str,
    host: str,
    port: int,
    version: str,
    home: Path,
    frontend_dist: Path,
    log_file: Path,
    started_at: str,
    module: str,
    instance_id: str,
    platform_name: str | None = None,
) -> InstanceState:
    """Build a fresh :class:`InstanceState`.

    The function is the single constructor used by the
    ``start`` command. It is a function (not a class
    method) so the input validation lives next to the
    construction and the field defaults are obvious.
    """
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError(f"pid must be a positive integer, got {pid!r}")
    if not isinstance(port, int) or not (0 <= port <= 65535):
        raise ValueError(f"port must be in 0..65535, got {port!r}")
    if not module.strip():
        raise ValueError("module must be a non-empty string")
    if not instance_id.strip():
        raise ValueError("instance_id must be a non-empty UUID string")
    bounded_module = module[:MODULE_MAX_LEN]
    platform_value = platform_name if platform_name is not None else _sys_platform()
    return InstanceState(
        schema_version=STATE_SCHEMA_VERSION,
        instance_id=instance_id,
        pid=pid,
        created_at=created_at,
        host=host,
        port=port,
        version=version,
        home=str(home.resolve(strict=False)),
        frontend_dist=str(frontend_dist.resolve(strict=False)),
        log_file=str(log_file.resolve(strict=False)),
        started_at=started_at,
        module=bounded_module,
        platform=platform_value,
        identity_token=make_identity_token(
            pid=pid,
            started_at=started_at,
            instance_id=instance_id,
        ),
    )


def _sys_platform() -> str:
    """Return the canonical ``platform`` value for the host.

    The function maps :data:`sys.platform` to the
    documented ``"windows"`` / ``"darwin"`` /
    ``"linux"`` values so the state file is portable
    across hosts and is not affected by the Python
    build flavour (``win32`` vs ``win_amd64`` etc.).
    """
    name = sys.platform
    if name.startswith("win"):
        return "windows"
    if name.startswith("darwin"):
        return "darwin"
    # Linux, BSD, other POSIX -- the runtime contract
    # calls all of them ``"linux"`` because the
    # subprocess / process-identity code paths use
    # the same ``/proc`` and ``os.kill`` primitives.
    return "linux"


def write_state(home: Path, state: InstanceState) -> Path:
    """Write ``state`` to disk atomically.

    The function writes to a temporary file in the same
    directory as the final file, flushes and closes the
    temporary, then :func:`os.replace` it onto the
    destination path. The replace is atomic on POSIX
    and best-effort on Windows; on either platform a
    crash mid-write leaves the previous state file (or
    no file) intact.
    """
    target = state_file_path(home)
    target.parent.mkdir(parents=True, exist_ok=True)
    # ``delete=False`` so the temporary file is preserved
    # across the ``os.replace`` call; ``delete=True``
    # would delete the file on ``close()`` even on the
    # success path.
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".lockverity.state.",
        suffix=".json.tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            with contextlib.suppress(OSError, AttributeError):
                # ``os.fsync`` may be unsupported on some
                # filesystems (network mounts, FUSE) and
                # ``handle.fileno`` may return ``-1`` if
                # the buffer was closed underneath us.
                # Either way, the data is flushed; the
                # OS decides when it hits the disk.
                os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        # Clean up the temporary file on any failure path
        # so a partial write does not accumulate.
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise
    return target


def read_state(home: Path) -> InstanceState | None:
    """Read the state file under ``home``.

    Returns ``None`` if the state file does not exist.
    Raises :class:`ValueError` if the file is unreadable,
    is not valid JSON, or is missing required fields.
    """
    path = state_file_path(home)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read state file {path}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"state file {path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"state file {path} is not a JSON object")
    return InstanceState.from_dict(payload)


def clear_state(home: Path) -> bool:
    """Remove the state file under ``home``.

    Returns ``True`` if a state file was removed,
    ``False`` if no state file existed. A failure to
    remove the file raises :class:`OSError` so the
    caller can surface the error to the operator.
    """
    path = state_file_path(home)
    # The foreground supervisor and an external ``stop`` command can both
    # observe the same child exit. On Windows, one process may briefly have
    # the state file open for its instance-id check while the other removes
    # it, yielding ``ERROR_SHARING_VIOLATION``. Retry that transient sharing
    # race for one bounded second; all other unlink errors still surface.
    attempts = 20 if sys.platform == "win32" else 1
    for attempt in range(attempts):
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except PermissionError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.05)
        else:
            return True
    return False  # pragma: no cover - loop always returns or raises


# Re-export ``field`` so the public dataclass-internals
# story stays self-contained. ``InstanceState`` does not
# use mutable defaults so this is a no-op for now, but
# having the symbol in scope keeps future migrations to
# ``field(default_factory=...)`` straightforward.
_ = field

__all__ = [
    "CREATION_TIME_TOLERANCE_SECONDS",
    "MODULE_MAX_LEN",
    "STATE_FILE_NAME",
    "STATE_SCHEMA_VERSION",
    "InstanceState",
    "clear_state",
    "make_identity_token",
    "make_state",
    "read_state",
    "state_file_path",
    "write_state",
]
