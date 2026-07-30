"""``lockverity`` CLI argparse entry point.

The module wires the six subcommands and the global
``--home`` option. The same function is exposed as
``python -m app.cli`` (see :mod:`app.cli.__main__`) and as
the ``lockverity`` console script (see
``pyproject.toml [project.scripts]``).

The CLI never shells out (``shell=True`` is forbidden);
every subprocess is constructed with an explicit
argument list. The CLI never modifies the source
repository; the only on-disk state it writes is under
the resolved runtime home.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app.cli import commands
from app.cli.commands import doctor, logs, open_cmd, start, status, stop

# Subcommand registry. The order here is the order
# shown in ``lockverity --help``. Each entry is a
# callable that takes the subparser and registers the
# command's arguments.
_SUBCOMMANDS = (
    ("start", "Start the Lockverity single-port runtime", start),
    ("stop", "Stop the running Lockverity instance", stop),
    ("status", "Show the current instance status", status),
    ("open", "Open the local Lockverity URL in the default browser", open_cmd),
    ("doctor", "Run a read-only diagnostic checklist", doctor),
    ("logs", "Show the runtime log (with --follow)", logs),
)

# Exit codes used by ``main``. The values are the
# conventional Unix exit codes: 0 success, 1 generic
# error, 2 misuse of shell command, 64 command-line
# usage error.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 64


def build_parser() -> argparse.ArgumentParser:
    """Return the root argparse parser.

    The function is the single chokepoint for the CLI
    grammar; the test suite exercises it directly to
    assert the documented options and the help text.
    """
    parser = argparse.ArgumentParser(
        prog="lockverity",
        description=(
            "lockverity -- cross-platform local runtime CLI for the "
            "Lockverity single-port production runtime. See "
            "docs/release-checklist.md for the full operator guide."
        ),
        epilog=(
            "The CLI never modifies the source repository. The only "
            "on-disk state is the runtime home (LOCKVERITY_HOME or "
            "--home, defaulting to the OS-appropriate data directory)."
        ),
    )
    parser.add_argument(
        "--home",
        default=None,
        help=(
            "Override the runtime home path. Takes precedence over the "
            "LOCKVERITY_HOME environment variable. Default: the OS-"
            "appropriate data directory (Windows: %%LOCALAPPDATA%%\\Lockverity; "
            "macOS: ~/Library/Application Support/Lockverity; Linux: "
            "${XDG_DATA_HOME:-~/.local/share}/lockverity)."
        ),
    )
    subparsers = parser.add_subparsers(dest="subcommand", metavar="<command>")
    for name, help_text, module in _SUBCOMMANDS:
        subparser = subparsers.add_parser(
            name,
            help=help_text,
            description=help_text,
        )
        module.add_arguments(subparser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    The function is the console-script entry point
    (``lockverity``) and the ``python -m app.cli`` entry
    point. The function returns the documented exit
    code; it never calls :func:`sys.exit` so the test
    suite can call it directly.
    """
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.subcommand is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    for name, _help_text, module in _SUBCOMMANDS:
        if name == args.subcommand:
            return module.main(args)
    # ``argparse`` guarantees ``args.subcommand`` is one
    # of the registered names when it is not ``None``;
    # the loop above always returns first.
    parser.print_help(sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXIT_ERROR",
    "EXIT_OK",
    "EXIT_USAGE",
    "build_parser",
    "main",
]

# Reference the commands package so a test that
# monkey-patches a submodule through ``app.cli.commands``
# works as expected.
_ = commands
