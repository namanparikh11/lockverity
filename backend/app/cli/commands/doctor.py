"""``lockverity doctor`` subcommand.

Runs a read-only diagnostic checklist and reports each
check as PASS / WARN / FAIL. The command is safe to run
on any host; it writes at most one temporary file in
the runtime home, which is removed before the command
returns.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from app import __version__
from app.cli import runner
from app.cli.home import (
    CONFIG_DIR,
    DATA_DIR,
    LOGS_DIR,
    RUN_DIR,
    is_safe_home,
    resolve_home,
)
from app.cli.process import (
    IdentityMatch,
    ProcessGone,
    verify_identity,
)
from app.cli.state import read_state
from app.core.config import get_settings
from app.static_frontend import validate_dist

# Sensitive env var names; the doctor redacts the
# value of any env var matching one of these names.
# Matching is case-insensitive. The list is a small,
# conservative set: GitHub tokens, database URLs, and
# any other clearly-secret-bearing variable.
SENSITIVE_ENV_NAMES = frozenset(
    {
        "github_token",
        "lockverity_github_token",
        "lockverity_database_url",
        "database_url",
        "auth_token",
        "api_key",
        "secret",
    }
)


def _redact_env(name: str, value: str) -> str:
    """Return a redacted representation of an env var value."""
    if not value:
        return ""
    if any(sensitive in name.lower() for sensitive in SENSITIVE_ENV_NAMES):
        if len(value) <= 4:
            return "***"
        return f"{value[:2]}***{value[-2:]}"
    return value


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``doctor`` argparse arguments."""
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit the result as a single JSON object on stdout.",
    )


def main(args: argparse.Namespace) -> int:
    """Run the ``doctor`` subcommand."""
    home = resolve_home(cli_override=getattr(args, "home", None))
    report = build_report(home)
    if args.json_output:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        _render_human(report)
    # Exit non-zero only for FAILs. WARNs are reported
    # but do not block operator workflow.
    if report.overall == "fail":
        return 2
    return 0


