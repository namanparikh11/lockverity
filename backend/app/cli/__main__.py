"""``python -m app.cli`` entry point.

This module is the Python-module-form entry point for
the CLI. It mirrors the ``lockverity`` console script
installed by ``pyproject.toml [project.scripts]`` and
exists so source-based usage works without an editable
install::

    cd backend
    .venv\\Scripts\\python.exe -m app.cli start
"""

from __future__ import annotations

import sys

from app.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
