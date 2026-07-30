"""Lockverity local runtime CLI (v2.1 Part B2).

This package is the cross-platform command layer for the
single-port production runtime introduced in v2.1 Part B1.

The package provides:

  - :mod:`app.cli.home` -- the operator-overridable runtime
    home (``LOCKVERITY_HOME`` / ``--home``).
  - :mod:`app.cli.state` -- the atomic, JSON-encoded
    instance state file (PID + process identity fingerprint).
  - :mod:`app.cli.process` -- cross-platform process
    identity verification that defends against PID reuse.
  - :mod:`app.cli.logging_setup` -- bounded rotating runtime
    log file.
  - :mod:`app.cli.runner` -- the :func:`start` and
    :func:`stop` runtime helpers (Alembic migration,
    detached Uvicorn, graceful shutdown).
  - :mod:`app.cli.commands` -- the six public subcommands
    (``start``, ``stop``, ``status``, ``open``, ``doctor``,
    ``logs``).
  - :mod:`app.cli.main` -- the argparse entry point exposed
    as ``lockverity`` and as ``python -m app.cli``.

The CLI never shells out with ``shell=True``; every
subprocess is constructed with an explicit argument list.
The CLI never stores secrets in the state file. The CLI
refuses to terminate a process whose identity fingerprint
does not match the recorded instance; PID reuse on the
host cannot lead to the wrong process being killed.

The public surface is the six subcommands documented in
``docs/release-checklist.md``. The implementation modules
are considered internal and may change without notice; the
:mod:`app.cli.commands` and :mod:`app.cli.main` modules are
the only ones a downstream integrator should import.
"""

from __future__ import annotations

__all__: list[str] = []
