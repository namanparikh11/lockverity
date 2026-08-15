"""Tests for the v2.1 Part B3A runner state-publication contract.

The frozen CLI ``lockverity-cli.exe start`` is the documented
public entry point for the runtime. The v2.1 Part B3A
acceptance spec requires that **no false running state is
published** when the server fails to become healthy. The
contract:

  - when the health endpoint responds 200, the state file
    is published with the live child's identity (pid,
    instance id, module, creation time, started_at, port);
  - when the health endpoint does NOT respond within the
    configured timeout, the state file is NOT published and
    any stale state file from a previous run is removed
    defensively so a follow-up ``status`` does not see a
    ghost record.

The test exercises the bind-failure path the launcher
probes against. The runner's :func:`probe_port` is patched
to return ``in_use=False`` so the runner's pre-flight
port-probe accepts the port; the subsequent Uvicorn bind
fails because a separate listener (the test fixture) has
already claimed the address. The race is exactly the one
the launcher can encounter in production: a second process
binds the port between the probe and the bind.
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


def _free_port() -> int:
    """Ask the OS for an unused loopback port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _take_tcp_port(port: int) -> socket.socket:
    """Bind ``port`` and ``listen`` so any subsequent TCP bind fails."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    return s


def _spawn_cli_in_process(
    *, home: Path, port: int, timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run the CLI in-process for the same code path the
    packaged ``lockverity-cli.exe`` exercises."""
    env = {
        "LOCKVERITY_HOME": str(home),
        "PATH": r"C:\Windows\System32;C:\Windows",
        "SYSTEMROOT": r"C:\Windows",
        "TEMP": str(home / "tmp"),
        "TMP": str(home / "tmp"),
        "USERPROFILE": str(home / "tmp"),
    }
    (home / "tmp").mkdir(parents=True, exist_ok=True)
    # The bind-failure scenario only needs a valid dist root; it
    # must not depend on an old portable build from one developer's
    # machine. A clean packaging build is expected to remove those
    # stale output directories.
    frontend_dist = home / "frontend-dist"
    frontend_dist.mkdir(parents=True, exist_ok=True)
    (frontend_dist / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    code = (
        "import sys; "
        "from pathlib import Path; "
        "sys.path.insert(0, r'" + str(BACKEND_ROOT) + "'); "
        "from app.cli.home import ensure_home; "
        "from app.cli.runner import start; "
        "from app.cli import runner as cli_runner; "
        "from app.cli.state import read_state, state_file_path, write_state, make_state; "
        "home = ensure_home(Path(r'" + str(home) + "')); "
        # Patch probe_port to return ``in_use=False`` so the
        # runner's pre-flight probe accepts the port. The
        # subsequent Uvicorn bind then fails with
        # EADDRINUSE because a separate listener (the
        # test fixture) has already claimed the address.
        "cli_runner.probe_port = lambda host, port, **kw: cli_runner.PortProbe("
        "    host=host, port=port, in_use=False, detail='patched for test'); "
        # Point at a real frontend dist so the runner's
        # ``validate_dist`` call does not raise before
        # reaching the bind step.
        "dist_path = Path(r'" + str(frontend_dist) + "'); "
        # Pre-write a stale state file so the runner has to
        # defensively clear it on a failed start.
        "write_state(home, make_state("
        "    pid=99999, created_at='2020-01-01T00:00:00Z', "
        "    host='127.0.0.1', port=" + str(port) + ", "
        "    version='2.1.0', home=home, "
        "    frontend_dist=dist_path, "
        "    log_file=Path('ignored'), module='app.cli._serve', "
        "    started_at='2020-01-01T00:00:00Z', "
        "    instance_id='00000000-0000-0000-0000-000000000000')); "
        "res = start("
        "    home=home, host='127.0.0.1', port=" + str(port) + ", "
        "    frontend_dist=dist_path, database_url='sqlite:///:memory:', "
        "    log_level='warning', timeout=" + str(timeout) + ", "
        "    open_browser=False, foreground=False); "
        "print('HEALTH_OK=', res.health_check_ok); "
        "post = read_state(home); "
        "print('STATE_AFTER=', 'PRESENT' if post is not None else 'ABSENT'); "
    )
    return subprocess.run(  # noqa: S603 - argv is the interpreter plus an inline script
        [sys.executable, "-c", code],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=int(timeout + 30),
    )


@pytest.fixture
def temp_home(tmp_path: Path) -> Path:
    """A fresh ``LOCKVERITY_HOME`` for each test."""
    return tmp_path


class TestFailedStartNoStateFile:
    """A failed ``start`` must not leave a false-running state file."""

    def test_occupied_port_health_timeout_clears_state(self, temp_home: Path) -> None:
        port = _free_port()
        holder = _take_tcp_port(port)
        try:
            result = _spawn_cli_in_process(home=temp_home, port=port, timeout=8.0)
            # The CLI's own health check should fail (the
            # Uvicorn child cannot bind because the test
            # listener already holds the port). The
            # runner's contract is to surface that as
            # ``health_check_ok=False`` and not publish a
            # state file.
            assert "HEALTH_OK= False" in result.stdout, (
                f"expected HEALTH_OK=False, got:\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
            assert "STATE_AFTER= ABSENT" in result.stdout, (
                f"expected STATE_AFTER=ABSENT, got:\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
            # The state file path that the runner was
            # asked to manage must be absent on disk.
            from app.cli.state import state_file_path

            state_path = state_file_path(temp_home)
            assert not state_path.exists(), (
                f"state file {state_path} was left on disk after a failed start"
            )
        finally:
            holder.close()
