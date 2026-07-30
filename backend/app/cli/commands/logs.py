"""``lockverity logs`` subcommand.

Reads the rotating runtime log file. ``--lines`` (or
``-n``) bounds the number of lines returned; ``--follow``
(or ``-f``) tails the file. The command never reads an
arbitrary user-supplied path; the log path is the
documented rotating file under the runtime home.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import signal
import sys

from app.cli import runner
from app.cli.home import logs_dir, resolve_home

DEFAULT_TAIL_LINES = 100
MAX_TAIL_LINES = 10_000


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``logs`` argparse arguments."""
    parser.add_argument(
        "--lines",
        "-n",
        type=int,
        default=DEFAULT_TAIL_LINES,
        help=(
            f"Number of trailing lines to display (default: "
            f"{DEFAULT_TAIL_LINES}, max: {MAX_TAIL_LINES})."
        ),
    )
    parser.add_argument(
        "--follow",
        "-f",
        action="store_true",
        help="Follow the log file (like tail -f).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=("Emit the bounded log tail as a JSON object on stdout (ignored in --follow mode)."),
    )


def main(args: argparse.Namespace) -> int:
    """Run the ``logs`` subcommand."""
    home = resolve_home(cli_override=getattr(args, "home", None))
    log_path = logs_dir(home) / "lockverity.log"
    if args.lines < 0 or args.lines > MAX_TAIL_LINES:
        print(
            f"ERROR: --lines must be between 0 and {MAX_TAIL_LINES}.",
            file=sys.stderr,
        )
        return 64
    if not log_path.is_file():
        if args.json_output:
            print(
                json.dumps(
                    {
                        "outcome": "missing",
                        "log_file": str(log_path),
                        "lines": [],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        print(f"ERROR: log file does not exist: {log_path}", file=sys.stderr)
        return 1
    if args.follow:
        # ``KeyboardInterrupt`` exits the follow loop
        # cleanly; ``signal.SIGINT`` is the documented
        # way to install a handler in the test suite.
        def _handle_sigint(_signum, _frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, _handle_sigint)
        with contextlib.suppress(KeyboardInterrupt):
            runner.follow_log(log_path, lines=args.lines)
        return 0
    tail = runner.read_log_tail(log_path, lines=args.lines)
    if args.json_output:
        print(
            json.dumps(
                {
                    "outcome": "ok",
                    "log_file": str(log_path),
                    "lines": tail,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    for line in tail:
        print(line)
    return 0


__all__ = ["add_arguments", "main"]
