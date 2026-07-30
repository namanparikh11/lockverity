"""Runtime-home resolution for the ``lockverity`` CLI.

The runtime home is the operator-controlled root directory
where the CLI persists:

  * ``data/``     - the SQLite database and the upload
    workspace.
  * ``logs/``     - the bounded rotating log files.
  * ``run/``      - the state file and any transient
    runtime markers.
  * ``config/``   - reserved for future operator-provided
    configuration (Part B2 does not write to ``config/``).

The location is operator-overridable in two ways:

  1. The environment variable ``LOCKVERITY_HOME`` takes
     precedence over every default.
  2. The CLI global option ``--home <path>`` takes
     precedence over the environment variable.

Defaults follow the platform conventions of other
operator-controlled local tools:

  * Windows: ``%LOCALAPPDATA%\\Lockverity``
    (falls back to ``%USERPROFILE%\\AppData\\Local\\Lockverity``
    when ``LOCALAPPDATA`` is unset, which matches the
    behaviour of the underlying Win32 ``SHGetKnownFolderPath``
    API).
  * macOS:   ``~/Library/Application Support/Lockverity``.
  * Linux / other POSIX: ``${XDG_DATA_HOME:-~/.local/share}/lockverity``
    (the XDG Base Directory specification default).

The resolver is read-only on disk; the directory is
created by the caller with safe permissions via
:func:`ensure_home`. The path is normalised with
``Path.resolve`` so a symlinked ``LOCKVERITY_HOME`` is
detected and rejected if it points outside the operator's
home directory (see :func:`is_safe_home`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HOME_ENV_VAR = "LOCKVERITY_HOME"
HOME_DIR_NAME = "Lockverity"
HOME_DIR_NAME_POSIX = "lockverity"

# Sub-directory layout. The names are part of the CLI
# contract: do not rename them silently, the runner and
# the doctor read them back.
DATA_DIR = "data"
LOGS_DIR = "logs"
RUN_DIR = "run"
CONFIG_DIR = "config"

ALL_SUBDIRS: tuple[str, ...] = (DATA_DIR, LOGS_DIR, RUN_DIR, CONFIG_DIR)


def default_home() -> Path:
    """Return the OS-appropriate default runtime home.

    The function is intentionally dependency-free: the only
    inputs are the standard-library ``os`` and ``sys``
    modules and the operator's environment. The function
    does not touch the filesystem; the caller is
    responsible for creating the directory.
    """
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / HOME_DIR_NAME
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            return Path(user_profile) / "AppData" / "Local" / HOME_DIR_NAME
        # Last-resort fallback. ``Path.home()`` resolves via
        # the Windows ``USERPROFILE`` environment variable
        # or the ``~`` alias in the shell. If both are
        # unset the path resolves to the process working
        # directory, which is documented behaviour for the
        # stdlib fallback.
        return Path.home() / "AppData" / "Local" / HOME_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / HOME_DIR_NAME
    # Linux and other POSIX (BSD, etc.).
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / HOME_DIR_NAME_POSIX
    return Path.home() / ".local" / "share" / HOME_DIR_NAME_POSIX


def resolve_home(
    *,
    cli_override: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    """Return the resolved runtime home, in priority order.

    Precedence (highest first):

      1. ``cli_override`` (the ``--home`` CLI option).
      2. ``LOCKVERITY_HOME`` environment variable.
      3. :func:`default_home` (OS-appropriate default).

    The function returns an absolute, symlink-resolved
    path. The caller is responsible for verifying the
    path is safe (see :func:`is_safe_home`) and for
    creating the directory (see :func:`ensure_home`).
    """
    environment = env if env is not None else os.environ
    if cli_override is not None:
        candidate = Path(str(cli_override)).expanduser()
    elif HOME_ENV_VAR in environment and environment[HOME_ENV_VAR].strip():
        candidate = Path(environment[HOME_ENV_VAR].strip()).expanduser()
    else:
        candidate = default_home()
    # ``Path.resolve`` resolves the path to an absolute
    # form, following symlinks. The strict check is
    # unnecessary here because the home may not exist
    # yet at first run; the caller is responsible for
    # the existence check.
    return candidate.resolve(strict=False)


def is_safe_home(home: Path, *, operator_home: Path | None = None) -> bool:
    """Return ``True`` iff ``home`` is a safe runtime home.

    A safe runtime home is an absolute, non-empty path
    that resolves to a directory the operator can write
    to. The function does not test writability; the
    caller is expected to use :func:`ensure_home` for
    that. The function exists to reject obvious
    injection attempts (``..`` segments, symlinks
    pointing outside the operator's home directory)
    before the runtime creates any state files.
    """
    if not str(home).strip():
        return False
    try:
        text = str(home)
    except Exception:
        return False
    if "\0" in text:
        return False
    if ".." in Path(text).parts:
        return False
    # Reject symlinks that point outside the operator's
    # home directory. A symlink to ``/etc`` or
    # ``/var`` is suspicious; a symlink to
    # ``/Users/alice/Library`` is not.
    try:
        resolved = home.resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    if operator_home is not None:
        try:
            operator_resolved = operator_home.resolve(strict=False)
        except (OSError, RuntimeError):
            return True
        try:
            resolved.relative_to(operator_resolved)
        except ValueError:
            return False
    return True


def ensure_home(home: Path) -> Path:
    """Create the runtime home and every documented sub-directory.

    The function is idempotent: existing directories are
    left untouched. The directories are created with the
    platform default permissions; on POSIX the default
    umask applies, so a freshly-created ``data/`` is
    ``0755`` masked down to ``0755`` for the typical
    umask ``0022``. The function returns the resolved
    home so the caller does not need to re-resolve the
    path. Raises :class:`OSError` on filesystem failure.
    """
    resolved = home.resolve(strict=False)
    for sub in (DATA_DIR, LOGS_DIR, RUN_DIR, CONFIG_DIR):
        (resolved / sub).mkdir(parents=True, exist_ok=True)
    return resolved


def data_dir(home: Path) -> Path:
    """Return the data directory under ``home``."""
    return home / DATA_DIR


def logs_dir(home: Path) -> Path:
    """Return the logs directory under ``home``."""
    return home / LOGS_DIR


def run_dir(home: Path) -> Path:
    """Return the run directory under ``home``."""
    return home / RUN_DIR


def config_dir(home: Path) -> Path:
    """Return the config directory under ``home``."""
    return home / CONFIG_DIR
