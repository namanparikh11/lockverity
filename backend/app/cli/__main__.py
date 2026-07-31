"""``python -m app.cli`` entry point.

This module is the Python-module-form entry point for
the CLI. It mirrors the ``lockverity`` console script
installed by ``pyproject.toml [project.scripts]`` and
exists so source-based usage works without an editable
install::

    cd backend
    .venv\\Scripts\\python.exe -m app.cli start

The module configures the standard streams to use
UTF-8 encoding on Windows so the operator-facing
status output can render Unicode paths (e.g. an
extraction directory containing ``Ω``). The
``PYTHONIOENCODING`` env var is the documented
environment-level override; the runtime reconfigure
is the documented v2.1 Part B3A frozen-mode
fallback so an operator who double-clicks the
executable without setting the env var still sees
the full Unicode output instead of a
:class:`UnicodeEncodeError` from ``cp1252``.
"""

from __future__ import annotations

import contextlib
import sys

from app.cli.main import main

if __name__ == "__main__":
    # Configure UTF-8 stdout/stderr on Windows.
    # The configuration is wrapped so a non-Windows
    # host (where ``reconfigure`` is unavailable or
    # unnecessary) does not fail. The default
    # encoding is otherwise used; the operator can
    # set ``PYTHONIOENCODING=utf-8`` to force the
    # documented behaviour from the shell.
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # The stream may be closed, replaced by a
        # non-standard object, or the runtime may
        # not support reconfigure; the default
        # encoding applies in that case.
        with contextlib.suppress(AttributeError, ValueError):
            reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
