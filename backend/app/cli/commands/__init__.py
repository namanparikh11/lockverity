"""Public subcommands for the ``lockverity`` CLI.

This package is the operator-facing command layer. Each
module corresponds to one ``lockverity <subcommand>``:

  - :mod:`app.cli.commands.start`
  - :mod:`app.cli.commands.stop`
  - :mod:`app.cli.commands.status`
  - :mod:`app.cli.commands.open_cmd` (named ``open_cmd``
    because Python's built-in :func:`open` would shadow
    the module reference)
  - :mod:`app.cli.commands.doctor`
  - :mod:`app.cli.commands.logs`

Each subcommand exposes a :func:`add_arguments` and
a :func:`main` function. The :func:`add_arguments`
function registers the argparse arguments; the
:func:`main` function performs the work. The argparse
parent is :func:`app.cli.main.build_parser`.
"""

from __future__ import annotations

__all__: list[str] = []
