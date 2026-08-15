"""Cross-platform process identity for the ``lockverity`` CLI.

The :class:`LiveProcess` dataclass is the canonical
record of a single OS process for the purposes of the
``start`` / ``stop`` / ``status`` / ``doctor`` commands.
A recorded :class:`~app.cli.state.InstanceState` includes
a PID, a recorded creation time, an instance UUID, and a
module hint; this module rebuilds the identity from the
live OS to decide whether the recorded identity still
matches the process running with that PID.

Why psutil
==========

PIDs are reused. The OS may recycle a PID after a
process exits; a subsequent, unrelated process may
inherit the same numeric PID. Stopping a process by
PID alone would therefore risk terminating an
unrelated process. The CLI guards against that by
requiring the live process to match the recorded
identity on at least three independent dimensions:

  1. **PID** -- the recorded PID must still be live.
  2. **Creation time** -- the recorded creation time
     must match the live creation time within a small
     tolerance. A process that reused the same PID has
     a different creation time.
  3. **Instance ID** -- the live command line must
     contain the recorded ``--instance-id <UUID>``
     token. A different program that reused the PID
     has a different command line.

The implementation uses :mod:`psutil` for process
inspection and termination. The standard library
alone cannot reliably identify a PID on Windows (no
``/proc`` filesystem, the ``wmic`` CLI is deprecated
and may be missing on modern Windows, ``tasklist``
does not return creation time or the full command
line). psutil ships as a wheel on Windows, macOS, and
Linux and gives a uniform API for every dimension the
identity check needs.

Process identity check
======================

The :func:`verify_identity` function returns one of:

  - :class:`IdentityMatch` -- the live process matches
    the recorded identity on every checked dimension.
  - :class:`IdentityMismatch` -- the process is alive
    but does not match the recorded identity (stale
    state, PID reuse, or unrelated process).
  - :class:`ProcessGone` -- no process with the
    recorded PID exists on the host.
  - :class:`ProcessInaccessible` -- the process is
    alive but the operator cannot read its identity
    (insufficient privileges or the process exited
    during inspection).

All four outcomes are reported with the same
:class:`IdentityCheck` value so the ``stop`` and
``status`` commands can branch uniformly.

The implementation never uses ``shell=True``, never
shells out to ``wmic`` or ``tasklist`` for normal
operation, and never assumes ``/proc`` is available.
"""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from datetime import UTC
from typing import Literal

import psutil

# ``psutil.NoSuchProcess`` is raised when the PID does
# not exist (or has just been reaped). ``AccessDenied``
# is raised when the process is owned by another user.
# ``ZombieProcess`` is raised when the process is a
# zombie (Linux). All three are caught by the
# ``verify_identity`` and ``read_live_identity``
# functions and translated into the documented
# outcome classes.
_NoSuchProcess = psutil.NoSuchProcess
_AccessDenied = psutil.AccessDenied
_ZombieProcess = psutil.ZombieProcess

Platform = Literal["windows", "linux", "darwin"]


def _platform_name() -> str:
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
    # calls all of them ``"linux"`` because psutil
    # uses the same primitive for every POSIX host.
    return "linux"


@dataclass(slots=True, frozen=True)
class LiveProcess:
    """The live identity of a single OS process.

    The dataclass is the live equivalent of the
    :class:`~app.cli.state.InstanceState` identity
    fields. The two are compared dimension-by-dimension
    by :func:`verify_identity`. The ``cmdline`` is a
    list of arguments (without the interpreter) and
    is the source of truth for the ``--instance-id``
    match.
    """

    pid: int
    created_at: float  # UNIX timestamp, seconds, fractional
    cmdline: tuple[str, ...]
    module: str
    platform: Platform

    def cmdline_contains_instance_id(self, instance_id: str) -> bool:
        """Return ``True`` iff the live command line carries ``--instance-id <UUID>``.

        The function tolerates the two supported
        argument placements (``--instance-id <UUID>``
        and ``--instance-id=<UUID>``) and the
        documented arguments-only position (the value
        is the next token).
        """
        if not instance_id:
            return False
        for index, token in enumerate(self.cmdline):
            if (
                token == "--instance-id"
                and index + 1 < len(self.cmdline)
                and self.cmdline[index + 1] == instance_id
            ):
                return True
            if token.startswith("--instance-id=") and token.split("=", 1)[1] == instance_id:
                return True
        return False

    def cmdline_str(self) -> str:
        """Return a human-readable shell-quoted form of the command line.

        The function is for ``--json`` output and for
        log lines. The returned string is a
        *non-secret* projection: it is a copy of the
        live command line that the OS is holding, not
        a reconstruction of the recorded one.
        """
        return " ".join(shlex.quote(part) for part in self.cmdline)


