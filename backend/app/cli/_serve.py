"""Private Lockverity CLI child-serve entry point.

The ``lockverity`` CLI supervisor launches the
production Uvicorn server as a detached subprocess.
The supervisor must be able to identify the child
at ``stop`` / ``status`` time so a PID-reuse by an
unrelated process cannot lead to the wrong process
being terminated.

Uvicorn's own CLI does not accept a custom
``--instance-id`` argument; the supervisor needs a
private entry point that consumes the argument and
then configures :class:`uvicorn.Server` with the rest
of the documented Uvicorn arguments. On Windows the
entry point also owns a per-instance named event so a
windowless GUI process can request graceful lifespan
shutdown without relying on console signals.

The entry point is a private module; downstream
integrators should not import it directly. The
documented CLI is :mod:`app.cli.main` and the
documented runner is :mod:`app.cli.runner`.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import logging
import signal
import sys
import threading
from collections.abc import Sequence

logger = logging.getLogger("lockverity.cli.serve")

_WINDOWS_STOP_EVENT_PREFIX = r"Local\LockverityBackendStop-"
_EVENT_MODIFY_STATE = 0x0002
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0
_INFINITE = 0xFFFFFFFF

# The argument name the supervisor appends to the
# child argv. The name is reserved: Uvicorn does not
# accept it, so the private entry point strips it
# before calling :func:`uvicorn.run`. The supervisor
# records the value in the state file and uses it to
# confirm the live process identity at ``stop`` /
# ``status`` time.
INSTANCE_ID_ARG = "--instance-id"

# Uvicorn argument names we expect to consume before
# delegating to :func:`uvicorn.run`. The list is
# intentionally narrow; Uvicorn's own argparse will
# validate the rest.
_UVICORN_KNOWN_FLAGS_WITH_VALUE: frozenset[str] = frozenset(
    {
        "--host",
        "--port",
        "--log-level",
        "--log-config",
        "--uds",
        "--fd",
        "--loop",
        "--http",
        "--ws",
        "--lifespan",
        "--interface",
        "--reload-dir",
    }
)


def _windows_shutdown_event_name(instance_id: str) -> str:
    """Return the bounded per-instance Windows shutdown event name."""
    import uuid

    canonical = str(uuid.UUID(instance_id))
    return _WINDOWS_STOP_EVENT_PREFIX + canonical


def signal_windows_shutdown(instance_id: str) -> bool:
    """Signal a running backend's graceful-shutdown event on Windows."""
    if sys.platform != "win32":
        return False
    try:
        name = _windows_shutdown_event_name(instance_id)
    except (ValueError, AttributeError, TypeError):
        return False
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.OpenEventW.restype = ctypes.c_void_p
    kernel32.SetEvent.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenEventW(_EVENT_MODIFY_STATE | _SYNCHRONIZE, False, name)
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)


