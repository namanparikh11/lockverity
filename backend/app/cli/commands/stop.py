"""``lockverity stop`` subcommand.

Stops the running instance gracefully. The command
verifies the recorded process identity (PID + creation
time + instance UUID + module) against the live process
before sending any signal. The cross-platform identity
check is implemented by :mod:`app.cli.process` via
:mod:`psutil`; a PID that has been recycled for an
unrelated process never matches and is never terminated.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.cli import runner
from app.cli.home import resolve_home


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``stop`` argparse arguments."""
    parser.add_argument(
        "--timeout",
        type=float,
        default=runner.DEFAULT_STOP_TIMEOUT,
        help=(
            "Maximum seconds to wait for graceful termination before "
            "reporting an error (default: 15). With --force, the "
            "runner escalates to a hard kill after this grace period."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Force-terminate the recorded process after the grace "
            "period if it has not exited. Only effective after "
            "identity verification; the runner never force-kills an "
            "unrelated process."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit the result as a single JSON object on stdout.",
    )


def main(args: argparse.Namespace) -> int:
    """Run the ``stop`` subcommand.

    Returns the process exit code:

      - 0 -- the instance was stopped (or was not
        running);
      - 1 -- an error occurred (identity mismatch,
        inaccessible process, or grace period
        exceeded without ``--force``).
    """
    home = resolve_home(cli_override=getattr(args, "home", None))
    try:
        result = runner.stop(home=home, timeout=args.timeout, force=args.force)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json_output:
        payload = {
            "outcome": result.outcome,
            "elapsed_seconds": result.elapsed_seconds,
            "details": result.details,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        if result.outcome in ("stopped", "force_killed", "was_not_running"):
            return 0
        return 1
    if result.outcome == "stopped":
        print(f"OK: stopped ({result.details}).")
        return 0
    if result.outcome == "force_killed":
        print(f"OK: force-killed ({result.details}).")
        return 0
    if result.outcome == "was_not_running":
        print(f"OK: no instance was running ({result.details}).")
        return 0
    # error
    print(f"ERROR: {result.details}", file=sys.stderr)
    return 1


__all__ = ["add_arguments", "main"]
