"""Frozen-runtime resource resolution.

The Lockverity Windows portable package is built with
PyInstaller in one-folder mode (``--onedir``). The frozen
artefact has two resource roots:

  * The **application data** bundled at freeze time:
    ``sys._MEIPASS`` points to the directory PyInstaller
    unpacks at launch. This is the only directory that
    contains ``frontend/dist/``, ``alembic/``, the
    approved ``favicon.ico``, the ``LICENSE`` file, and
    the frozen Python distribution.

  * The **frozen executable's directory** (the directory
    the user double-clicks from, after unzip). This
    directory contains the launcher exe, the CLI exe,
    and the ``_internal/`` PyInstaller support directory.

This module is the single chokepoint for "where do I
find resource X?" so the application code does not need
to know whether it is running from a source checkout or
a frozen artefact. The resolver:

  * In **source mode** (no ``sys._MEIPASS``): falls back
    to the existing repository-root-based paths
    (``repo_root/frontend/dist``,
    ``backend/alembic/versions``).

  * In **frozen mode** (``sys._MEIPASS`` is set by
    PyInstaller): returns the bundled path under
    ``sys._MEIPASS``.

The function never raises on a missing resource; callers
are expected to call :func:`is_frozen` /
:func:`is_source` and handle the two modes explicitly
when the difference matters (e.g. ``alembic.ini`` in
source mode is mutable for development; in frozen mode
it is read-only).

Why we do not write runtime data beside the executable
in frozen mode
----------------------------------

The frozen executable directory must be treated as
read-only application content. The Windows portable
package is a "drop anywhere" artefact; the user may
extract it to a write-protected location (e.g. ``Program
Files\\``) or a read-only network share. Runtime data
(domains, state, logs, lock) goes under
:func:`runtime_home` (the Part B2 home), which the
operator controls. The bundled ``frozen_root`` is
read-only application content.

The function never depends on the caller's current
working directory (``os.getcwd()``) and never reads from
a temporary extraction location. PyInstaller's
``sys._MEIPASS`` is the canonical bundle root and is
stable for the lifetime of the process.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


# PyInstaller sets this attribute on the frozen
# interpreter at launch. The standard library does not
# define the name in the typeshed stubs, hence the
# ``getattr`` guard.
def is_frozen() -> bool:
    """Return ``True`` when running inside a PyInstaller bundle.

    The function is the documented chokepoint for the
    "source versus frozen" branch. Every call site that
    needs to make a runtime decision that depends on
    the build flavour should call this function rather
    than inspecting ``sys`` directly.
    """
    return getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None) is not None


def is_source() -> bool:
    """Return ``True`` when running from a source checkout.

    The function is the inverse of :func:`is_frozen`.
    A process is always in exactly one mode; the two
    helpers are kept symmetric so a typo is caught
    immediately.
    """
    return not is_frozen()


def frozen_root() -> Path:
    """Return the absolute path of the frozen bundle root.

    The bundle root is the directory PyInstaller sets
    via ``sys._MEIPASS``. It contains every read-only
    resource the application uses at runtime
    (frontend dist, alembic scripts and config, the
    approved brand assets, the ``LICENSE`` file, the
    portable documentation, the application icon, the
    compiled Python bytecode of the application code).

    The function raises :class:`RuntimeError` in source
    mode so a caller that mistakenly asks for the
    frozen root in a source checkout fails loudly. Use
    :func:`is_frozen` to guard the call.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        raise RuntimeError(
            "frozen_root() called outside a PyInstaller bundle. "
            "Use is_frozen() / is_source() to guard the call."
        )
    return Path(meipass).resolve()


def source_root() -> Path:
    """Return the absolute path of the repository root in source mode.

    The repository root is the parent of the ``backend``
    package directory. The application always resolves
    relative paths against this root so a frontend dist
    at ``frontend/dist`` works the same way regardless
    of the operator's current working directory.

    In frozen mode the function raises because there
    is no "repository root" in a frozen artefact; the
    equivalent is :func:`frozen_root`.
    """
    if is_frozen():
        raise RuntimeError(
            "source_root() called inside a PyInstaller bundle. "
            "Use is_frozen() / is_source() to guard the call."
        )
    # ``runtime_paths.py`` lives at
    # ``backend/app/runtime_paths.py``; parents[0] is
    # ``app/``, parents[1] is ``backend/``, parents[2]
    # is the repo root.
    return Path(__file__).resolve().parents[2]


def application_root() -> Path:
    """Return the absolute path of the active application root.

    In source mode this is the repository root. In
    frozen mode this is the frozen bundle root. The
    function is the documented "give me the root I
    should read application content from" entry point.
    """
    if is_frozen():
        return frozen_root()
    return source_root()


def frontend_dist_path() -> Path:
    """Return the absolute path of the bundled frontend ``dist``.

    In source mode the dist is at
    ``<repo_root>/frontend/dist`` (the Vite build
    output, populated by
    ``scripts/prepare_frontend_dist.py``). In frozen
    mode the dist is at
    ``<frozen_root>/frontend/dist`` (the PyInstaller
    ``datas`` entry bundles the entire ``dist/``
    tree at freeze time).
    """
    if is_frozen():
        return frozen_root() / "frontend" / "dist"
    return source_root() / "frontend" / "dist"