@dataclass(slots=True, frozen=True)
class IdentityMatch:
    """The live process matches the recorded identity."""

    live: LiveProcess


@dataclass(slots=True, frozen=True)
class IdentityMismatch:
    """The process is alive but does not match the recorded identity.

    The class carries the recorded identity dimensions
    so the CLI can render an actionable error ("PID
    alive but command line differs -- PID reuse
    suspected") instead of a bare "mismatch" string.
    """

    reason: str
    recorded_pid: int
    recorded_created_at: str
    recorded_instance_id: str
    live_cmdline: tuple[str, ...] | None = None


@dataclass(slots=True, frozen=True)
class ProcessGone:
    """No process with the recorded PID exists on the host."""

    recorded_pid: int


@dataclass(slots=True, frozen=True)
class ProcessInaccessible:
    """The process is alive but the operator cannot read its identity.

    The class is distinct from :class:`IdentityMismatch`
    so the CLI can surface a clear "permission denied"
    error instead of a generic "mismatch".
    """

    recorded_pid: int
    reason: str


IdentityCheck = IdentityMatch | IdentityMismatch | ProcessGone | ProcessInaccessible


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def verify_identity(
    *,
    recorded_pid: int,
    recorded_created_at: str,
    recorded_instance_id: str,
    recorded_module: str,
    creation_time_tolerance_seconds: float = 5.0,
) -> IdentityCheck:
    """Compare the recorded identity against the live process.

    The function never raises for normal "process is
    gone" or "identity does not match" outcomes; the
    return value captures the outcome. Unexpected
    exceptions propagate to the caller.
    """
    if recorded_pid <= 0:
        # A non-positive recorded PID is treated as
        # "no process" -- the runner never records
        # such a value but the boundary is defensive.
        return ProcessGone(recorded_pid=recorded_pid)
    if not is_process_alive(recorded_pid):
        return ProcessGone(recorded_pid=recorded_pid)
    try:
        live = read_live_identity(recorded_pid)
    except _AccessDenied as exc:
        return ProcessInaccessible(recorded_pid=recorded_pid, reason=str(exc))
    except psutil.Error as exc:
        return ProcessInaccessible(recorded_pid=recorded_pid, reason=str(exc))
    if live is None:
        return ProcessGone(recorded_pid=recorded_pid)
    # PID reuse defence: the recorded creation time
    # must match the live creation time within a small
    # tolerance. A process that reused the same PID
    # has a different creation time. The comparison is
    # done in UNIX-timestamp space so the parse is
    # unambiguous and time-zone independent.
    if recorded_created_at and not _creation_times_match(
        recorded_created_at, live.created_at, creation_time_tolerance_seconds
    ):
        return IdentityMismatch(
            reason=(
                f"process creation time {live.created_at!r} does not match "
                f"recorded {recorded_created_at!r} (PID reuse suspected)"
            ),
            recorded_pid=recorded_pid,
            recorded_created_at=recorded_created_at,
            recorded_instance_id=recorded_instance_id,
            live_cmdline=live.cmdline,
        )
    # Strong identity: the live command line must
    # contain the recorded ``--instance-id <UUID>``
    # token. The ``--instance-id`` argument is the
    # documented fingerprint the CLI writes to the
    # state file and the child server reads to confirm
    # it is the expected instance.
    if recorded_instance_id and not live.cmdline_contains_instance_id(recorded_instance_id):
        return IdentityMismatch(
            reason=(
                f"process command line does not carry "
                f"--instance-id {recorded_instance_id!r} (PID reuse or "
                "unrelated process suspected)"
            ),
            recorded_pid=recorded_pid,
            recorded_created_at=recorded_created_at,
            recorded_instance_id=recorded_instance_id,
            live_cmdline=live.cmdline,
        )
    # Soft identity: the recorded module hint is
    # informational. The recorded value is the Python
    # module the CLI launched (``app.main:app``); the
    # live command line is expected to reference the
    # same module. A mismatch is reported as a soft
    # warning, not a hard stop, so the operator can
    # still inspect an instance that was launched by
    # an older CLI.
    if recorded_module and not _module_matches(recorded_module, live.cmdline):
        return IdentityMismatch(
            reason=(
                f"process command line does not reference the recorded module {recorded_module!r}"
            ),
            recorded_pid=recorded_pid,
            recorded_created_at=recorded_created_at,
            recorded_instance_id=recorded_instance_id,
            live_cmdline=live.cmdline,
        )
    return IdentityMatch(live=live)


# ---------------------------------------------------------------------------
# Live process reading
# ---------------------------------------------------------------------------