class _WindowsShutdownEvent:
    """Own the backend's named Windows event and map it to Uvicorn exit."""

    def __init__(self, instance_id: str, server: object) -> None:
        self._server = server
        self._handle: int | None = None
        self._thread: threading.Thread | None = None
        if sys.platform != "win32":
            return
        name = _windows_shutdown_event_name(instance_id)
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateEventW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_wchar_p,
        ]
        kernel32.CreateEventW.restype = ctypes.c_void_p
        kernel32.SetEvent.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        handle = kernel32.CreateEventW(None, True, False, name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateEventW failed")
        self._handle = int(handle)
        self._thread = threading.Thread(
            target=self._wait,
            name="lockverity-backend-shutdown-event",
            daemon=True,
        )

    def _wait(self) -> None:
        if self._handle is None:
            return
        result = ctypes.windll.kernel32.WaitForSingleObject(self._handle, _INFINITE)
        if result == _WAIT_OBJECT_0:
            self._server.should_exit = True  # type: ignore[attr-defined]

    def __enter__(self) -> _WindowsShutdownEvent:
        if self._thread is not None:
            self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._handle is None:
            return
        ctypes.windll.kernel32.SetEvent(self._handle)
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        ctypes.windll.kernel32.CloseHandle(self._handle)
        self._handle = None


def _split_argv(argv: Sequence[str]) -> tuple[str | None, list[str]]:
    """Return ``(instance_id, remaining_argv)``.

    The function walks ``argv`` and extracts the
    ``--instance-id`` argument (or its ``--instance-id=<UUID>``
    form). Everything else is returned as
    ``remaining_argv`` in the original order. A
    missing ``--instance-id`` is returned as
    ``None``; the supervisor always passes the flag
    in production but a developer running the entry
    point by hand may omit it.
    """
    instance_id: str | None = None
    remaining: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == INSTANCE_ID_ARG:
            if index + 1 < len(argv):
                instance_id = argv[index + 1]
                index += 2
                continue
            index += 1
            continue
        if token.startswith(INSTANCE_ID_ARG + "="):
            instance_id = token.split("=", 1)[1]
            index += 1
            continue
        remaining.append(token)
        index += 1
    return instance_id, remaining


def _parse_uvicorn_args(remaining: Sequence[str]) -> argparse.Namespace:
    """Parse the Uvicorn-relevant arguments from ``remaining``.

    The function mirrors the small subset of Uvicorn
    flags the supervisor forwards (``--host``,
    ``--port``, ``--log-level``) so a developer can
    run the entry point by hand without typing the
    full Uvicorn option list. Uvicorn itself will
    re-parse the rest.
    """
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--app-dir", default=None)
    return parser.parse_args(list(remaining))


def main(argv: Sequence[str] | None = None) -> int:
    """Strip the supervisor's ``--instance-id`` flag and run Uvicorn.

    The function is the private child entry point. It
    is called from a subprocess spawned by
    :func:`app.cli.runner.start`; the function never
    runs in the supervisor's process. The supervisor
    waits for the child to be reachable on the
    configured host / port and then records the
    instance ID in the state file.
    """
    if argv is None:
        argv = sys.argv[1:]
    instance_id, remaining = _split_argv(argv)
    parsed = _parse_uvicorn_args(remaining)
    # The Uvicorn module path is the documented
    # single-port runtime. The supervisor always
    # passes ``app.main:app`` via the documented
    # argv; we do not accept a ``--app`` argument
    # because the supervisor is the only legitimate
    # caller.
    app_module = "app.main:app"
    logger.info(
        "lockverity cli.serve starting (instance_id=%s, host=%s, port=%d)",
        instance_id,
        parsed.host,
        parsed.port,
    )
    # Windows ``CTRL_BREAK_EVENT`` (sent by the
    # supervisor or by an external signal delivery)
    # arrives as :data:`signal.SIGBREAK`, which the
    # CPython default action terminates without
    # raising :class:`KeyboardInterrupt`. The Uvicorn
    # signal handler installed by ``uvicorn.run`` only
    # translates ``SIGINT`` and ``SIGTERM``; ``SIGBREAK``
    # is platform-specific and would silently bypass
    # the documented graceful-shutdown path. The
    # handler below maps ``SIGBREAK`` to ``SIGINT`` so
    # the standard Uvicorn graceful shutdown runs and
    # the lifespan, the application shutdown, the
    # log flush, and the exit-code translation all
    # behave consistently with the operator pressing
    # Ctrl+C in a console.
    if sys.platform == "win32" and hasattr(signal, "SIGBREAK"):
        # ``SIGBREAK`` can only be installed by the
        # main thread on Windows. ``ValueError`` covers
        # a test worker thread; ``OSError`` covers a
        # non-main context. Either way, the graceful
        # path still works for ``SIGINT`` / ``SIGTERM``
        # which Uvicorn already handles.
        with contextlib.suppress(ValueError, OSError):
            signal.signal(signal.SIGBREAK, signal.default_int_handler)  # type: ignore[attr-defined]
    # Defer the heavy import to the function body so
    # the import-time cost of uvicorn is not paid by
    # the supervisor or the unit tests.
    import uvicorn

    config = uvicorn.Config(
        app_module,
        host=parsed.host,
        port=parsed.port,
        log_level=parsed.log_level,
        # The child does not need a reload watcher; the
        # operator restarts the server explicitly via
        # ``lockverity start`` / ``lockverity stop``.
        reload=False,
    )
    server = uvicorn.Server(config)
    if sys.platform == "win32" and instance_id:
        with _WindowsShutdownEvent(instance_id, server):
            server.run()
    else:
        server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