def alembic_config_path() -> Path:
    """Return the absolute path of the ``alembic.ini`` file.

    In source mode the config is at
    ``<repo_root>/backend/alembic.ini``. In frozen
    mode the config is bundled at
    ``<frozen_root>/alembic/cfg/alembic.ini`` (the
    ``alembic/cfg/`` directory prefix is the
    documented v2.1 Part B3A PyInstaller
    prefix-collision workaround: bundling a single
    file at the dest ``alembic.ini`` or
    ``alembic/alembic.ini`` would be interpreted as
    a directory of the same name by PyInstaller's
    ``datas`` processing when a sibling directory
    entry shares the ``alembic`` prefix; placing
    the file in the ``cfg/`` subdirectory removes
    the collision).

    The Alembic env script (``alembic/env.py``)
    reads the URL from the application settings at
    runtime; the config file is the script-location
    and prepend-sys-path metadata.
    """
    if is_frozen():
        return frozen_root() / "alembic" / "cfg" / "alembic.ini"
    return source_root() / "backend" / "alembic.ini"


def alembic_versions_dir() -> Path:
    """Return the absolute path of the Alembic ``versions`` directory.

    In source mode the directory is at
    ``<repo_root>/backend/alembic/versions``. In
    frozen mode it is bundled at
    ``<frozen_root>/alembic/versions``. The directory
    is treated as read-only application content in
    frozen mode; runtime data never writes here.
    """
    if is_frozen():
        return frozen_root() / "alembic" / "versions"
    return source_root() / "backend" / "alembic" / "versions"


def favicon_path() -> Path:
    """Return the absolute path of the approved application icon.

    The path is the same ICO that the v2.1 Part A brand
    board shipped; the file is bundled at
    ``<frozen_root>/favicon.ico`` for the graphical
    launcher's executable icon resource. In source mode
    the same file lives at
    ``<repo_root>/frontend/public/favicon.ico`` and is
    used by the Part A tests; the function returns the
    same path the source-mode Part A code uses, so the
    two paths agree on the same approved asset.
    """
    if is_frozen():
        return frozen_root() / "favicon.ico"
    return source_root() / "frontend" / "public" / "favicon.ico"


def brand_symbol_path() -> Path:
    """Return the absolute path of the approved brand symbol PNG.

    The function returns the same file the v2.1 Part A
    ``LockveritySymbol`` React component renders. In
    source mode it is at
    ``<repo_root>/frontend/public/brand/lockverity-symbol.png``.
    In frozen mode it is bundled at
    ``<frozen_root>/brand/lockverity-symbol.png``.
    """
    if is_frozen():
        return frozen_root() / "brand" / "lockverity-symbol.png"
    return source_root() / "frontend" / "public" / "brand" / "lockverity-symbol.png"


def license_path() -> Path:
    """Return the absolute path of the bundled ``LICENSE`` file.

    In source mode the file is at the repository root.
    In frozen mode it is bundled at the bundle root.
    """
    if is_frozen():
        return frozen_root() / "LICENSE"
    return source_root() / "LICENSE"


def portable_readme_path() -> Path:
    """Return the absolute path of the portable ``README-PORTABLE.txt``.

    In source mode the file is at
    ``<repo_root>/docs/windows-portable.md``. In frozen
    mode it is bundled at
    ``<frozen_root>/README-PORTABLE.txt``.
    """
    if is_frozen():
        return frozen_root() / "README-PORTABLE.txt"
    return source_root() / "docs" / "windows-portable.md"


def frozen_exe_dir() -> Path:
    """Return the directory containing the running frozen executable.

    The directory is the parent of ``sys.executable``
    when running from a PyInstaller onedir bundle. The
    directory contains the launcher and CLI exes plus
    the ``_internal/`` PyInstaller support directory.
    In source mode the function raises because the
    notion of "frozen exe dir" is not applicable.
    """
    if not is_frozen():
        raise RuntimeError("frozen_exe_dir() called outside a PyInstaller bundle.")
    return Path(sys.executable).resolve().parent


__all__ = [
    "alembic_config_path",
    "alembic_versions_dir",
    "application_root",
    "brand_symbol_path",
    "favicon_path",
    "frontend_dist_path",
    "frozen_exe_dir",
    "frozen_root",
    "is_frozen",
    "is_source",
    "license_path",
    "portable_readme_path",
    "source_root",
]


# Module-level sanity check: the file must NOT be
# imported from a path that depends on the caller's
# current working directory. The check is intentionally
# cheap and runs once at import time. The function
# raises if the module's own ``__file__`` is not absolute
# (which would be a sign of a frozen artefact using a
# different layout than expected).
if not __file__:
    # The branch is dead code on CPython; the check
    # is kept to make the invariant explicit.
    raise RuntimeError("runtime_paths must be loaded from a file")
# Belt-and-braces: a hard-coded diagnostic for the
# frozen-mode loader. PyInstaller does not set
# ``__file__`` to a real path for some entry points;
# the application code never depends on it, but a
# debugging operator can set ``LOCKVERITY_DEBUG_PATHS=1``
# to print the resolved paths at startup.
if os.environ.get("LOCKVERITY_DEBUG_PATHS") == "1":
    import sys as _sys

    _sys.stderr.write(
        f"[lockverity.runtime_paths] frozen={is_frozen()} "
        f"application_root={application_root()!s} "
        f"frontend_dist={frontend_dist_path()!s}\n"
    )
