"""``lockverity open`` subcommand.

Opens the local URL in the default browser. The command
verifies the instance is healthy and refuses to open an
untrusted URL (only loopback host/port is accepted).
"""

from __future__ import annotations

import argparse
import json
import sys

from app.cli import runner
from app.cli.home import resolve_home
from app.cli.process import (
    IdentityCheck,
    IdentityMatch,
    ProcessGone,
    verify_identity,
)
from app.cli.state import read_state

EXIT_OK = 0
EXIT_STOPPED = 1
EXIT_UNHEALTHY = 2
EXIT_USAGE = 64


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``open`` argparse arguments."""
    parser.add_argument(
        "--print-url",
        action="store_true",
        help="Print the URL on stdout instead of opening the browser.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit the result as a single JSON object on stdout.",
    )


def main(args: argparse.Namespace) -> int:
    """Run the ``open`` subcommand."""
    home = resolve_home(cli_override=getattr(args, "home", None))
    state = read_state(home)
    if state is None:
        if args.json_output:
            print(
                json.dumps(
                    {"outcome": "no_instance", "url": None},
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(
                "ERROR: no instance recorded under this runtime home.",
                file=sys.stderr,
            )
        return EXIT_STOPPED
    identity = verify_identity(
        recorded_pid=state.pid,
        recorded_created_at=state.created_at,
        recorded_instance_id=state.instance_id,
        recorded_module=state.module,
    )
    if not isinstance(identity, IdentityMatch):
        if args.json_output:
            print(
                json.dumps(
                    {
                        "outcome": "unhealthy",
                        "url": f"http://{state.host}:{state.port}/",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(
                f"ERROR: recorded instance is not healthy ({_identity_reason(identity)}).",
                file=sys.stderr,
            )
        return EXIT_UNHEALTHY
    if not runner.is_loopback_host(state.host):
        if args.json_output:
            print(
                json.dumps(
                    {
                        "outcome": "refused",
                        "url": f"http://{state.host}:{state.port}/",
                        "reason": "non-loopback host",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(
                f"ERROR: refusing to open non-loopback URL http://{state.host}:{state.port}/.",
                file=sys.stderr,
            )
        return EXIT_USAGE
    url = f"http://{state.host}:{state.port}/"
    if args.print_url:
        if args.json_output:
            print(
                json.dumps(
                    {"outcome": "printed", "url": url},
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(url)
        return EXIT_OK
    opened = runner.open_browser(state.host, state.port)
    if args.json_output:
        print(
            json.dumps(
                {"outcome": "opened" if opened else "failed", "url": url},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        if opened:
            print(f"OK: opened {url} in the default browser.")
        else:
            print(
                f"ERROR: could not open {url} in the default browser.",
                file=sys.stderr,
            )
            return EXIT_UNHEALTHY
    return EXIT_OK


def _identity_reason(identity: IdentityCheck) -> str:
    """Return a short reason string for an unhealthy identity."""
    if isinstance(identity, ProcessGone):
        return "process is gone"
    if hasattr(identity, "reason"):
        return identity.reason or "identity does not match"
    return "identity does not match"


__all__ = [
    "EXIT_OK",
    "EXIT_STOPPED",
    "EXIT_UNHEALTHY",
    "EXIT_USAGE",
    "add_arguments",
    "main",
]
