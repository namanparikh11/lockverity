"""Cross-process GUI shutdown signal.

The desktop ``Lockverity.exe`` instance owns its FastAPI backend as a
child process and owns the documented ``run/lockverity.state.json``
state file. ``lockverity-cli stop`` is the canonical way to terminate
an instance from a second terminal.

For a CLI-only instance the documented contract is to terminate the
recorded ``state.pid`` (which is the CLI's own PID). For a GUI instance
the recorded ``state.pid`` is the CLI subprocess PID, and the GUI
process is the parent of that subprocess. Terminating only the
subprocess would leave the GUI process alive holding the pre-bound
socket and the runtime state.

This module provides the cross-process signal the CLI ``stop`` command
uses to ask the running GUI instance to self-terminate. On Windows the
signal is a global named event the GUI's main thread polls alongside
the message loop. On non-Windows hosts the helper is a no-op and the
CLI ``stop`` falls back to the recorded-PID-terminate path.
"""

from __future__ import annotations

import sys
from typing import Final

STOP_EVENT_NAME: Final[str] = r"Global\{E5B0C0F4-7C42-4D6A-9B17-1A2B3C4D5E70}"


def signal_gui_stop() -> bool:
    """Signal the running desktop instance to self-terminate.

    The function sets the global ``STOP_EVENT_NAME`` event so the
    GUI's poll thread tears down the WebView and exits cleanly. It
    returns ``True`` if the event was set, ``False`` if the platform
    does not support the documented event (POSIX) or the GUI is
    not running. ``lockverity-cli stop`` should still terminate the
    backend child after this returns, so a non-Windows host (or a
    missing event) still ends the instance via the recorded
    ``state.pid``-terminate path.
    """
    if sys.platform != "win32":
        return False
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.OpenEventW.restype = ctypes.c_void_p
    kernel32.SetEvent.argtypes = [ctypes.c_void_p]
    handle = kernel32.OpenEventW(0x0002, False, STOP_EVENT_NAME)  # EVENT_MODIFY_STATE
    if not handle:
        return False
    try:
        kernel32.SetEvent(handle)
    finally:
        kernel32.CloseHandle(handle)
    return True


__all__ = ["STOP_EVENT_NAME", "signal_gui_stop"]
