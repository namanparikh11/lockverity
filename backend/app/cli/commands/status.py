"""``lockverity status`` subcommand.

Reports the current instance state. The human output
is a small table; ``--json`` emits a documented stable
schema suitable for future launchers.

JSON schema
===========

The ``status --json`` output is a single object with the
following documented stable top-level keys:

  - ``status`` -- ``"running"`` / ``"stopped"`` /
    ``"stale"`` / ``"unhealthy"``;
  - ``instance_id`` -- the recorded instance UUID, or
    ``null`` when the instance is stopped;
  - ``pid`` -- the recorded PID, or ``null``;
  - ``host`` -- the recorded host, or ``null``;
  - ``port`` -- the recorded port, or ``null``;
  - ``url`` -- ``"http://{host}:{port}/"`` or ``null``;
  - ``version`` -- the recorded product version, or
    ``null``;
  - ``home`` -- the absolute runtime-home path, or
    ``null``;
  - ``frontend_dist`` -- the absolute dist path, or
    ``null``;
  - ``log_file`` -- the absolute log path, or
    ``null``;
  - ``started_at`` -- ISO 8601 UTC string, or ``null``;
  - ``uptime`` -- human-readable uptime, or ``null``;
  - ``health`` -- ``{reachable, body}`` or
    ``{reachable: false}``;
  - ``state_file`` -- the absolute state-file path.

The schema is the single source of truth for launcher
scripts; new keys may be added in a backward-compatible
way, removed keys are not.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.cli import runner
from app.cli.home import resolve_home
from app.cli.process import (
    IdentityCheck,
    IdentityMatch,
    IdentityMismatch,
    ProcessGone,
    ProcessInaccessible,
    verify_identity,
)
from app.cli.state import read_state, state_file_path

EXIT_RUNNING = 0
EXIT_STOPPED = 1
EXIT_UNHEALTHY = 2
EXIT_USAGE = 64


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``status`` argparse arguments."""
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit the result as a single JSON object on stdout.",
    )


def _build_payload(state, identity, health, *, home: Path) -> dict[str, object]:
    """Return the JSON-serialisable status payload.

    The ``home`` argument is the resolved runtime
    home the command was invoked with; the
    ``state_file`` key is the on-disk path of the
    state file under that home so the operator can
    verify the home they passed matches the home the
    process is using.
    """
    status_value = _status_to_string(identity)
    payload: dict[str, object] = {
        "status": status_value,
        "instance_id": state.instance_id if state is not None else None,
        "pid": state.pid if state is not None else None,
        "host": state.host if state is not None else None,
        "port": state.port if state is not None else None,
        "url": (f"http://{state.host}:{state.port}/" if state is not None else None),
        "version": state.version if state is not None else None,
        "home": state.home if state is not None else None,
        "frontend_dist": state.frontend_dist if state is not None else None,
        "log_file": state.log_file if state is not None else None,
        "started_at": state.started_at if state is not None else None,
        "uptime": (runner.format_uptime(state.created_at) if state is not None else None),
        "health": health,
        "state_file": str(state_file_path(home)),
    }
    return payload


def _resolve_home_for_status():
    """Return the home used for ``state_file`` path rendering.

    The function is retained for backward
    compatibility with external scripts that import
    it directly; the public ``main`` function now
    passes the resolved ``home`` to
    :func:`_build_payload` so the ``--home`` CLI
    override and the ``LOCKVERITY_HOME`` env var are
    honoured in the rendered ``state_file`` path.
    """
    return resolve_home(cli_override=None)


def _status_to_string(identity: IdentityCheck | None) -> str:
    """Map a verify_identity result to the documented status string."""
    if identity is None:
        return "stopped"
    if isinstance(identity, IdentityMatch):
        return "running"
    if isinstance(identity, ProcessGone):
        return "stopped"
    if isinstance(identity, ProcessInaccessible):
        return "unhealthy"
    if isinstance(identity, IdentityMismatch):
        return "stale"
    return "unknown"


def main(args: argparse.Namespace) -> int:
    """Run the ``status`` subcommand.

    Returns the documented exit code:

      - 0 -- running and healthy
      - 1 -- stopped (no state file or process gone)
      - 2 -- unhealthy, stale, or misconfigured
      - 64 -- invalid invocation
    """
    home = resolve_home(cli_override=getattr(args, "home", None))
    state = read_state(home)
    if state is None:
        payload = _build_payload(None, None, None, home=home)
        if args.json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print("stopped: no instance recorded.")
        return EXIT_STOPPED
    identity = verify_identity(
        recorded_pid=state.pid,
        recorded_created_at=state.created_at,
        recorded_instance_id=state.instance_id,
        recorded_module=state.module,
    )
    health: dict[str, object] | None = None
    if isinstance(identity, IdentityMatch):
        health_raw = runner.fetch_health(state.host, state.port, timeout=3.0)
        if health_raw is None:
            health = {"reachable": False}
        else:
            health = {
                "reachable": True,
                "body": health_raw,
            }
    payload = _build_payload(state, identity, health, home=home)
    if args.json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _render_human(payload, identity, health)
    # Exit code mapping.
    if isinstance(identity, IdentityMatch) and health and health.get("reachable"):
        return EXIT_RUNNING
    if isinstance(identity, (ProcessGone,)):
        return EXIT_STOPPED
    return EXIT_UNHEALTHY


def _render_human(
    payload: dict[str, object],
    identity: IdentityCheck,
    health: dict[str, object] | None,
) -> None:
    """Render the human-readable status table."""
    print(f"status        : {payload['status']}")
    if payload.get("pid") is not None:
        print(f"pid           : {payload['pid']}")
    if payload.get("host") is not None:
        host = payload["host"]
        port = payload["port"]
        print(f"url           : http://{host}:{port}/")
    if payload.get("version") is not None:
        print(f"version       : {payload['version']}")
    if payload.get("instance_id") is not None:
        print(f"instance_id   : {payload['instance_id']}")
    if payload.get("uptime") is not None:
        print(f"uptime        : {payload['uptime']}")
    if payload.get("started_at") is not None:
        print(f"created_at    : {payload['started_at']}")
    if payload.get("home") is not None:
        print(f"runtime_home  : {payload['home']}")
    if payload.get("frontend_dist") is not None:
        print(f"frontend_dist : {payload['frontend_dist']}")
    if payload.get("log_file") is not None:
        print(f"log_file      : {payload['log_file']}")
    if health is not None:
        if health.get("reachable"):
            body = health.get("body")
            if isinstance(body, dict):
                print(
                    f"health        : ok (database={body.get('database')}, "
                    f"version={body.get('version')})"
                )
            else:
                print("health        : ok")
        else:
            print("health        : unreachable")
    if isinstance(identity, IdentityMismatch):
        reason = identity.reason
        print(
            f"warning       : recorded identity does not match live process ({reason})",
            file=sys.stderr,
        )
    if isinstance(identity, ProcessInaccessible):
        print(
            f"warning       : process identity not readable ({identity.reason})",
            file=sys.stderr,
        )


__all__ = [
    "EXIT_RUNNING",
    "EXIT_STOPPED",
    "EXIT_UNHEALTHY",
    "EXIT_USAGE",
    "add_arguments",
    "main",
]
