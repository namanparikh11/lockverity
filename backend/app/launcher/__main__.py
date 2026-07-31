"""Entry point for ``python -m app.launcher``.

The module is the ``-m`` form of the launcher; the
frozen ``Lockverity.exe`` entry point is the same
``main`` function from :mod:`app.launcher`.
"""

from __future__ import annotations

import sys

from app.launcher import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
