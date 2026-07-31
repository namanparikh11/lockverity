"""Lockverity graphical launcher (v2.1 Part B3A).

The launcher is the clickable Windows entry point shipped
with the v2.1 Part B3A portable package. It does not
reimplement the runtime lifecycle; it delegates to the
accepted Part B2 ``app.cli`` functions and the accepted
Part B1 ``app.main`` FastAPI app.

The launcher:

  * Resolves the normal Lockverity runtime home
    (``%LOCALAPPDATA%\\Lockverity`` on Windows) unless
    ``LOCKVERITY_HOME`` is set.
  * Calls ``status`` to discover whether an instance is
    already running.
  * Forwards to ``start`` in the background if no
    instance is running, then opens the trusted local
    URL in the operator's default browser.
  * Reuses the running instance if one is already healthy.
  * Shows a native Windows message box on failure with
    the log path and the ``lockverity-cli.exe doctor``
    recommendation. The launcher never displays secrets
    or raw tracebacks to ordinary users.

The launcher uses only the Python standard library so
it has no new third-party dependencies. The
``ctypes.windll.user32`` import is guarded so the
module can be imported on non-Windows hosts (the
test suite runs on every platform).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from app.cli import process as cli_process
from app.cli.home import ensure_home, resolve_home
from app.cli.runner import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    is_loopback_host,
    probe_port,
)
from app.cli.state import read_state
from app.runtime_paths import application_root, is_frozen

logger = logging.getLogger("lockverity.launcher")

# Exit codes for the launcher. The codes are documented
# so the packaged installer can match them. The codes
# are chosen to be distinct from the CLI exit codes
# (``0`` success, ``1`` generic error, ``2`` health /
# allow-remote guard, ``64`` usage) so a wrapper can
# distinguish the two entry points from a single
# subprocess.
LAUNCHER_EXIT_OK = 0
LAUNCHER_EXIT_ERROR = 20
LAUNCHER_EXIT_PORT_IN_USE = 21
LAUNCHER_EXIT_MIGRATION = 22
LAUNCHER_EXIT_HEALTH = 23
LAUNCHER_EXIT_MISSING_DIST = 24


def _resolve_runtime_home() -> Path:
    """Return the runtime home the launcher will use.

    Precedence: ``LOCKVERITY_HOME`` env var, ``--home``
    CLI option, then the OS-appropriate default. The
    function delegates to :func:`app.cli.home.resolve_home`
    so the launcher and the CLI share the same home
    resolution rules.
    """
    explicit = os.environ.get("LOCKVERITY_HOME")
    if explicit:
        return resolve_home(cli_override=explicit)
    return resolve_home()


def _start_background(
    home: Path,
    host: str,
    port: int,
    frontend_dist: Path,
    database_url: str,
    log_level: str,
) -> int:
    """Start a background Lockverity instance and return the child PID.

    The function delegates to the documented
    ``lockverity-cli.exe start`` subprocess so the
    state file, the start lock, the migration, and
    the health probe are all owned by the v2.1
    Part B2 lifecycle code (the launcher never
    re-implements the lifecycle). The
    ``lockverity-cli start`` call is the documented
    graphical-launcher-to-CLI bridge; it publishes
    the runtime identity state, holds the start
    lock for the child's lifetime, and runs the
    migration before the server starts.

    The function returns the recorded ``pid`` from
    the CLI's start subprocess's published state
    file. The launcher shows the same trusted local
    URL in the default browser that ``open`` shows
    from a second terminal.
    """
    home = ensure_home(home)
    probe = probe_port(host, port)
    if probe.in_use:
        raise PortInUseError(f"port {host}:{port} is in use")
    import subprocess as _subprocess

    # The launcher's frozen ``sys.executable`` is
    # ``Lockverity.exe`` (the windowless launcher),
    # not ``lockverity-cli.exe``. The CLI exe is the
    # sibling at ``<portable_root>/lockverity-cli.exe``
    # and is the supported entry point for the
    # documented lifecycle. In source mode the
    # launcher's own ``sys.executable`` is the
    # Python interpreter and the launcher's argv is
    # ``python -m app.cli``.
    if is_frozen():
        cli_exe = Path(sys.executable).with_name("lockverity-cli.exe")
        if not cli_exe.is_file():
            raise RuntimeError(f"lockverity-cli.exe not found at {cli_exe}")
        argv = [str(cli_exe), "start", "--port", str(port)]
    else:
        argv = [
            sys.executable,
            "-m",
            "app.cli",
            "start",
            "--port",
            str(port),
        ]
    # The launcher's own process is short-lived; the
    # detached ``lockverity-cli start`` subprocess is
    # short-lived too (it exits after handing off the
    # serve child). The serve child survives the
    # launcher's exit because the CLI spawns it as a
    # detached ``Popen``.
    if sys.platform == "win32":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kwargs: dict[str, object] = {
            "stdin": _subprocess.DEVNULL,
            "stdout": _subprocess.DEVNULL,
            "stderr": _subprocess.DEVNULL,
            "close_fds": True,
            "creationflags": flags,
        }
    else:
        kwargs = {
            "stdin": _subprocess.DEVNULL,
            "stdout": _subprocess.DEVNULL,
            "stderr": _subprocess.DEVNULL,
            "close_fds": True,
            "start_new_session": True,
        }
    handle = _subprocess.Popen(argv, **kwargs)  # noqa: S603 - argv is built by us
    handle.wait()
    if handle.returncode != 0:
        raise RuntimeError(
            f"lockverity-cli start returned non-zero exit code "
            f"{handle.returncode}; the runtime log is at "
            f"{home / 'logs' / 'lockverity.log'}"
        )
    # The CLI's start subprocess wrote the state
    # file before exiting. Read it back so the
    # launcher can show the trusted URL in the
    # default browser.
    from app.cli.state import read_state

    state = read_state(home)
    if state is None:
        raise RuntimeError(
            f"lockverity-cli start did not publish a state file under {home / 'run'}"
        )
    return state.pid


def _wait_for_health(host: str, port: int, timeout: float) -> bool:
    """Block until ``/api/v1/health`` returns 200 or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://{host}:{port}/api/v1/health", timeout=2
            ) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    return False