def build_report(home: Path) -> runner.DoctorReport:
    """Return the :class:`runner.DoctorReport` for ``home``.

    The function is the single chokepoint for the
    doctor's logic; ``main`` is the I/O layer. Tests
    exercise the report shape directly.
    """
    checks: list[runner.DoctorCheck] = []
    # --- OS / Python / Lockverity version checks ---
    checks.append(
        runner.DoctorCheck(
            name="os",
            status="pass",
            message=f"{sys.platform}",
        )
    )
    py_version = sys.version_info
    py_str = f"{py_version.major}.{py_version.minor}.{py_version.micro}"
    if (py_version.major, py_version.minor) >= (3, 12):
        checks.append(
            runner.DoctorCheck(
                name="python",
                status="pass",
                message=f"Python {py_str} (>= 3.12)",
            )
        )
    else:
        checks.append(
            runner.DoctorCheck(
                name="python",
                status="fail",
                message=f"Python {py_str} is below the required 3.12 floor",
            )
        )
    checks.append(
        runner.DoctorCheck(
            name="version",
            status="pass",
            message=f"lockverity {__version__}",
        )
    )
    # --- Runtime home checks ---
    home_str = str(home)
    safe = is_safe_home(home)
    if safe:
        checks.append(
            runner.DoctorCheck(
                name="runtime_home",
                status="pass",
                message=f"runtime home resolves to {home_str}",
            )
        )
    else:
        checks.append(
            runner.DoctorCheck(
                name="runtime_home",
                status="fail",
                message=f"runtime home {home_str!r} is not a safe path",
            )
        )
    # Directory existence / writeability.
    for sub, label in (
        (DATA_DIR, "data"),
        (LOGS_DIR, "logs"),
        (RUN_DIR, "run"),
        (CONFIG_DIR, "config"),
    ):
        path = home / sub
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
                checks.append(
                    runner.DoctorCheck(
                        name=f"runtime_home_{label}",
                        status="pass",
                        message=f"{path} created",
                    )
                )
            except OSError as exc:
                checks.append(
                    runner.DoctorCheck(
                        name=f"runtime_home_{label}",
                        status="fail",
                        message=f"cannot create {path}: {exc}",
                    )
                )
                continue
        # Write probe.
        probe = path / ".lockverity-doctor.tmp"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            checks.append(
                runner.DoctorCheck(
                    name=f"runtime_home_{label}_writable",
                    status="pass",
                    message=f"{path} is writable",
                )
            )
        except OSError as exc:
            checks.append(
                runner.DoctorCheck(
                    name=f"runtime_home_{label}_writable",
                    status="fail",
                    message=f"cannot write to {path}: {exc}",
                )
            )
    # --- Database / Alembic checks ---
    settings = get_settings()
    db_url = settings.database_url
    if db_url.startswith("sqlite"):
        db_path_str = db_url[len("sqlite:///") :]
        db_path = Path(db_path_str)
        if db_path.is_file():
            checks.append(
                runner.DoctorCheck(
                    name="database",
                    status="pass",
                    message=f"database file exists at {db_path}",
                    redacted_message=f"database file exists at {db_path}",
                )
            )
        else:
            checks.append(
                runner.DoctorCheck(
                    name="database",
                    status="warn",
                    message=(
                        f"database file does not exist at {db_path}; "
                        "the next `lockverity start` will run alembic "
                        "upgrade head to create it."
                    ),
                )
            )
    # Alembic current == migration head.
    try:
        head = _alembic_head()
        current = _alembic_current(db_url)
        if head == current:
            checks.append(
                runner.DoctorCheck(
                    name="alembic",
                    status="pass",
                    message=f"alembic is at head ({head})",
                )
            )
        elif current is None:
            checks.append(
                runner.DoctorCheck(
                    name="alembic",
                    status="warn",
                    message=(
                        "alembic version is empty; the next "
                        "`lockverity start` will run alembic upgrade head."
                    ),
                )
            )
        else:
            checks.append(
                runner.DoctorCheck(
                    name="alembic",
                    status="fail",
                    message=f"alembic is at {current}, head is {head}",
                )
            )
    except Exception as exc:
        checks.append(
            runner.DoctorCheck(
                name="alembic",
                status="warn",
                message=f"could not determine alembic state: {exc}",
            )
        )
    # Frontend dist.
    dist_path = settings.frontend_dist_path
    try:
        validate_dist(dist_path)
        checks.append(
            runner.DoctorCheck(
                name="frontend_dist",
                status="pass",
                message=f"dist validated at {dist_path}",
            )
        )
    except Exception as exc:
        checks.append(
            runner.DoctorCheck(
                name="frontend_dist",
                status="fail",
                message=(
                    f"dist is missing or invalid at {dist_path}: {exc}. "
                    "Run scripts/prepare_frontend_dist.py to build the "
                    "frontend before starting the backend in single-port "
                    "mode."
                ),
            )
        )
    # --- Port availability (probe the default port) ---
    probe = runner.probe_port(runner.DEFAULT_HOST, runner.DEFAULT_PORT, timeout=0.5)
    if not probe.in_use:
        checks.append(
            runner.DoctorCheck(
                name="port_default_free",
                status="pass",
                message=f"{runner.DEFAULT_HOST}:{runner.DEFAULT_PORT} is free",
            )
        )
    else:
        # An occupied default port is not necessarily a
        # failure -- the operator may have bound a
        # different port. The check is reported as a
        # warning.
        checks.append(
            runner.DoctorCheck(
                name="port_default_free",
                status="warn",
                message=(
                    f"{runner.DEFAULT_HOST}:{runner.DEFAULT_PORT} is in use; "
                    "either another Lockverity instance is running, or "
                    "another process is bound. Pass --port to use a "
                    "different port."
                ),
            )
        )
    # --- State file integrity ---
    state = read_state(home)
    if state is None:
        checks.append(
            runner.DoctorCheck(
                name="state_file",
                status="pass",
                message="no state file (instance is not running)",
            )
        )
    else:
        identity = verify_identity(
            recorded_pid=state.pid,
            recorded_created_at=state.created_at,
            recorded_instance_id=state.instance_id,
            recorded_module=state.module,
        )
        if isinstance(identity, IdentityMatch):
            health = runner.fetch_health(state.host, state.port, timeout=2.0)
            if health is not None:
                checks.append(
                    runner.DoctorCheck(
                        name="state_file",
                        status="pass",
                        message=(
                            f"recorded instance is running and healthy "
                            f"(pid={state.pid}, port={state.port}, "
                            f"instance_id={state.instance_id})"
                        ),
                    )
                )
            else:
                checks.append(
                    runner.DoctorCheck(
                        name="state_file",
                        status="warn",
                        message=(
                            f"recorded instance is running but "
                            f"/api/v1/health is not reachable "
                            f"(pid={state.pid}, port={state.port})"
                        ),
                    )
                )
        elif isinstance(identity, ProcessGone):
            checks.append(
                runner.DoctorCheck(
                    name="state_file",
                    status="warn",
                    message=(
                        f"state file is stale: recorded pid {state.pid} is "
                        "gone. The next `lockverity start` will clear it."
                    ),
                )
            )
        else:
            checks.append(
                runner.DoctorCheck(
                    name="state_file",
                    status="fail",
                    message=(
                        f"recorded identity does not match the live process "
                        f"({getattr(identity, 'reason', 'unknown')})"
                    ),
                )
            )
    # --- Node availability (only if dist is missing) ---
    node = shutil.which("node")
    if node is not None:
        checks.append(
            runner.DoctorCheck(
                name="node",
                status="pass",
                message="node is on PATH (only needed to rebuild the frontend)",
            )
        )
    else:
        # Only a warning, because the runtime does not
        # need node when a valid dist already exists.
        checks.append(
            runner.DoctorCheck(
                name="node",
                status="warn",
                message=(
                    "node is not on PATH; install Node.js >= 22.22.0 to rebuild the frontend dist."
                ),
            )
        )
    # --- psutil availability (process identity backend) ---
    try:
        import psutil  # noqa: F401

        checks.append(
            runner.DoctorCheck(
                name="psutil",
                status="pass",
                message="psutil is available (process identity backend)",
            )
        )
    except ImportError:
        checks.append(
            runner.DoctorCheck(
                name="psutil",
                status="fail",
                message=(
                    "psutil is not importable; the CLI cannot verify "
                    "process identity. Reinstall the backend."
                ),
            )
        )
    # --- Environment (redacted) ---
    # We list only the LOCKVERITY_* variables the CLI
    # cares about; other variables are out of scope
    # for the doctor command.
    interesting = (
        "LOCKVERITY_ENVIRONMENT",
        "LOCKVERITY_SERVE_FRONTEND",
        "LOCKVERITY_FRONTEND_DIST",
        "LOCKVERITY_DATABASE_URL",
    )
    rendered: list[str] = []
    for name in interesting:
        value = os.environ.get(name)
        if value is None:
            continue
        rendered.append(f"{name}={_redact_env(name, value)}")
    if rendered:
        checks.append(
            runner.DoctorCheck(
                name="environment",
                status="pass",
                message="; ".join(rendered),
            )
        )
    overall = _overall(checks)
    return runner.DoctorReport(
        checks=tuple(checks),
        overall=overall,
        home=home_str,
        version=__version__,
    )


