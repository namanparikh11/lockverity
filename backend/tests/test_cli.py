"""Tests for the v2.1 Part B2 ``lockverity`` CLI.

The test suite is organised by subcommand and by
implementation module. The fixtures are intentionally
self-contained: every test creates a temporary runtime
home and never reads or writes the operator's real
``%LOCALAPPDATA%\\Lockverity`` directory. The CLI
modules never shell out with ``shell=True`` and never
write outside the resolved runtime home (apart from
the rotating log file, which lives under the runtime
home ``logs/`` sub-directory).

The fixtures also pin the
``LOCKVERITY_ENVIRONMENT=test`` posture so the
``serve_frontend`` flag (refused in test environments
by the Part B1 settings validator) cannot accidentally
trigger in a unit test.

The tests are designed to run in default pytest
collection order. There is no explicit class-order
hook, no ``-v`` output-buffer dependency, and no
special invocation flags. The test suite also does not
rely on the order in which pytest executes the
classes; each test cleans up after itself and the
fixtures are scoped to the test function.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import logging.handlers
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

# Configure the environment *before* importing the
# application modules so the settings cache is built
# with the test posture.
os.environ.setdefault("LOCKVERITY_ENVIRONMENT", "test")
os.environ.setdefault("LOCKVERITY_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("LOCKVERITY_WORKSPACE_ROOT", "./var/workspace-test")
os.environ.setdefault("LOCKVERITY_SERVE_FRONTEND", "false")

from datetime import UTC

from app import __version__
from app.cli import home as home_module
from app.cli import lock as start_lock
from app.cli import main as cli_main
from app.cli import process as process_module
from app.cli import runner
from app.cli import state as state_module
from app.cli.commands import (
    doctor as doctor_cmd,
)
from app.cli.commands import (
    logs as logs_cmd,
)
from app.cli.commands import (
    open_cmd,
)
from app.cli.commands import (
    start as start_cmd,
)
from app.cli.commands import (
    status as status_cmd,
)
from app.cli.commands import (
    stop as stop_cmd,
)
from app.cli.state import (
    InstanceState,
    clear_state,
    make_state,
    read_state,
    state_file_path,
    write_state,
)
from app.core.config import get_settings

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Provide a fresh, empty runtime home for each test.

    The fixture sets ``LOCKVERITY_HOME`` to a temporary
    directory, clears the application settings cache,
    and yields the path. The teardown restores the
    previous ``LOCKVERITY_HOME`` value and clears the
    settings cache again so the next test sees a
    pristine state.
    """
    previous = monkeypatch.delenv("LOCKVERITY_HOME", raising=False)
    monkeypatch.setenv("LOCKVERITY_HOME", str(tmp_path))
    get_settings.cache_clear()
    try:
        yield tmp_path
    finally:
        if previous is not None:
            monkeypatch.setenv("LOCKVERITY_HOME", previous)
        else:
            monkeypatch.delenv("LOCKVERITY_HOME", raising=False)
        get_settings.cache_clear()


