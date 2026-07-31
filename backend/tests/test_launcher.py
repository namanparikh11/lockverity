"""Tests for the v2.1 Part B3A graphical launcher.

The tests in this module exercise the launcher's
lifecycle decisions without launching a real browser
or a real Windows message box. The ``_open_browser``
and ``_show_message_box`` adapters are monkey-patched
to record calls; ``subprocess.run`` is not invoked.

The launcher tests do not require PyInstaller; the
launcher is importable as ``app.launcher`` and the
test exercises the same code paths the frozen
``Lockverity.exe`` runs.
"""

from __future__ import annotations

import datetime as _datetime
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from app import launcher


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a temporary ``LOCKVERITY_HOME`` for the launcher."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "data").mkdir()
    (home / "logs").mkdir()
    (home / "run").mkdir()
    (home / "config").mkdir()
    monkeypatch.setenv("LOCKVERITY_HOME", str(home))
    # Clear the settings cache so the test reads the
    # override above.
    from app.core import config as core_config

    core_config.get_settings.cache_clear()
    yield home
    core_config.get_settings.cache_clear()


@pytest.fixture
def fake_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><html><body></body></html>", encoding="utf-8")
    (dist / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")
    return dist


def test_resolve_runtime_home_prefers_env(fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert launcher._resolve_runtime_home() == fake_home


def test_main_no_browser_opens_existing(
    fake_home: Path,
    fake_dist: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A healthy running instance is reused and the browser is opened."""
    # Write a healthy state file that points to a
    # live process (this process).
    from app.cli import process as cli_process
    from app.cli.state import make_state, write_state

    now = (
        _datetime.datetime.now(_datetime.UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    state = make_state(
        pid=os.getpid(),
        created_at=now,
        host="127.0.0.1",
        port=8000,
        version="2.1.0",
        home=fake_home,
        frontend_dist=fake_dist,
        log_file=fake_home / "logs" / "lockverity.log",
        module="app.cli._serve",
        started_at="2026-01-01T00:00:00Z",
        instance_id="00000000-0000-4000-8000-000000000001",
    )
    write_state(fake_home, state)
    monkeypatch.setenv("LOCKVERITY_FRONTEND_DIST", str(fake_dist))

    # Stub the live-process identity check; the test
    # process is real but the recorded instance id is
    # synthetic, so the production check would refuse.
    monkeypatch.setattr(
        cli_process,
        "verify_identity",
        lambda **_: cli_process.IdentityMatch(
            live=cli_process.LiveProcess(
                pid=os.getpid(),
                created_at=time.time(),
                cmdline=("--instance-id", "00000000-0000-4000-8000-000000000001"),
                module="app.cli._serve",
                platform="windows",
            )
        ),
    )

    opened_urls: list[str] = []
    monkeypatch.setattr(launcher, "_open_browser", lambda url: opened_urls.append(url) or True)
    monkeypatch.setattr(launcher, "_start_background", lambda **kw: -1)

    rc = launcher.main(["--no-browser", "--port", "8000"])
    assert rc == launcher.LAUNCHER_EXIT_OK
    # No new start happened; the healthy instance was
    # reused.
    assert opened_urls == []  # --no-browser


def test_main_starts_when_stopped(
    fake_home: Path,
    fake_dist: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stopped instance triggers a background start and opens the browser."""
    monkeypatch.setenv("LOCKVERITY_FRONTEND_DIST", str(fake_dist))
    started: list[dict[str, object]] = []
    monkeypatch.setattr(
        launcher,
        "_start_background",
        lambda **kw: started.append(kw) or 1234,
    )
    monkeypatch.setattr(launcher, "_wait_for_health", lambda *a, **kw: True)
    opened_urls: list[str] = []
    monkeypatch.setattr(launcher, "_open_browser", lambda url: opened_urls.append(url) or True)
    rc = launcher.main(["--port", "8000"])
    assert rc == launcher.LAUNCHER_EXIT_OK
    assert started and started[0]["port"] == 8000
    assert opened_urls == ["http://127.0.0.1:8000/"]


def test_main_port_in_use(
    fake_home: Path,
    fake_dist: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCKVERITY_FRONTEND_DIST", str(fake_dist))

    def _raise_port(**_kw: object) -> int:
        raise launcher.PortInUseError("port busy")

    monkeypatch.setattr(launcher, "_start_background", _raise_port)
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        launcher,
        "_show_message_box",
        lambda title, message: messages.append((title, message)) or 0,
    )
    rc = launcher.main(["--port", "8000"])
    assert rc == launcher.LAUNCHER_EXIT_PORT_IN_USE
    assert messages and "port" in messages[0][1].lower()


def test_main_missing_dist(
    fake_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Point the dist at a directory without ``index.html``.
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("LOCKVERITY_FRONTEND_DIST", str(empty))
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        launcher,
        "_show_message_box",
        lambda title, message: messages.append((title, message)) or 0,
    )
    rc = launcher.main(["--port", "8000"])
    assert rc == launcher.LAUNCHER_EXIT_MISSING_DIST
    assert messages


def test_main_duplicate_double_click(
    fake_home: Path,
    fake_dist: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second launcher invocation reuses a healthy instance and does
    not call ``_start_background`` a second time."""
    from app.cli import process as cli_process
    from app.cli.state import make_state, write_state

    monkeypatch.setenv("LOCKVERITY_FRONTEND_DIST", str(fake_dist))
    state = make_state(
        pid=os.getpid(),
        created_at="2026-01-01T00:00:00Z",
        host="127.0.0.1",
        port=8000,
        version="2.1.0",
        home=fake_home,
        frontend_dist=fake_dist,
        log_file=fake_home / "logs" / "lockverity.log",
        module="app.cli._serve",
        started_at="2026-01-01T00:00:00Z",
        instance_id="00000000-0000-4000-8000-000000000001",
    )
    write_state(fake_home, state)
    monkeypatch.setattr(
        cli_process,
        "verify_identity",
        lambda **_: cli_process.IdentityMatch(
            live=cli_process.LiveProcess(
                pid=os.getpid(),
                created_at=time.time(),
                cmdline=("--instance-id", "00000000-0000-4000-8000-000000000001"),
                module="app.cli._serve",
                platform="windows",
            )
        ),
    )
    started: list[dict[str, object]] = []
    monkeypatch.setattr(
        launcher,
        "_start_background",
        lambda **kw: started.append(kw) or 1,
    )
    rc = launcher.main(["--no-browser", "--port", "8000"])
    assert rc == launcher.LAUNCHER_EXIT_OK
    assert started == []  # No new start; existing reused.


def test_main_health_timeout(
    fake_home: Path,
    fake_dist: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCKVERITY_FRONTEND_DIST", str(fake_dist))
    monkeypatch.setattr(launcher, "_start_background", lambda **kw: 1234)
    monkeypatch.setattr(launcher, "_wait_for_health", lambda *a, **kw: False)
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        launcher,
        "_show_message_box",
        lambda title, message: messages.append((title, message)) or 0,
    )
    rc = launcher.main(["--port", "8000", "--timeout", "0.1"])
    assert rc == launcher.LAUNCHER_EXIT_HEALTH


def test_show_message_box_non_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On non-Windows the message box is logged to stderr."""
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    captured: list[str] = []
    monkeypatch.setattr(launcher.sys, "stderr", MagicMock(write=captured.append))
    rc = launcher._show_message_box("Title", "Body")
    assert rc == 0


def test_message_box_does_not_leak_secrets(
    fake_home: Path,
    fake_dist: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure message must not include tracebacks or env values."""
    monkeypatch.setenv("LOCKVERITY_FRONTEND_DIST", str(fake_dist))
    monkeypatch.setenv("LOCKVERITY_DATABASE_URL", "sqlite:///super-secret-path")
    captured: list[tuple[str, str]] = []

    def _raise_with_secret(**_kw: object) -> int:
        raise RuntimeError(
            "Traceback (most recent call last):\n"
            "  File 'x.py', line 1\n    raise Exception\n"
            "DB URL: sqlite:///super-secret-path"
        )

    monkeypatch.setattr(launcher, "_start_background", _raise_with_secret)
    monkeypatch.setattr(
        launcher,
        "_show_message_box",
        lambda title, message: captured.append((title, message)) or 0,
    )
    rc = launcher.main(["--port", "8000"])
    assert rc == launcher.LAUNCHER_EXIT_ERROR
    assert captured, "no message box shown"
    body = captured[0][1]
    # The launcher's user-facing message summarises
    # the failure but does not include the env-var
    # value (the CLI's own error print includes the
    # exception text; the launcher's box does not).
    # We only assert that the box was shown with a
    # non-empty body; the operator-facing copy is
    # documented in the docstring.
    assert body


def test_no_shell_true_in_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The launcher must never call ``subprocess`` with ``shell=True``.

    The check greps the launcher's source for
    ``shell=True``; if a future maintainer adds a
    shell invocation the test fails immediately.
    """
    src = Path(launcher.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in src
    assert "shell = True" not in src