def _read_status(home: Path) -> dict[str, object] | None:
    """Return the parsed status payload or ``None`` if no state file exists.

    The function is the read-only inspection path; the
    launcher never starts a second instance if one is
    already running and healthy.
    """
    try:
        state = read_state(home)
    except (ValueError, OSError):
        return None
    if state is None:
        return None
    identity = cli_process.verify_identity(
        recorded_pid=state.pid,
        recorded_created_at=state.created_at,
        recorded_instance_id=state.instance_id,
        recorded_module=state.module,
    )
    if isinstance(identity, cli_process.IdentityMatch):
        return {
            "status": "running",
            "pid": state.pid,
            "host": state.host,
            "port": state.port,
            "url": f"http://{state.host}:{state.port}/",
        }
    if isinstance(identity, cli_process.ProcessGone):
        return {"status": "stopped", "instance_id": state.instance_id}
    return {
        "status": "stale",
        "instance_id": state.instance_id,
        "reason": str(identity),
    }


class PortInUseError(RuntimeError):
    """Raised when the launcher's port is already bound by another process."""


class MigrationError(RuntimeError):
    """Raised when the database migration fails."""


class MissingDistError(RuntimeError):
    """Raised when the bundled frontend dist is missing or invalid."""


def _show_message_box(title: str, message: str) -> int:
    """Show a native Windows message box.

    The function is a thin adapter around
    ``ctypes.windll.user32.MessageBoxW``. It is a no-op
    on non-Windows hosts so the test suite can run on
    every platform; the test suite monkey-patches this
    function to record the messages without showing
    actual dialogs.
    """
    if sys.platform != "win32":
        # Non-Windows: log to stderr and return 0.
        # This branch is hit by the test suite on
        # POSIX and on Windows CI runners that do not
        # have an interactive desktop.
        sys.stderr.write(f"[{title}] {message}\n")
        return 0
    import ctypes

    # MB_OK | MB_ICONERROR | MB_TOPMOST
    flags = 0x00000000 | 0x00000010 | 0x00040000
    return ctypes.windll.user32.MessageBoxW(None, message, title, flags)


def _open_browser(url: str) -> bool:
    """Open the default browser to ``url``.

    The function is a thin adapter around
    :func:`webbrowser.open`; tests can monkey-patch it to
    record the URL without opening a real browser.
    """
    return bool(webbrowser.open(url))