def _overall(checks: list[runner.DoctorCheck]) -> str:
    """Return ``"pass"`` / ``"warn"`` / ``"fail"`` for the report."""
    for check in checks:
        if check.status == "fail":
            return "fail"
    for check in checks:
        if check.status == "warn":
            return "warn"
    return "pass"


def _alembic_head() -> str | None:
    """Return the current Alembic head revision or ``None`` on failure."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_root = Path(__file__).resolve().parents[3]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    sd = ScriptDirectory.from_config(cfg)
    heads = sd.get_heads()
    return heads[0] if heads else None


def _alembic_current(database_url: str) -> str | None:
    """Return the current Alembic revision for ``database_url`` or ``None``."""
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from sqlalchemy import create_engine

        backend_root = Path(__file__).resolve().parents[3]
        cfg = Config(str(backend_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend_root / "alembic"))
        cfg.set_main_option("sqlalchemy.url", database_url)
        engine = create_engine(database_url, future=True)
        try:
            with engine.connect() as connection:
                context = MigrationContext.configure(connection)
                current = context.get_current_revision()
                return current
        finally:
            engine.dispose()
    except Exception:
        return None


def _render_human(report: runner.DoctorReport) -> None:
    """Render the doctor report as a human-readable table."""
    print(f"lockverity doctor -- {report.overall.upper()}")
    print(f"version: {report.version}")
    print(f"runtime home: {report.home}")
    print("")
    width = max(len(check.name) for check in report.checks) if report.checks else 0
    for check in report.checks:
        marker = {
            "pass": "PASS",
            "warn": "WARN",
            "fail": "FAIL",
        }.get(check.status, "????")
        print(f"  [{marker}] {check.name.ljust(width)}  {check.message}")


__all__ = [
    "SENSITIVE_ENV_NAMES",
    "add_arguments",
    "build_report",
    "main",
]