def is_process_alive(pid: int) -> bool:
    """Return ``True`` iff a process with ``pid`` exists.

    The function uses :func:`psutil.pid_exists` which
    does not signal the process; it is a kernel-state
    probe that returns ``True`` only when the PID is
    reachable. A ``True`` result covers normal and
    zombie processes; the :func:`read_live_identity`
    function rejects zombies at the next step.
    """
    if pid <= 0:
        return False
    try:
        return bool(psutil.pid_exists(pid))
    except psutil.Error:
        return False


def read_live_identity(pid: int) -> LiveProcess | None:
    """Return the live identity of ``pid`` or ``None`` if missing.

    A :class:`psutil.NoSuchProcess` (or the equivalent
    on the platform) is translated to ``None`` so the
    caller treats the process as gone. Other psutil
    errors propagate to the caller and are translated
    to :class:`ProcessInaccessible` by
    :func:`verify_identity`.
    """
    if pid <= 0:
        return None
    try:
        process = psutil.Process(pid)
    except _NoSuchProcess:
        return None
    except _ZombieProcess:
        # A zombie process has no live identity; the
        # CLI should treat it as gone and let the
        # parent reap it.
        return None
    try:
        create_time = float(process.create_time())
    except (psutil.Error, OSError):
        create_time = 0.0
    try:
        cmdline = tuple(process.cmdline())
    except (_AccessDenied, psutil.Error):
        # ``cmdline()`` can fail with ``AccessDenied`` on
        # some platforms even when ``pid_exists`` is
        # ``True``. The caller treats the process as
        # inaccessible.
        raise
    module = _module_from_cmdline(cmdline)
    return LiveProcess(
        pid=pid,
        created_at=create_time,
        cmdline=cmdline,
        module=module,
        platform=_platform_name(),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Termination
# ---------------------------------------------------------------------------


def terminate_process(
    pid: int,
    *,
    timeout: float = 10.0,
    instance_id: str | None = None,
) -> bool:
    """Terminate the live process gracefully.

    The function is the standard-library / psutil
    wrapper used by the ``stop`` command. It first
    sends ``SIGTERM`` (POSIX) / ``CTRL_BREAK_EVENT``
    (Windows) and waits up to ``timeout`` seconds for
    the process to exit. The caller escalates to
    :func:`force_terminate_process` if the process is
    still alive after the grace period.

    Returns ``True`` if the process exited within the
    grace period, ``False`` otherwise.
    """
    if pid <= 0:
        return True
    try:
        process = psutil.Process(pid)
    except _NoSuchProcess:
        return True
    except psutil.Error:
        return False
    try:
        if sys.platform == "win32" and instance_id:
            # A GUI-subsystem process has no console to receive Ctrl+C or
            # Ctrl+Break. Signal the per-instance named event created by
            # ``app.cli._serve`` so Uvicorn can run its lifespan shutdown.
            from app.cli._serve import signal_windows_shutdown

            if not signal_windows_shutdown(instance_id):
                return False
        else:
            process.terminate()
    except (psutil.Error, OSError):
        return False
    try:
        process.wait(timeout=timeout)
        return True
    except psutil.TimeoutExpired:
        return False
    except psutil.Error:
        return False


def force_terminate_process(pid: int, *, timeout: float = 5.0) -> bool:
    """Force-terminate ``pid``.

    On Windows, ``Process.kill`` is mapped to
    ``TerminateProcess`` (the documented forceful
    primitive). On POSIX it is mapped to ``SIGKILL``.
    The function waits up to ``timeout`` seconds for
    the process to exit and returns ``True`` if it did.
    """
    if pid <= 0:
        return True
    try:
        process = psutil.Process(pid)
    except _NoSuchProcess:
        return True
    except psutil.Error:
        return False
    try:
        process.kill()
    except (psutil.Error, OSError):
        return False
    try:
        process.wait(timeout=timeout)
        return True
    except psutil.TimeoutExpired:
        return False
    except psutil.Error:
        return False


def is_zombie(pid: int) -> bool:
    """Return ``True`` iff the process with ``pid`` is a zombie.

    A zombie is a process that has exited but has not
    yet been reaped by its parent. The CLI never
    sends signals to a zombie; the caller should
    leave the zombie for the parent to reap or use
    the documented ``wait()`` to clean it up.
    """
    if pid <= 0:
        return False
    try:
        process = psutil.Process(pid)
    except _NoSuchProcess:
        return False
    except psutil.Error:
        return False
    return _ZombieProcess is not None and process.status() == psutil.STATUS_ZOMBIE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _creation_times_match(
    recorded: str,
    live_unix: float,
    tolerance_seconds: float,
) -> bool:
    """Return ``True`` iff the recorded and live creation times are within tolerance.

    The recorded value is an ISO 8601 UTC string; the
    live value is a UNIX timestamp in seconds. The
    comparison converts the recorded value to a UNIX
    timestamp and computes the absolute difference.
    """
    from datetime import datetime

    try:
        recorded_dt = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
    except ValueError:
        return False
    recorded_unix = recorded_dt.timestamp()
    return abs(recorded_unix - live_unix) <= tolerance_seconds


def _module_from_cmdline(cmdline: tuple[str, ...]) -> str:
    """Return the Python module the command line is invoking.

    The function recognises the documented invocations:

      - ``python -m uvicorn app.main:app ...``
      - ``python -m uvicorn --app-dir <dir> app.main:app ...``
      - ``python -m app.cli._serve ...`` (the v2.1 Part B2 private wrapper)
      - ``lockverity-cli.exe --internal-serve ...`` (the v2.1 Part B3A frozen wrapper)

    The module is the first non-flag token after
    ``uvicorn`` (or the first ``-m`` value when the
    invocation is the private wrapper). The empty
    string is returned when the invocation form is
    not recognised.
    """
    # Frozen-mode dispatch: the documented v2.1
    # Part B3A ``--internal-serve`` launch token
    # invokes the same private entry point as
    # ``-m app.cli._serve``. The function returns
    # the canonical recorded module so the
    # identity check against the state file is
    # consistent across source and frozen modes.
    if "--internal-serve" in cmdline:
        return "app.cli._serve"
    for index, token in enumerate(cmdline):
        if token == "-m" and index + 1 < len(cmdline):
            module_name = cmdline[index + 1]
            j = index + 2
            while j < len(cmdline):
                candidate = cmdline[j]
                if candidate.startswith("-"):
                    if candidate in {
                        "--app-dir",
                        "--host",
                        "--port",
                        "--log-level",
                        "--log-config",
                        "--instance-id",
                    }:
                        j += 2
                    else:
                        j += 1
                    continue
                # ``-m uvicorn <module>`` -- return the
                # module after ``uvicorn``.
                if module_name == "uvicorn":
                    return candidate
                # ``-m app.cli._serve`` -- the
                # supervisor's private entry point. The
                # recorded module value is the wrapper
                # itself; the inner ``app.main:app`` is
                # hardcoded inside the wrapper and never
                # appears in the live command line.
                if module_name == "app.cli._serve":
                    return module_name
                return module_name
            return module_name if module_name != "uvicorn" else ""
    return ""


def _module_matches(recorded_module: str, live_cmdline: tuple[str, ...]) -> bool:
    """Return ``True`` iff the live command line invokes the recorded module.

    The match is a substring check: the live command
    line is expected to contain the recorded module
    string (the canonical ``app.main:app``). This
    is a soft check; the strong identity is the
    ``--instance-id`` token, which the
    :func:`verify_identity` function checks first.

    The v2.1 Part B3A frozen-mode dispatch uses
    ``--internal-serve`` as the launch token instead
    of ``-m app.cli._serve``; the function recognises
    the documented frozen-mode token as a valid
    match for the recorded ``app.cli._serve`` module
    so a frozen ``lockverity-cli.exe`` running the
    serve module is not reported as identity-mismatch.
    """
    if not recorded_module:
        return True
    if any(recorded_module in token for token in live_cmdline):
        return True
    # Frozen-mode match: the v2.1 Part B3A
    # ``--internal-serve`` dispatch token is the
    # documented equivalent of ``-m app.cli._serve``
    # for the frozen ``lockverity-cli.exe``. The
    # check is gated on the recorded module being
    # ``app.cli._serve`` so a different recorded
    # module cannot accidentally match the
    # ``--internal-serve`` token.
    return recorded_module == "app.cli._serve" and "--internal-serve" in live_cmdline


def _format_unix_iso(unix_seconds: float) -> str:
    """Return an ISO 8601 UTC string for ``unix_seconds``.

    The function mirrors the recorded ``created_at``
    field on :class:`app.cli.state.InstanceState`
    so test code can build a recorded value from a
    live :class:`LiveProcess` and feed it back to
    :func:`verify_identity`. The returned string is
    rounded to whole seconds (the recorded field is
    also whole seconds) so the creation-time
    comparison is unambiguous.
    """
    from datetime import datetime

    return (
        datetime.fromtimestamp(float(unix_seconds), tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


__all__ = [
    "IdentityCheck",
    "IdentityMatch",
    "IdentityMismatch",
    "LiveProcess",
    "Platform",
    "ProcessGone",
    "ProcessInaccessible",
    "force_terminate_process",
    "is_process_alive",
    "is_zombie",
    "read_live_identity",
    "terminate_process",
    "verify_identity",
]