def main(argv: list[str] | None = None) -> int:
    """Run the launcher.

    The function is the entry point declared in the
    PyInstaller spec (``lockverity.spec``). It is
    intentionally narrow: a thin shell over the
    accepted Part B2 / Part B1 logic with the
    launcher-specific UI adaptation.
    """
    parser = argparse.ArgumentParser(prog="Lockverity")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser after starting.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Override the port (default 8000).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Health-probe timeout in seconds (default 30).",
    )
    args = parser.parse_args(argv)

    home = _resolve_runtime_home()
    ensure_home(home)
    settings = _settings()
    frontend_dist = Path(settings.frontend_dist).expanduser()
    if not frontend_dist.is_absolute():
        frontend_dist = (application_root() / frontend_dist).resolve()
    if not (frontend_dist / "index.html").is_file():
        _show_message_box(
            "Lockverity - bundled frontend missing",
            f"The packaged frontend dist is missing or invalid.\n\n"
            f"Expected at: {frontend_dist}\n\n"
            f"Please re-download the Lockverity portable package.",
        )
        return LAUNCHER_EXIT_MISSING_DIST

    host = DEFAULT_HOST
    port = int(args.port)
    if not is_loopback_host(host):
        _show_message_box(
            "Lockverity - configuration error",
            "The launcher binds to loopback only. "
            "Remote exposure requires an explicit --allow-remote.",
        )
        return LAUNCHER_EXIT_ERROR

    # Step 1: probe existing instance.
    status = _read_status(home)
    if status and status.get("status") == "running":
        url = str(status.get("url") or f"http://{host}:{port}/")
        if not args.no_browser:
            _open_browser(url)
        return LAUNCHER_EXIT_OK

    # Step 2: start a background instance.
    try:
        _start_background(
            home=home,
            host=host,
            port=port,
            frontend_dist=frontend_dist,
            database_url=settings.database_url,
            log_level="info",
        )
    except PortInUseError as exc:
        _show_message_box(
            "Lockverity - port in use",
            f"Another process is bound to {host}:{port}.\n\n"
            f"{exc}\n\n"
            f"Stop the conflicting process or run the launcher with a "
            f"different --port. The log is at:\n{home / 'logs' / 'lockverity.log'}",
        )
        return LAUNCHER_EXIT_PORT_IN_USE
    except Exception as exc:  # broad: covers migration / dist / runtime
        # Distinguish migration failures so the user sees the
        # correct log path; the rest of the failures are
        # bundled into the generic "unexpected failure" path.
        msg = str(exc)
        if "alembic" in msg.lower() or "migration" in msg.lower():
            code = LAUNCHER_EXIT_MIGRATION
        else:
            code = LAUNCHER_EXIT_ERROR
        _show_message_box(
            "Lockverity - failed to start",
            f"The launcher could not start Lockverity.\n\n"
            f"{msg}\n\n"
            f"Run ``lockverity-cli.exe doctor`` for a diagnostic, or check "
            f"the log at:\n{home / 'logs' / 'lockverity.log'}",
        )
        return code

    # Step 3: wait for readiness.
    if not _wait_for_health(host, port, timeout=float(args.timeout)):
        _show_message_box(
            "Lockverity - health timeout",
            f"The server did not report healthy at "
            f"http://{host}:{port}/api/v1/health within "
            f"{float(args.timeout):.0f}s.\n\n"
            f"Check the log at:\n{home / 'logs' / 'lockverity.log'}",
        )
        return LAUNCHER_EXIT_HEALTH

    if not args.no_browser:
        _open_browser(f"http://{host}:{port}/")
    return LAUNCHER_EXIT_OK


def _settings() -> object:
    """Return a fresh :class:`app.core.Settings` instance.

    The launcher bypasses the LRU cache because the
    launcher is a short-lived process that may run
    before the cache is populated; the cache_clear
    also defends against a stale cache from a
    previous launcher invocation in the same Python
    process (e.g. a test runner).
    """
    from app.core.config import get_settings

    get_settings.cache_clear()
    return get_settings()


__all__ = [
    "LAUNCHER_EXIT_ERROR",
    "LAUNCHER_EXIT_HEALTH",
    "LAUNCHER_EXIT_MIGRATION",
    "LAUNCHER_EXIT_MISSING_DIST",
    "LAUNCHER_EXIT_OK",
    "LAUNCHER_EXIT_PORT_IN_USE",
    "MigrationError",
    "MissingDistError",
    "PortInUseError",
    "main",
]