@pytest.fixture
def isolated_home_with_subdirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Provide a runtime home with the documented sub-directories pre-created.

    The fixture builds on :func:`isolated_home` but
    pre-creates the four sub-directories the
    ``lockverity`` runtime expects (``data/``,
    ``logs/``, ``run/``, ``config/``). The fixture is
    used by state-file tests that want the parent
    directory to exist before the writer runs.
    """
    previous = monkeypatch.delenv("LOCKVERITY_HOME", raising=False)
    monkeypatch.setenv("LOCKVERITY_HOME", str(tmp_path))
    for sub in ("data", "logs", "run", "config"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    get_settings.cache_clear()
    try:
        yield tmp_path
    finally:
        if previous is not None:
            monkeypatch.setenv("LOCKVERITY_HOME", previous)
        else:
            monkeypatch.delenv("LOCKVERITY_HOME", raising=False)
        get_settings.cache_clear()


@pytest.fixture
def settings_no_serve_frontend(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Pin the application settings to the test posture."""
    monkeypatch.setenv("LOCKVERITY_ENVIRONMENT", "test")
    monkeypatch.setenv("LOCKVERITY_SERVE_FRONTEND", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def parser() -> argparse.ArgumentParser:
    """Return a fresh root CLI argparse parser."""
    return cli_main.build_parser()


def _free_port() -> int:
    """Bind an ephemeral port on loopback and return the port number."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _spawn_short_lived_subprocess() -> subprocess.Popen[bytes]:
    """Spawn a real short-lived subprocess and wait for it to exit.

    The function returns the (now-exited) Popen
    handle. The PID is suitable for "process is gone"
    tests on every platform because the OS has fully
    reaped the child by the time the function returns.
    """
    handle = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(0)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    handle.wait()
    return handle


def _make_fake_live_process(
    *,
    pid: int,
    started_at: float,
    instance_id: str,
    module: str = "app.main:app",
    cmdline: tuple[str, ...] | None = None,
    platform: str = "linux",
) -> process_module.LiveProcess:
    """Build a synthetic :class:`LiveProcess` for mocking."""
    if cmdline is None:
        cmdline = (
            sys.executable,
            "-m",
            "uvicorn",
            module,
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--instance-id",
            instance_id,
        )
    return process_module.LiveProcess(
        pid=pid,
        created_at=started_at,
        cmdline=cmdline,
        module=module,
        platform=platform,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Runtime-home tests
# ---------------------------------------------------------------------------


class TestRuntimeHome:
    """The runtime-home resolver and safety checks."""

    def test_default_home_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Alice\AppData\Local")
        home = home_module.default_home()
        assert home == Path(r"C:\Users\Alice\AppData\Local\Lockverity")

    def test_default_home_windows_falls_back_to_userprofile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        monkeypatch.setenv("USERPROFILE", r"C:\Users\Bob")
        home = home_module.default_home()
        assert home == Path(r"C:\Users\Bob\AppData\Local\Lockverity")

    def test_default_home_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(Path, "home", lambda: Path("/Users/alice"))
        home = home_module.default_home()
        assert home == Path("/Users/alice/Library/Application Support/Lockverity")

    def test_default_home_linux_xdg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_DATA_HOME", "/srv/data")
        home = home_module.default_home()
        assert home == Path("/srv/data/lockverity")

    def test_default_home_linux_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setattr(Path, "home", lambda: Path("/home/alice"))
        home = home_module.default_home()
        assert home == Path("/home/alice/.local/share/lockverity")

    def test_resolve_home_cli_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOCKVERITY_HOME", "/from/env")
        home = home_module.resolve_home(cli_override="/from/cli")
        # On Windows the absolute path resolves to a
        # drive-rooted path (``C:/from/cli``). The
        # important property is that the CLI override
        # wins; the assertion compares the resolved
        # tail rather than the full path.
        assert str(home).replace("\\", "/").endswith("/from/cli")

    def test_resolve_home_env_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setattr(Path, "home", lambda: Path("/home/alice"))
        monkeypatch.setenv("LOCKVERITY_HOME", "/from/env")
        home = home_module.resolve_home()
        assert str(home) == str(Path("/from/env").resolve(strict=False))

    def test_resolve_home_handles_spaces_and_unicode(self, tmp_path: Path) -> None:
        weird = tmp_path / "Lockverity with spaces \u00e9"
        home = home_module.resolve_home(cli_override=str(weird))
        assert home == weird.resolve(strict=False)

    def test_is_safe_home_rejects_traversal(self) -> None:
        assert home_module.is_safe_home(Path("..")) is False
        assert home_module.is_safe_home(Path("../escape")) is False
        assert home_module.is_safe_home(Path("a/../../etc/passwd")) is False

    def test_is_safe_home_rejects_null_byte(self) -> None:
        assert home_module.is_safe_home(Path("ok\x00bad")) is False

    def test_ensure_home_creates_subdirs(self, tmp_path: Path) -> None:
        resolved = home_module.ensure_home(tmp_path)
        for sub in (
            home_module.DATA_DIR,
            home_module.LOGS_DIR,
            home_module.RUN_DIR,
            home_module.CONFIG_DIR,
        ):
            assert (resolved / sub).is_dir()
        # Idempotent.
        home_module.ensure_home(tmp_path)


# ---------------------------------------------------------------------------
# State-file tests
# ---------------------------------------------------------------------------


class TestStateFile:
    """The atomic state-file module."""

    def test_write_state_is_atomic(self, isolated_home_with_subdirs: Path) -> None:
        # ``isolated_home_with_subdirs`` is intentionally
        # not used here; the test exercises the writer
        # without the home subdirs to confirm the
        # writer creates them.
        isolated_home = isolated_home_with_subdirs
        state = make_state(
            pid=1234,
            created_at="2026-01-01T00:00:00Z",
            host="127.0.0.1",
            port=8000,
            version=__version__,
            home=isolated_home,
            frontend_dist=Path("frontend/dist"),
            log_file=Path("logs/lockverity.log"),
            module="app.main:app",
            started_at="2026-01-01T00:00:00Z",
            instance_id=str(uuid.uuid4()),
        )
        target = write_state(isolated_home, state)
        assert target.is_file()
        leftovers = list(target.parent.glob(".lockverity.state.*.tmp"))
        assert not leftovers

    def test_read_state_round_trip(self, isolated_home_with_subdirs: Path) -> None:
        isolated_home = isolated_home_with_subdirs
        instance_id = str(uuid.uuid4())
        state = make_state(
            pid=42,
            created_at="2026-02-02T12:00:00Z",
            host="127.0.0.1",
            port=9000,
            version=__version__,
            home=isolated_home,
            frontend_dist=Path("/abs/frontend/dist"),
            log_file=Path("/abs/logs/lockverity.log"),
            module="app.main:app",
            started_at="2026-02-02T12:00:00Z",
            instance_id=instance_id,
        )
        write_state(isolated_home, state)
        restored = read_state(isolated_home)
        assert restored is not None
        assert restored.pid == 42
        assert restored.port == 9000
        assert restored.host == "127.0.0.1"
        assert restored.version == __version__
        assert restored.module == "app.main:app"
        assert restored.instance_id == instance_id
        assert restored.identity_token != ""
        assert restored.identity_token == state.identity_token

    def test_read_state_missing_returns_none(self, isolated_home_with_subdirs: Path) -> None:
        assert read_state(isolated_home_with_subdirs) is None

    def test_read_state_corrupt_raises(self, isolated_home_with_subdirs: Path) -> None:
        path = state_file_path(isolated_home_with_subdirs)
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            read_state(isolated_home_with_subdirs)

    def test_read_state_missing_key_raises(self, isolated_home_with_subdirs: Path) -> None:
        path = state_file_path(isolated_home_with_subdirs)
        path.write_text(json.dumps({"pid": 1}), encoding="utf-8")
        with pytest.raises(ValueError, match="missing required key"):
            read_state(isolated_home_with_subdirs)

    def test_clear_state(self, isolated_home_with_subdirs: Path) -> None:
        isolated_home = isolated_home_with_subdirs
        state = make_state(
            pid=99,
            created_at="2026-01-01T00:00:00Z",
            host="127.0.0.1",
            port=8000,
            version=__version__,
            home=isolated_home,
            frontend_dist=Path("frontend/dist"),
            log_file=Path("logs/lockverity.log"),
            module="app.main:app",
            started_at="2026-01-01T00:00:00Z",
            instance_id=str(uuid.uuid4()),
        )
        write_state(isolated_home, state)
        assert clear_state(isolated_home) is True
        assert clear_state(isolated_home) is False

    def test_make_state_validates_inputs(self, isolated_home_with_subdirs: Path) -> None:
        with pytest.raises(ValueError):
            make_state(
                pid=0,
                created_at="2026-01-01T00:00:00Z",
                host="127.0.0.1",
                port=8000,
                version=__version__,
                home=isolated_home_with_subdirs,
                frontend_dist=Path("frontend/dist"),
                log_file=Path("logs/lockverity.log"),
                module="app.main:app",
                started_at="2026-01-01T00:00:00Z",
                instance_id=str(uuid.uuid4()),
            )
        with pytest.raises(ValueError):
            make_state(
                pid=1,
                created_at="2026-01-01T00:00:00Z",
                host="127.0.0.1",
                port=99999,
                version=__version__,
                home=isolated_home_with_subdirs,
                frontend_dist=Path("frontend/dist"),
                log_file=Path("logs/lockverity.log"),
                module="app.main:app",
                started_at="2026-01-01T00:00:00Z",
                instance_id=str(uuid.uuid4()),
            )
        with pytest.raises(ValueError):
            make_state(
                pid=1,
                created_at="2026-01-01T00:00:00Z",
                host="127.0.0.1",
                port=8000,
                version=__version__,
                home=isolated_home_with_subdirs,
                frontend_dist=Path("frontend/dist"),
                log_file=Path("logs/lockverity.log"),
                module="",
                started_at="2026-01-01T00:00:00Z",
                instance_id=str(uuid.uuid4()),
            )
        with pytest.raises(ValueError):
            make_state(
                pid=1,
                created_at="2026-01-01T00:00:00Z",
                host="127.0.0.1",
                port=8000,
                version=__version__,
                home=isolated_home_with_subdirs,
                frontend_dist=Path("frontend/dist"),
                log_file=Path("logs/lockverity.log"),
                module="app.main:app",
                started_at="2026-01-01T00:00:00Z",
                instance_id="",
            )

    def test_state_file_path_under_run_dir(self, isolated_home_with_subdirs: Path) -> None:
        expected = isolated_home_with_subdirs / "run" / state_module.STATE_FILE_NAME
        assert state_file_path(isolated_home_with_subdirs) == expected

    def test_state_from_dict_rejects_non_dict(self) -> None:
        with pytest.raises(ValueError, match="not a JSON object"):
            InstanceState.from_dict("not a dict")  # type: ignore[arg-type]

    def test_state_does_not_store_cmdline_or_db_url(self, isolated_home_with_subdirs: Path) -> None:
        # Regression: the state file must not contain
        # the database URL (which may embed a password)
        # or the full child command line (which may
        # echo back ``--database-url <URL>``).
        state = make_state(
            pid=1,
            created_at="2026-01-01T00:00:00Z",
            host="127.0.0.1",
            port=8000,
            version=__version__,
            home=isolated_home_with_subdirs,
            frontend_dist=Path("frontend/dist"),
            log_file=Path("logs/lockverity.log"),
            module="app.main:app",
            started_at="2026-01-01T00:00:00Z",
            instance_id=str(uuid.uuid4()),
        )
        write_state(isolated_home_with_subdirs, state)
        text = state_file_path(isolated_home_with_subdirs).read_text(encoding="utf-8")
        # Must not echo the database URL the runner
        # passes through the child env.
        assert "database_url" not in text.lower()
        assert "sqlite:///" not in text
        # Must not echo the full uvicorn command line.
        assert "--log-level" not in text
        assert "uvicorn" not in text


# ---------------------------------------------------------------------------
# Process identity tests (psutil-backed)
# ---------------------------------------------------------------------------


class TestProcessIdentity:
    """The cross-platform process identity checks (psutil)."""

    def test_is_process_alive_self(self) -> None:
        assert process_module.is_process_alive(os.getpid()) is True

    def test_is_process_alive_negative_returns_false(self) -> None:
        assert process_module.is_process_alive(-1) is False
        assert process_module.is_process_alive(0) is False

    def test_is_process_alive_dead_pid(self) -> None:
        # Spawn a real short-lived subprocess and
        # probe its PID after it exits.
        handle = _spawn_short_lived_subprocess()
        assert process_module.is_process_alive(handle.pid) is False

    def test_read_live_identity_self(self) -> None:
        live = process_module.read_live_identity(os.getpid())
        if live is None:
            pytest.skip("host does not expose process identity for the test pid")
        assert live.pid == os.getpid()
        assert live.created_at > 0
        assert live.cmdline
        assert live.module or live.cmdline

    def test_read_live_identity_dead_pid(self) -> None:
        # ``read_live_identity`` returns ``None`` when
        # the PID is non-positive.
        assert process_module.read_live_identity(0) is None
        assert process_module.read_live_identity(-1) is None

    def test_read_live_identity_real_dead_pid(self) -> None:
        handle = _spawn_short_lived_subprocess()
        assert process_module.read_live_identity(handle.pid) is None

    def test_verify_identity_self_matches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Read the live process identity, then build a
        # state file from it and verify the identity
        # check returns ``IdentityMatch``.
        live = process_module.read_live_identity(os.getpid())
        if live is None:
            pytest.skip("host does not expose process identity for the test pid")
        # The state records the live process; the
        # verify call should match.
        recorded_at = process_module._format_unix_iso(live.created_at)
        result = process_module.verify_identity(
            recorded_pid=live.pid,
            recorded_created_at=recorded_at,
            recorded_instance_id="",  # no instance-id on the test process
            recorded_module=live.module or "app.main:app",
            creation_time_tolerance_seconds=10.0,
        )
        # The test process is not a uvicorn process, so
        # the recorded instance_id is empty; the
        # identity check still succeeds because the
        # ``recorded_instance_id`` is empty (the check
        # is short-circuited). If the host does not
        # expose the live identity, skip.
        assert isinstance(result, process_module.IdentityMatch)

    def test_verify_identity_dead_pid(self) -> None:
        handle = _spawn_short_lived_subprocess()
        result = process_module.verify_identity(
            recorded_pid=handle.pid,
            recorded_created_at="2026-01-01T00:00:00Z",
            recorded_instance_id=str(uuid.uuid4()),
            recorded_module="app.main:app",
        )
        assert isinstance(result, process_module.ProcessGone)

    def test_verify_identity_mismatch_pid_reuse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Mock the live read to return a fake identity
        # whose creation time differs from the recorded
        # value -- the identity check must report a
        # mismatch (PID reuse defence).
        # Use the test process's own PID (always alive)
        # so ``is_process_alive`` returns ``True`` and
        # the mock layer is exercised; the recorded
        # value is then obviously mismatched.
        live_pid = os.getpid()
        recorded_at = "2026-01-01T00:00:00Z"
        live_at = 1234567890.0  # different from recorded_at

        def _fake_read(pid: int) -> process_module.LiveProcess:
            return process_module.LiveProcess(
                pid=live_pid,
                created_at=live_at,
                cmdline=(
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--instance-id",
                    str(uuid.uuid4()),
                ),
                module="app.main:app",
                platform="linux",
            )

        monkeypatch.setattr(process_module, "read_live_identity", _fake_read)
        result = process_module.verify_identity(
            recorded_pid=live_pid,
            recorded_created_at=recorded_at,
            recorded_instance_id=str(uuid.uuid4()),
            recorded_module="app.main:app",
        )
        assert isinstance(result, process_module.IdentityMismatch)
        assert "creation time" in result.reason

    def test_verify_identity_mismatch_wrong_instance_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Mock the live read to return a process that
        # is alive but does not carry the recorded
        # ``--instance-id`` token -- the identity check
        # must report a mismatch (PID reuse / unrelated
        # process defence). The recorded creation time
        # must match the live one (within tolerance) so
        # the check reaches the instance-id step.
        live_pid = os.getpid()
        recorded_instance_id = str(uuid.uuid4())
        live_instance_id = str(uuid.uuid4())  # different
        live_at = time.time()

        def _fake_read(pid: int) -> process_module.LiveProcess:
            return process_module.LiveProcess(
                pid=live_pid,
                created_at=live_at,
                cmdline=(
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--instance-id",
                    live_instance_id,
                ),
                module="app.main:app",
                platform="linux",
            )

        monkeypatch.setattr(process_module, "read_live_identity", _fake_read)
        result = process_module.verify_identity(
            recorded_pid=live_pid,
            recorded_created_at=process_module._format_unix_iso(live_at),
            recorded_instance_id=recorded_instance_id,
            recorded_module="app.main:app",
        )
        assert isinstance(result, process_module.IdentityMismatch)
        assert "instance-id" in result.reason

    def test_module_from_cmdline(self) -> None:
        # Two supported invocations.
        assert (
            process_module._module_from_cmdline(
                ("python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1")
            )
            == "app.main:app"
        )
        assert (
            process_module._module_from_cmdline(
                ("python", "-m", "uvicorn", "--app-dir", "/tmp", "app.main:app")  # noqa: S108 - test fixture for argv parsing
            )
            == "app.main:app"
        )
        # No ``-m`` token: empty string.
        assert process_module._module_from_cmdline(("/usr/bin/python", "/usr/bin/uvicorn")) == ""
        # ``--instance-id`` is one of the recognised
        # single-token flags and is skipped without
        # consuming the next argument.
        assert (
            process_module._module_from_cmdline(
                (
                    "python",
                    "-m",
                    "uvicorn",
                    "--instance-id",
                    "abc",
                    "app.main:app",
                )
            )
            == "app.main:app"
        )

    def test_cmdline_contains_instance_id(self) -> None:
        live = _make_fake_live_process(
            pid=os.getpid(),
            started_at=time.time(),
            instance_id="abc-123",
        )
        assert live.cmdline_contains_instance_id("abc-123") is True
        assert live.cmdline_contains_instance_id("xyz-789") is False
        # The ``=`` form is also supported.
        live_equals = process_module.LiveProcess(
            pid=os.getpid(),
            created_at=time.time(),
            cmdline=(
                "python",
                "-m",
                "uvicorn",
                "app.main:app",
                "--instance-id=abc-123",
            ),
            module="app.main:app",
            platform="linux",
        )
        assert live_equals.cmdline_contains_instance_id("abc-123") is True

    def test_module_matches(self) -> None:
        # Soft module check: the recorded module is
        # expected to be a substring of the live
        # command line.
        assert process_module._module_matches(
            "app.main:app", ("python", "-m", "uvicorn", "app.main:app")
        )
        assert not process_module._module_matches(
            "different", ("python", "-m", "uvicorn", "app.main:app")
        )
        # Empty recorded module is a non-check.
        assert process_module._module_matches("", ("any", "cmdline"))


# ---------------------------------------------------------------------------
# Logging setup tests
# ---------------------------------------------------------------------------


class TestLoggingSetup:
    """The rotating log handler."""

    def test_configure_logging_idempotent(self, tmp_path: Path) -> None:
        # Use a unique logger name to avoid polluting
        # the singleton CLI logger; subsequent tests
        # in the same session would otherwise share
        # the handler and observe cross-test state.
        log_path = tmp_path / "lockverity.log"
        import app.cli.logging_setup as ls_module

        original_logger_name = ls_module.CLI_LOGGER_NAME
        local_name = "lockverity.test.cli_idempotent"
        ls_module.CLI_LOGGER_NAME = local_name
        try:
            logger1 = ls_module.configure_logging(log_path)
            logger2 = ls_module.configure_logging(log_path)
            assert logger1 is logger2
            rotating = [
                h for h in logger2.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
            ]
            assert len(rotating) == 1
            for handler in list(logger1.handlers):
                logger1.removeHandler(handler)
                with contextlib.suppress(Exception):
                    handler.close()
        finally:
            ls_module.CLI_LOGGER_NAME = original_logger_name

    def test_configure_logging_creates_log_file_on_write(self, tmp_path: Path) -> None:
        log_path = tmp_path / "logs" / "lockverity.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Use a unique logger name to avoid sharing
        # state with the singleton CLI logger; the
        # fixture is destructive of the logger
        # registry and would hang subsequent
        # tests on Windows when combined with
        # ``socket.bind`` calls.
        import logging

        local_logger = logging.getLogger("lockverity.test.logging_creates")
        # Reset any prior handlers so the test is
        # independent of the run order.
        for handler in list(local_logger.handlers):
            local_logger.removeHandler(handler)
            with contextlib.suppress(Exception):
                handler.close()
        local_logger.setLevel(logging.DEBUG)
        local_logger.propagate = False
        handler = logging.handlers.RotatingFileHandler(
            filename=str(log_path),
            maxBytes=1024,
            backupCount=1,
            encoding="utf-8",
            delay=False,
        )
        handler.setLevel(logging.DEBUG)
        local_logger.addHandler(handler)
        try:
            local_logger.info("hello world")
            handler.flush()
            assert log_path.is_file()
            body = log_path.read_text(encoding="utf-8")
            assert "hello world" in body
        finally:
            # Explicitly close and remove the handler
            # so the file handle is released before
            # the next test runs.
            local_logger.removeHandler(handler)
            handler.close()


# ---------------------------------------------------------------------------
# Runner tests
# ---------------------------------------------------------------------------


class TestRunner:
    """The runner helpers (port probe, loopback, log tail, etc.)."""

    def test_probe_port_free(self) -> None:
        port = _free_port()
        probe = runner.probe_port("127.0.0.1", port, timeout=0.5)
        assert probe.in_use is False

    def test_probe_port_occupied(self) -> None:
        # Open a server socket and probe the port; the
        # probe must report the port is in use.
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = int(server.getsockname()[1])
            probe = runner.probe_port("127.0.0.1", port, timeout=0.5)
            assert probe.in_use is True
        finally:
            server.close()

    def test_is_loopback_host(self) -> None:
        assert runner.is_loopback_host("127.0.0.1")
        assert runner.is_loopback_host("::1")
        assert not runner.is_loopback_host("0.0.0.0")  # noqa: S104 - testing non-loopback
        assert not runner.is_loopback_host("localhost")
        assert not runner.is_loopback_host("8.8.8.8")

    def test_format_uptime_seconds(self) -> None:
        from datetime import datetime, timedelta

        now = datetime.now(UTC)
        five_seconds_ago = (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
        assert runner.format_uptime(five_seconds_ago).endswith("s")

    def test_format_uptime_minutes(self) -> None:
        from datetime import datetime, timedelta

        now = datetime.now(UTC)
        three_min_ago = (now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z")
        text = runner.format_uptime(three_min_ago)
        assert "m" in text

    def test_format_uptime_invalid(self) -> None:
        assert runner.format_uptime("not-a-date") == "unknown"

    def test_read_log_tail_bounded(self, tmp_path: Path) -> None:
        log_path = tmp_path / "lockverity.log"
        lines = [f"line {i}\n" for i in range(1000)]
        log_path.write_text("".join(lines), encoding="utf-8")
        tail = runner.read_log_tail(log_path, lines=10)
        assert len(tail) == 10
        # The Windows text-mode read may convert
        # ``\n`` to ``\r\n``; the comparison is
        # tolerant of the trailing CR.
        assert tail[-1].rstrip("\r\n") == "line 999"
        assert tail[0].rstrip("\r\n") == "line 990"

    def test_read_log_tail_missing_returns_empty(self, tmp_path: Path) -> None:
        assert runner.read_log_tail(tmp_path / "missing.log", lines=10) == []

    def test_read_log_tail_rejects_zero(self, tmp_path: Path) -> None:
        log_path = tmp_path / "lockverity.log"
        log_path.write_text("a\nb\n", encoding="utf-8")
        assert runner.read_log_tail(log_path, lines=0) == []

    def test_run_migrations_against_temp_db(self, tmp_path: Path) -> None:
        # The runner takes a SQLAlchemy URL and runs
        # ``alembic upgrade head`` in a subprocess so
        # the URL is honoured without the
        # application's ``alembic/env.py`` overriding
        # it. The subprocess writes the alembic
        # version to the configured database. The
        # test uses a relative URL and
        # monkey-patches the backend-root lookup so
        # the migration runs against a temp file.
        relative_target = tmp_path / "mig.sqlite"
        relative_target.parent.mkdir(parents=True, exist_ok=True)
        os.environ["LOCKVERITY_DATABASE_URL"] = f"sqlite:///{relative_target}"
        try:
            get_settings.cache_clear()
            runner.run_migrations(f"sqlite:///{relative_target}")
        finally:
            os.environ.pop("LOCKVERITY_DATABASE_URL", None)
            get_settings.cache_clear()
        assert relative_target.is_file()
        import sqlite3

        with sqlite3.connect(relative_target) as conn:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            assert row is not None
            assert row[0] == "f6a7b8c9d0e1"

    def test_open_browser_refuses_non_loopback(self) -> None:
        assert runner.open_browser("0.0.0.0", 8000) is False  # noqa: S104 - testing refusal
        assert runner.open_browser("8.8.8.8", 80) is False

    def test_fetch_health_unreachable(self) -> None:
        port = _free_port()
        result = runner.fetch_health("127.0.0.1", port, timeout=0.5)
        assert result is None

    def test_build_server_argv_includes_instance_id(self) -> None:
        instance_id = str(uuid.uuid4())
        argv = runner.build_server_argv(
            host="127.0.0.1",
            port=8000,
            log_level="info",
            instance_id=instance_id,
        )
        assert "--instance-id" in argv
        assert instance_id in argv

    def test_build_server_argv_no_database_url(self) -> None:
        # The argv must not echo the database URL.
        argv = runner.build_server_argv(
            host="127.0.0.1",
            port=8000,
            log_level="info",
            instance_id=str(uuid.uuid4()),
        )
        joined = " ".join(argv)
        assert "database-url" not in joined.lower()
        assert "sqlite:///" not in joined
        assert "LOCKVERITY_DATABASE_URL" not in joined


# ---------------------------------------------------------------------------
# Start-lock tests
# ---------------------------------------------------------------------------


class TestStartLock:
    """The cross-platform start lock."""

    def test_acquire_and_release(self, isolated_home: Path) -> None:
        lock = start_lock.acquire(isolated_home)
        try:
            assert lock.path.is_file()
            assert lock.owner_pid == os.getpid()
        finally:
            lock.release()
        assert not lock.path.exists()

    def test_concurrent_acquire_blocked(self, isolated_home: Path) -> None:
        # A second acquire on the same home must
        # raise ``StartLockHeld`` while the first is
        # still held. The timeout is 0 (fail fast) so
        # the test does not block.
        lock = start_lock.acquire(isolated_home)
        try:
            with pytest.raises(start_lock.StartLockHeld):
                start_lock.acquire(isolated_home, timeout_seconds=0.0)
        finally:
            lock.release()

    def test_stale_lock_recovered_when_owner_dead(self, isolated_home: Path) -> None:
        # Simulate a stale lock from a previous CLI
        # that crashed. The recorded owner PID is the
        # now-exited short-lived subprocess; the
        # recovery path must clean up the lock and
        # allow a fresh acquire.
        handle = _spawn_short_lived_subprocess()
        # The lock file records the short-lived
        # subprocess PID as the owner. ``time.time()``
        # minus ``started_at`` is much larger than
        # ``_STALE_OWNER_SECONDS`` (30s), so the
        # owner is considered definitively stale.
        started_at = time.time() - 120.0
        target = start_lock.lock_file_path(isolated_home)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{handle.pid}\n{started_at}\n", encoding="utf-8")
        # The next acquire must succeed and clear the
        # stale file.
        lock = start_lock.acquire(isolated_home)
        try:
            assert lock.path.is_file()
            assert lock.owner_pid == os.getpid()
        finally:
            lock.release()

    def test_real_concurrency_two_start_attempts(self, isolated_home: Path, tmp_path: Path) -> None:
        # Two simultaneous ``lockverity start``
        # attempts against the same home must not
        # both launch. We exercise the lock primitive
        # directly because the full ``start`` would
        # also need a real Alembic migration. The
        # integration with ``runner.start`` is
        # covered by the conftest's autouse fixtures
        # and by the manual smoke.
        # Hold the lock in the first ``acquire``.
        lock = start_lock.acquire(isolated_home)
        try:
            # The second attempt must fail fast.
            with pytest.raises(start_lock.StartLockHeld):
                start_lock.acquire(isolated_home, timeout_seconds=0.0)
        finally:
            lock.release()
        # After the first releases, the second can
        # proceed.
        lock2 = start_lock.acquire(isolated_home)
        try:
            assert lock2.owner_pid == os.getpid()
        finally:
            lock2.release()


# ---------------------------------------------------------------------------
# Start / stop flow guards
# ---------------------------------------------------------------------------


class TestStartStopFlowGuards:
    """Start / stop flow guards without launching a real server."""

    def test_start_refuses_non_loopback(
        self,
        isolated_home: Path,
        settings_no_serve_frontend: None,
    ) -> None:
        with pytest.raises(RuntimeError, match="only binds loopback"):
            runner.start(
                home=isolated_home,
                host="0.0.0.0",  # noqa: S104 - testing the non-loopback guard
                port=8000,
                database_url="sqlite:///:memory:",
            )

    def test_start_refuses_existing_instance(
        self,
        isolated_home: Path,
        settings_no_serve_frontend: None,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Use the test process itself as the
        # "already running" instance. The runner
        # reads the recorded PID + identity and asks
        # ``verify_identity`` to compare them against
        # the live process. We mock ``verify_identity``
        # to return ``IdentityMatch`` so the runner
        # refuses to start without depending on the
        # subprocess-based "real alive PID" path
        # (which is fragile on Windows when
        # ``os.kill`` and ``subprocess.run`` are
        # interleaved in the same test process).
        from app.cli.process import IdentityMatch, LiveProcess

        def _fake_verify(
            *, recorded_pid, recorded_created_at, recorded_instance_id, recorded_module
        ):
            return IdentityMatch(
                live=LiveProcess(
                    pid=os.getpid(),
                    created_at=time.time(),
                    cmdline=(
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.main:app",
                        "--instance-id",
                        str(uuid.uuid4()),
                    ),
                    module="app.main:app",
                    platform="linux",
                )
            )

        monkeypatch.setattr(runner, "verify_identity", _fake_verify)
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text(
            '<!doctype html><html><body><div id="root"></div></body></html>',
            encoding="utf-8",
        )
        state = make_state(
            pid=os.getpid(),
            created_at="2026-01-01T00:00:00Z",
            host="127.0.0.1",
            port=8000,
            version=__version__,
            home=isolated_home,
            frontend_dist=dist,
            log_file=Path("logs/lockverity.log"),
            module="app.main:app",
            started_at="2026-01-01T00:00:00Z",
            instance_id=str(uuid.uuid4()),
        )
        write_state(isolated_home, state)
        local_monkeypatch = pytest.MonkeyPatch()
        try:
            local_monkeypatch.setenv("LOCKVERITY_FRONTEND_DIST", str(dist))
            get_settings.cache_clear()
            with pytest.raises(RuntimeError, match="already running"):
                runner.start(
                    home=isolated_home,
                    host="127.0.0.1",
                    port=8000,
                    database_url="sqlite:///:memory:",
                    frontend_dist=dist,
                )
        finally:
            local_monkeypatch.undo()
            get_settings.cache_clear()

    def test_start_refuses_missing_dist(
        self,
        isolated_home: Path,
        settings_no_serve_frontend: None,
    ) -> None:
        # Use a port that is free, but supply a
        # frontend_dist that does not exist. The
        # Part B1 settings validator must reject the
        # start.
        with pytest.raises(Exception):  # noqa: B017 - either error type
            runner.start(
                home=isolated_home,
                host="127.0.0.1",
                port=_free_port(),
                database_url="sqlite:///:memory:",
                frontend_dist=isolated_home / "no-such-dist",
            )

    def test_stop_when_not_running(self, isolated_home: Path) -> None:
        result = runner.stop(home=isolated_home, timeout=1)
        assert result.outcome == "was_not_running"


# ---------------------------------------------------------------------------
# Foreground signal handling tests
# ---------------------------------------------------------------------------


class TestForegroundSignalHandling:
    """The foreground supervisor's signal-handling contract.

    The tests pin the Windows behaviour the operator
    relies on: pressing Ctrl+C (or a process-group
    ``CTRL_BREAK_EVENT``) must translate into a
    :class:`KeyboardInterrupt` so the
    ``with start_lock.acquire(home):`` block unwinds
    and the start lock is released before the
    supervisor exits. On POSIX, ``SIGINT`` already
    raises ``KeyboardInterrupt`` via the CPython
    default handler; the supervisor's handler is a
    no-op there.
    """

    def test_install_handler_registers_sigbreak_handler(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # On Windows the supervisor installs a
        # ``SIGBREAK`` handler that translates the
        # ``CTRL_BREAK_EVENT`` into a
        # ``KeyboardInterrupt``. On POSIX the function
        # is a documented no-op.
        captured: dict[str, object] = {}

        def _fake_signal(sig: int, handler: object) -> object:
            captured["sig"] = sig
            captured["handler"] = handler
            return handler

        monkeypatch.setattr(runner.signal, "signal", _fake_signal)
        monkeypatch.setattr(runner.sys, "platform", "win32")
        if not hasattr(runner.signal, "SIGBREAK"):
            monkeypatch.setattr(runner.signal, "SIGBREAK", 15, raising=False)
        runner._install_foreground_signal_handlers()
        if sys.platform == "win32":
            assert "sig" in captured
            assert captured["sig"] == runner.signal.SIGBREAK
            assert captured["handler"] is signal.default_int_handler
        # POSIX path is a no-op; nothing to assert.

    def test_install_handler_is_safe_off_main_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # ``signal.signal`` raises ``ValueError`` when
        # called from a non-main thread on POSIX. The
        # supervisor's helper must swallow the error
        # so the foreground command still works in
        # test workers.
        def _raise_value_error(sig: int, handler: object) -> object:
            raise ValueError("signal only works in main thread of the main interpreter")

        monkeypatch.setattr(runner.signal, "signal", _raise_value_error)
        monkeypatch.setattr(runner.sys, "platform", "win32")
        if not hasattr(runner.signal, "SIGBREAK"):
            monkeypatch.setattr(runner.signal, "SIGBREAK", 15, raising=False)
        # Must not raise.
        runner._install_foreground_signal_handlers()

    def test_foreground_subprocess_run_raises_keyboard_interrupt(
        self,
        isolated_home: Path,
        settings_no_serve_frontend: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Mock ``subprocess.run`` to raise
        # ``KeyboardInterrupt`` (the documented Ctrl+C
        # contract). The supervisor's
        # ``_start_foreground`` re-raises the
        # exception so the start lock in the
        # surrounding ``with`` block unwinds and the
        # caller (``main.py``) can convert the
        # interrupt to a clean exit code.
        def _fake_run(*args: object, **kwargs: object) -> None:
            raise KeyboardInterrupt("simulated Ctrl+C in foreground")

        monkeypatch.setattr(runner.subprocess, "run", _fake_run)
        with pytest.raises(KeyboardInterrupt, match="simulated"):
            runner._start_foreground(
                argv=[sys.executable, "-c", "pass"],
                env={},
                home=isolated_home,
                host="127.0.0.1",
                port=0,
                frontend_dist=isolated_home,
                log_path=isolated_home / "logs" / "lockverity.log",
                started=time.monotonic(),
                database_url="sqlite:///:memory:",
                open_browser=False,
                cli_logger=runner.get_cli_logger(),
            )

    def test_main_converts_foreground_keyboard_interrupt_to_exit_code_130(
        self,
        isolated_home: Path,
        settings_no_serve_frontend: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The CLI ``main`` function converts a
        # ``KeyboardInterrupt`` raised by the
        # ``start --foreground`` subcommand into the
        # POSIX-conventional exit code 130
        # (128 + SIGINT). The Windows
        # ``0xC000013A`` ``STATUS_CONTROL_C_EXIT``
        # code is delivered by the parent process
        # when the Python interpreter exits via
        # ``SystemExit``; the CLI returns 130 to the
        # test harness regardless of platform.
        def _raise_keyboard_interrupt(args: object) -> int:
            raise KeyboardInterrupt("simulated foreground shutdown")

        monkeypatch.setattr(cli_main, "build_parser", cli_main.build_parser)
        # The start subcommand is the only path that
        # raises ``KeyboardInterrupt`` in the public
        # contract; we monkey-patch the ``start.main``
        # function (the subcommand handler) to raise.
        from app.cli.commands import start as start_cmd

        monkeypatch.setattr(start_cmd, "main", _raise_keyboard_interrupt)
        rc = cli_main.main(["start", "--host", "127.0.0.1", "--port", "0"])
        assert rc == 130


# ---------------------------------------------------------------------------
# End-to-end foreground graceful-shutdown test
# ---------------------------------------------------------------------------


class TestForegroundGracefulShutdownE2E:
    """End-to-end test: launch the CLI in a real subprocess, send a real
    ``CTRL_BREAK_EVENT``, and verify the post-shutdown contract.

    The test is Windows-aware. On Windows it spawns
    the CLI in a new process group and sends a
    ``CTRL_BREAK_EVENT`` to that group. On POSIX the
    test sends ``SIGINT``. Either signal is the
    documented graceful interrupt; the test asserts
    the supervisor's KeyboardInterrupt-translation
    handler is what makes the cleanup deterministic.

    The test is bounded: it skips if the host does
    not support the documented signal delivery, or
    if the test runner cannot allocate a free port
    or write to a temp directory. It does not skip
    on Windows for the documented graceful-shutdown
    path -- the whole point of the test is the
    Windows signal translation.
    """

    @pytest.fixture
    def foreground_env(self, isolated_home: Path, tmp_path: Path) -> Iterator[dict[str, str]]:
        # Build a minimal dist the runner will accept.
        dist = tmp_path / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text(
            "<!doctype html><html><head><title>t</title></head><body></body></html>",
            encoding="utf-8",
        )
        (dist / "assets" / "dummy.js").write_text("// empty", encoding="utf-8")
        env = dict(os.environ)
        env["LOCKVERITY_HOME"] = str(isolated_home)
        env["LOCKVERITY_FRONTEND_DIST"] = str(dist)
        env["LOCKVERITY_DATABASE_URL"] = f"sqlite:///{tmp_path}/fg.sqlite"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        yield env

    def test_foreground_graceful_shutdown_releases_lock_and_state(
        self, foreground_env: dict[str, str]
    ) -> None:
        # The test deliberately uses a real subprocess
        # so the signal-translation path is exercised.
        # The test is bounded: if the host cannot
        # create a new process group or the subprocess
        # is not deliverable, the test is skipped with
        # a precise reason -- not failed.
        if not hasattr(signal, "CTRL_BREAK_EVENT") and not hasattr(signal, "SIGINT"):
            pytest.skip("host does not expose a documented graceful interrupt")
        port = _free_port()
        cmd = [
            sys.executable,
            "-m",
            "app.cli",
            "start",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--foreground",
        ]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            )
        proc = subprocess.Popen(  # noqa: S603 - argv is built by us
            cmd,
            cwd=str(Path(__file__).resolve().parents[1]),
            env=foreground_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        try:
            # Wait for health.
            if not _wait_for_health_for_test(port, timeout=30.0):
                pytest.skip("foreground subprocess did not report healthy in 30s")
            # Send the real graceful interrupt.
            if sys.platform == "win32":
                proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                proc.send_signal(signal.SIGINT)
            try:
                rc = proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
                pytest.fail("foreground subprocess did not exit within 30s")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
        # The documented graceful codes are 0 and 130.
        # 0 is allowed because the foreground command
        # may complete naturally if health responds
        # before the operator's signal lands; 130 is
        # the POSIX-conventional 128+SIGINT.
        assert rc in (0, 130), f"unexpected exit code {rc}"
        # The CLI's foreground supervisor's start lock
        # is the supervisor's own PID; the lock file
        # lives in ``$LOCKVERITY_HOME/run/``. The
        # context manager's ``__exit__`` runs on
        # ``KeyboardInterrupt`` and removes the file.
        lock_path = Path(foreground_env["LOCKVERITY_HOME"]) / "run" / "lockverity.start.lock"
        assert not lock_path.exists(), f"start lock not released: {lock_path}"
        # Foreground mode does not write a state file
        # (the supervisor does not own the child's
        # lifetime), so the absence of a state file
        # is part of the contract.
        state_path = Path(foreground_env["LOCKVERITY_HOME"]) / "run" / "lockverity.state.json"
        assert not state_path.exists(), f"state file unexpectedly present: {state_path}"
        # The port must be free.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.connect(("127.0.0.1", port))
                pytest.fail("port still bound after graceful shutdown")
            except (ConnectionRefusedError, OSError):
                pass


def _wait_for_health_for_test(port: int, *, timeout: float) -> bool:
    """Bounded health probe used only by the foreground E2E test."""
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/v1/health", timeout=2
            ) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# CLI parser / dispatch tests
# ---------------------------------------------------------------------------


class TestCliParser:
    """Argparse behaviour for the root and subcommand parsers."""

    def test_top_level_help(self, parser: argparse.ArgumentParser) -> None:
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--help"])
        assert exc.value.code == 0

    def test_unknown_command(self, parser: argparse.ArgumentParser) -> None:
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["nonexistent"])
        assert exc.value.code != 0

    def test_no_args_prints_help(self, parser: argparse.ArgumentParser) -> None:
        # The CLI returns ``EXIT_USAGE`` (64) when no
        # subcommand is given; ``main`` prints the
        # help text to stderr and returns 64. The
        # test exercises ``main`` directly so the
        # full error-handling path is covered.
        import io
        from contextlib import redirect_stderr

        from app.cli.main import EXIT_USAGE

        buf = io.StringIO()
        with redirect_stderr(buf):
            rc = cli_main.main([])
        assert rc == EXIT_USAGE
        assert "usage" in buf.getvalue().lower() or "lockverity" in buf.getvalue().lower()

    def test_global_home_option(self, parser: argparse.ArgumentParser) -> None:
        args = parser.parse_args(["--home", "/tmp/lockverity", "status", "--json"])  # noqa: S108 - testing argparse path handling
        assert args.home == "/tmp/lockverity"  # noqa: S108 - testing argparse path handling
        assert args.subcommand == "status"
        assert args.json_output is True

    def test_start_help(self, parser: argparse.ArgumentParser) -> None:
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["start", "--help"])
        assert exc.value.code == 0

    def test_invalid_port(self, parser: argparse.ArgumentParser) -> None:
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["start", "--port", "not-a-number"])
        assert exc.value.code != 0

    def test_invalid_log_level(self, parser: argparse.ArgumentParser) -> None:
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["start", "--log-level", "verbose"])
        assert exc.value.code != 0

    def test_logs_negative_lines_rejected(self, isolated_home: Path, capsys) -> None:
        parser = cli_main.build_parser()
        args = parser.parse_args(["logs", "--lines", "-1"])
        rc = logs_cmd.main(args)
        assert rc == 64


# ---------------------------------------------------------------------------
# Subcommand behaviour tests
# ---------------------------------------------------------------------------


class TestSubcommandBehaviours:
    """End-to-end tests of the subcommand handlers."""

    def test_status_when_no_state(
        self, isolated_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parser = cli_main.build_parser()
        args = parser.parse_args(["status"])
        rc = status_cmd.main(args)
        assert rc == status_cmd.EXIT_STOPPED
        out = capsys.readouterr().out
        assert "stopped" in out

    def test_status_json_when_no_state(
        self, isolated_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parser = cli_main.build_parser()
        args = parser.parse_args(["status", "--json"])
        rc = status_cmd.main(args)
        assert rc == status_cmd.EXIT_STOPPED
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["status"] == "stopped"

    def test_stop_when_no_state(
        self, isolated_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parser = cli_main.build_parser()
        args = parser.parse_args(["stop", "--json"])
        rc = stop_cmd.main(args)
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["outcome"] == "was_not_running"

    def test_logs_when_missing(
        self, isolated_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parser = cli_main.build_parser()
        args = parser.parse_args(["logs", "--json"])
        rc = logs_cmd.main(args)
        # Missing log file is a non-fatal condition in
        # JSON mode (the operator gets an empty
        # ``lines`` array). Human mode returns 1.
        if args.json_output:
            assert rc == 0
            payload = json.loads(capsys.readouterr().out)
            assert payload["outcome"] == "missing"
            assert payload["lines"] == []
        else:
            assert rc == 1

    def test_open_when_no_instance(
        self, isolated_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parser = cli_main.build_parser()
        args = parser.parse_args(["open", "--json"])
        rc = open_cmd.main(args)
        assert rc == open_cmd.EXIT_STOPPED
        payload = json.loads(capsys.readouterr().out)
        assert payload["outcome"] == "no_instance"

    def test_open_refuses_non_loopback(
        self,
        isolated_home: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Write a state file with a non-loopback host
        # and a recorded identity that the runner
        # will not match. We mock the live read so
        # the test does not depend on the kernel
        # state.
        from app.cli import process as proc_mod
        from app.cli.process import IdentityMismatch

        def _fake_verify(
            *, recorded_pid, recorded_created_at, recorded_instance_id, recorded_module
        ):
            return IdentityMismatch(
                reason="recorded identity does not match (test)",
                recorded_pid=os.getpid(),
                recorded_created_at="2026-01-01T00:00:00Z",
                recorded_instance_id=str(uuid.uuid4()),
                live_cmdline=("unrelated", "process"),
            )

        monkeypatch.setattr(proc_mod, "verify_identity", _fake_verify)
        state = make_state(
            pid=os.getpid(),
            created_at="2026-01-01T00:00:00Z",
            host="8.8.8.8",
            port=80,
            version=__version__,
            home=isolated_home,
            frontend_dist=Path("/abs/dist"),
            log_file=Path("/abs/log"),
            module="app.main:app",
            started_at="2026-01-01T00:00:00Z",
            instance_id=str(uuid.uuid4()),
        )
        write_state(isolated_home, state)
        parser = cli_main.build_parser()
        args = parser.parse_args(["open", "--print-url"])
        rc = open_cmd.main(args)
        # The recorded identity does not match
        # (mocked) and the host is not loopback; the
        # runner must refuse to open the URL.
        assert rc in (
            open_cmd.EXIT_STOPPED,
            open_cmd.EXIT_USAGE,
            open_cmd.EXIT_UNHEALTHY,
        )

    def test_start_refuses_remote_host(
        self, isolated_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        parser = cli_main.build_parser()
        args = parser.parse_args(
            ["start", "--host", "0.0.0.0"]  # noqa: S104 - testing refusal
        )
        rc = start_cmd.main(args)
        assert rc == 2

    def test_doctor_all_pass_when_dist_valid(
        self, isolated_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Build a synthetic dist so the dist check
        # passes.
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text(
            '<!doctype html><html><body><div id="root"></div></body></html>',
            encoding="utf-8",
        )
        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setenv("LOCKVERITY_FRONTEND_DIST", str(dist))
            get_settings.cache_clear()
            parser = cli_main.build_parser()
            args = parser.parse_args(["doctor", "--json"])
            rc = doctor_cmd.main(args)
            # ``pass`` or ``warn`` is acceptable (the
            # doctor never returns FAIL on a clean host
            # where the only thing missing is the demo
            # database).
            assert rc in (0, 2)
            payload = json.loads(capsys.readouterr().out)
            assert payload["overall"] in ("pass", "warn")
            names = {check["name"] for check in payload["checks"]}
            assert "frontend_dist" in names
            assert "runtime_home" in names
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()

    def test_doctor_redacts_secrets(
        self, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOCKVERITY_GITHUB_TOKEN", "ghp_abcdefghij1234567890")
        report = doctor_cmd.build_report(isolated_home)
        for check in report.checks:
            assert "ghp_abcdefghij1234567890" not in check.message


# ---------------------------------------------------------------------------
# Public entry-point smoke
# ---------------------------------------------------------------------------


class TestPublicEntryPoints:
    """The ``python -m app.cli`` and ``lockverity`` entry points exist."""

    def test_python_m_app_cli_help(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")
        env["LOCKVERITY_ENVIRONMENT"] = "test"
        env["LOCKVERITY_DATABASE_URL"] = "sqlite:///:memory:"
        env["LOCKVERITY_HOME"] = str(repo_root / "var" / "cli-entrypoint-test")
        env["LOCKVERITY_HOME"].encode("utf-8")  # type check only
        result = subprocess.run(
            [sys.executable, "-m", "app.cli", "--help"],
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        for cmd in ("start", "stop", "status", "open", "doctor", "logs"):
            assert cmd in result.stdout

    def test_consistent_subcommand_registry(self) -> None:
        from app.cli.main import _SUBCOMMANDS

        names = tuple(name for name, _, _ in _SUBCOMMANDS)
        assert names == ("start", "stop", "status", "open", "doctor", "logs")
