"""B3B Windows installer acceptance test.

Drives the compiled ``Lockverity-2.1.0-windows-x64-setup.exe``
through the full per-user installer acceptance workflow from
the v2.1 Part B3B spec:

  1. Silent install into a path containing spaces and Unicode.
  2. Installed application smoke (health, status, logs, stop).
  3. Restricted-PATH execution (no system Python/Node/npm).
  4. Reinstall while the application is running.
  5. Uninstall while the application is running.
  6. Runtime-data preservation.
  7. Per-user uninstall registry review.
  8. Start Menu and desktop shortcut review.

The script uses temporary per-test runtime homes so no
production user data is touched. The script never deletes
runtime data; the optional cleanup is opt-in via
``--cleanup``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
DEFAULT_INSTALLER = REPO_ROOT / "build" / "installer" / "Lockverity-2.1.0-windows-x64-setup.exe"
DEFAULT_INSTALL_DIR = Path(r"C:\Temp\Lockverity B3B Unicode Ω\Lockverity")
DEFAULT_RUNTIME_HOME = Path(r"C:\Temp\Lockverity B3B Unicode Ω\Home")
DEFAULT_LOG_DIR = REPO_ROOT / "build" / "installer" / "logs"
EXPECTED_LOCKVERITY_EXE_SHA256 = "7b8e5363e64f58e8a9ed705db8f941495c55ccff430ac19a7e32f9e55a9701c7"
EXPECTED_LOCKVERITY_CLI_EXE_SHA256 = (
    "9942cbc9018a1905ac25139ff6b632bcaca1881fbb5f441606053430a68bca51"
)


def _sha256_of(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_responsive(url: str, timeout: float = 2.0) -> bool:
    try:
        # Only the loopback ``http://127.0.0.1:PORT/...`` URL is
        # ever passed in; the smoke test polls the locally
        # running Lockverity server. The URL is not user input.
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _restricted_env(home_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["LOCKVERITY_HOME"] = str(home_dir)
    env["PATH"] = r"C:\Windows\System32;C:\Windows"
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def step_silent_install(installer: Path, install_dir: Path, log: Path) -> dict[str, object]:
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(installer),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        f"/DIR={install_dir}",
        f"/LOG={log}",
    ]
    result = subprocess.run(  # noqa: S603 - argv is built by us
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600
    )
    return {
        "step": "silent_install",
        "install_dir": str(install_dir),
        "rc": result.returncode,
        "log_tail": (log.read_text(encoding="utf-8", errors="replace") if log.is_file() else "")[
            -2000:
        ],
        "stdout_tail": (result.stdout or "")[-1000:],
        "stderr_tail": (result.stderr or "")[-1000:],
    }


def step_verify_installed_payload(install_dir: Path) -> dict[str, object]:
    installed_exe = install_dir / "app" / "Lockverity.exe"
    installed_cli = install_dir / "app" / "lockverity-cli.exe"
    if not installed_exe.is_file():
        return {"step": "verify_installed_payload", "ok": False, "reason": "missing Lockverity.exe"}
    if not installed_cli.is_file():
        return {
            "step": "verify_installed_payload",
            "ok": False,
            "reason": "missing lockverity-cli.exe",
        }
    exe_sha = _sha256_of(installed_exe)
    cli_sha = _sha256_of(installed_cli)
    return {
        "step": "verify_installed_payload",
        "ok": exe_sha == EXPECTED_LOCKVERITY_EXE_SHA256
        and cli_sha == EXPECTED_LOCKVERITY_CLI_EXE_SHA256,
        "Lockverity.exe_sha256": exe_sha,
        "expected_Lockverity.exe_sha256": EXPECTED_LOCKVERITY_EXE_SHA256,
        "lockverity-cli.exe_sha256": cli_sha,
        "expected_lockverity-cli.exe_sha256": EXPECTED_LOCKVERITY_CLI_EXE_SHA256,
    }


def step_smoke(install_dir: Path, home_dir: Path, port: int, log: Path) -> dict[str, object]:
    installed_cli = install_dir / "app" / "lockverity-cli.exe"
    env = _restricted_env(home_dir)
    # The CLI is started with the install dir as the
    # caller's CWD on purpose: the v2.1 Part B3B
    # release-blocker regression test verifies the
    # default database URL is **CWD-independent** --
    # a relative ``sqlite:///./lockverity.sqlite`` URL
    # would resolve under the install dir; the fixed
    # default (resolved under the runtime home) must
    # not. The CLI's own CWD must be the install dir
    # to mirror the documented
    # "double-click ``Lockverity.exe`` from the Start
    # Menu" launch path, where Windows gives the
    # launcher / CLI a per-user CWD that is *not* the
    # install dir.
    start_proc = subprocess.Popen(  # noqa: S603 - argv is built by us
        [str(installed_cli), "start", "--port", str(port)],
        env=env,
        stdout=open(log, "wb"),  # noqa: SIM115 - opened once, closed by Popen
        stderr=subprocess.STDOUT,
        cwd=str(install_dir),
    )
    health_ok = False
    for _ in range(40):
        time.sleep(1.0)
        if _is_responsive(f"http://127.0.0.1:{port}/api/v1/health"):
            health_ok = True
            break
    # Snapshot the install dir and the runtime home so
    # the test can prove the SQLite database landed
    # under ``home/data/`` and *not* under the install
    # dir. The list of ``*.sqlite`` files is the
    # canonical evidence: the install dir must contain
    # zero of them; the runtime home must contain
    # exactly one. (The runtime home may also have
    # WAL / SHM sidecars; we only count the main
    # ``lockverity.sqlite`` file here.)
    install_dir_sqlite = [str(p) for p in install_dir.rglob("*.sqlite")]
    home_dir_sqlite = (
        sorted(str(p) for p in (home_dir / "data").glob("*.sqlite"))
        if (home_dir / "data").is_dir()
        else []
    )
    # Query status
    status_result = subprocess.run(  # noqa: S603 - argv is built by us
        [str(installed_cli), "status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    # Stop
    stop_result = subprocess.run(  # noqa: S603 - argv is built by us
        [str(installed_cli), "stop"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    try:
        start_proc.wait(timeout=10)
    except Exception:
        start_proc.kill()
    return {
        "step": "smoke",
        "port": port,
        "health_ok": health_ok,
        "status_rc": status_result.returncode,
        "status_stdout_tail": (status_result.stdout or "")[-1000:],
        "stop_rc": stop_result.returncode,
        "stop_stdout_tail": (stop_result.stdout or "")[-500:],
        # CWD-independence evidence.
        "install_dir_sqlite_files": install_dir_sqlite,
        "home_dir_sqlite_files": home_dir_sqlite,
        "database_under_home": bool(home_dir_sqlite),
        "no_database_under_install_dir": not bool(install_dir_sqlite),
    }


def step_uninstall(install_dir: Path, home_dir: Path, log: Path) -> dict[str, object]:
    """Run the actual Inno Setup-generated uninstaller.

    The Inno Setup installer EXE is *also* the uninstaller when
    run with the right switches (``/uninstall`` was deprecated;
    the modern way is to run ``unins000.exe`` directly with
    ``/VERYSILENT``). Running the installer EXE again just
    reinstalls, so we have to drive the per-install
    ``unins000.exe`` instead. The per-user uninstall registry
    entry points at this exact file.

    The test home is passed via ``LOCKVERITY_HOME`` so the
    uninstaller's [Code] section can find the live state
    file (which the test created with the same home) and
    drive the identity-verified Part B2 graceful stop before
    file deletion. The default ``{localappdata}\\Lockverity``
    is the production default; tests that override the home
    must propagate the same override to the uninstaller.
    """
    uninstaller = install_dir / "unins000.exe"
    if not uninstaller.is_file():
        return {
            "step": "uninstall",
            "ok": False,
            "reason": f"uninstaller not found: {uninstaller}",
        }
    env = os.environ.copy()
    env["LOCKVERITY_HOME"] = str(home_dir)
    cmd = [
        str(uninstaller),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        f"/LOG={log}",
    ]
    result = subprocess.run(  # noqa: S603 - argv is built by us
        cmd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    return {
        "step": "uninstall",
        "uninstaller": str(uninstaller),
        "rc": result.returncode,
        "log_tail": (log.read_text(encoding="utf-8", errors="replace") if log.is_file() else "")[
            -2000:
        ],
    }


def step_reinstall_while_running(
    installer: Path, install_dir: Path, home_dir: Path, port: int, log: Path
) -> dict[str, object]:
    installed_cli = install_dir / "app" / "lockverity-cli.exe"
    env = _restricted_env(home_dir)
    # Start the installed app
    start_proc = subprocess.Popen(  # noqa: S603 - argv is built by us
        [str(installed_cli), "start", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(install_dir / "app"),
    )
    health_ok = False
    for _ in range(40):
        time.sleep(1.0)
        if _is_responsive(f"http://127.0.0.1:{port}/api/v1/health"):
            health_ok = True
            break
    # Now run the installer again (reinstall). The Pascal [Code]
    # in the .iss detects the running instance via AppMutex and
    # requests a graceful stop before file replacement. We do
    # *not* pass ``/CLOSEAPPS`` because Inno Setup's RestartManager
    # does not handle the detached ``Lockverity.exe`` server
    # reliably (the server is a detached child of the
    # ``lockverity-cli.exe`` wrapper, and RestartManager walks
    # the handle table from the installer process up — the
    # detached server is not in the installer's handle table).
    # The canonical B3B flow is the [Code]'s ``PrepareToInstall``
    # hook which calls the installed ``lockverity-cli.exe stop``
    # (Part B2 identity-verified). In silent mode the [Code]
    # does not show a MsgBox; the operator would see the same
    # flow in wizard mode with a Retry/Cancel prompt.
    cmd = [
        str(installer),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        f"/DIR={install_dir}",
        f"/LOG={log}",
    ]
    reinstall_result = subprocess.run(  # noqa: S603 - argv is built by us
        cmd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    # Wait for process to exit (the AppMutex-detected graceful
    # stop should have made it exit).
    try:
        start_proc.wait(timeout=30)
    except Exception:
        start_proc.kill()
    # Verify the reinstalled CLI still works
    recheck = subprocess.run(  # noqa: S603 - argv is built by us
        [str(installed_cli), "--version"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    return {
        "step": "reinstall_while_running",
        "health_ok_before_reinstall": health_ok,
        "reinstall_rc": reinstall_result.returncode,
        "reinstall_log_tail": (
            log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        )[-2000:],
        "recheck_version_rc": recheck.returncode,
        "recheck_version_stdout": (recheck.stdout or "")[-500:],
    }


def step_uninstall_while_running(
    install_dir: Path, home_dir: Path, port: int, log: Path
) -> dict[str, object]:
    installed_cli = install_dir / "app" / "lockverity-cli.exe"
    env = _restricted_env(home_dir)
    start_proc = subprocess.Popen(  # noqa: S603 - argv is built by us
        [str(installed_cli), "start", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(install_dir / "app"),
    )
    health_ok = False
    for _ in range(40):
        time.sleep(1.0)
        if _is_responsive(f"http://127.0.0.1:{port}/api/v1/health"):
            health_ok = True
            break
    # The .iss's [Code] section handles uninstall-while-running
    # via the ``CurUninstallStepChanged`` event: at the
    # ``usUninstall`` step the Pascal code calls the installed
    # ``lockverity-cli.exe`` identity-verified ``stop`` (Part
    # B2) via the AppMutex detection, then the rest of the
    # uninstall proceeds. The actual uninstaller we invoke is
    # the per-install ``unins000.exe``, not the installer EXE.
    # The test's ``LOCKVERITY_HOME`` is forwarded so the [Code]
    # can locate the live state file.
    uninstaller = install_dir / "unins000.exe"
    env = os.environ.copy()
    env["LOCKVERITY_HOME"] = str(home_dir)
    cmd = [
        str(uninstaller),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        f"/LOG={log}",
    ]
    uninstall_result = subprocess.run(  # noqa: S603 - argv is built by us
        cmd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    try:
        start_proc.wait(timeout=30)
    except Exception:
        start_proc.kill()
    return {
        "step": "uninstall_while_running",
        "health_ok_before_uninstall": health_ok,
        "uninstall_rc": uninstall_result.returncode,
        "uninstall_log_tail": (
            log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        )[-2000:],
    }


def step_registry_review() -> dict[str, object]:
    """Inspect the per-user uninstall registry for Lockverity entries."""
    import subprocess

    cmd = ["reg", "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall", "/s"]
    proc = subprocess.run(  # noqa: S603 - argv is built by us
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
    )
    in_lockverity_block = False
    found_block: list[str] = []
    for line in proc.stdout.splitlines():
        if "Lockverity" in line:
            in_lockverity_block = True
            found_block.append(line.strip())
        elif in_lockverity_block:
            if line.strip() == "":
                in_lockverity_block = False
            else:
                found_block.append(line.strip())
    return {
        "step": "registry_review",
        "lockverity_block_lines": found_block[:50],
    }


def step_shortcut_review(install_dir: Path) -> dict[str, object]:
    """Inspect the Start Menu and desktop shortcut files.

    The .iss declares ``DefaultGroupName={#MyAppDisplayName}``
    (== ``Lockverity``) and keeps
    ``DisableProgramGroupPage=yes`` so the shortcuts land in
    ``Programs\\Lockverity\\`` -- a coherent per-app folder
    -- rather than the legacy ``Programs\\(Default)\\`` which
    was a literal Inno Setup convention for the user's
    default Programs folder. The function inspects both
    the per-app folder and the legacy default folder so the
    test is robust against a future installer that flips
    the group name back to the default.
    """
    start_menu_root = (
        Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    )
    desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
    start_menu_files: list[str] = []
    for sub in (
        start_menu_root / "Lockverity",
        start_menu_root / "(Default)",
        start_menu_root,
    ):
        if sub.is_dir():
            for p in sub.glob("Lockverity*"):
                if p.is_file():
                    start_menu_files.append(str(p.relative_to(start_menu_root)))
            for p in sub.glob("Uninstall Lockverity*"):
                if p.is_file():
                    start_menu_files.append(str(p.relative_to(start_menu_root)))
    return {
        "step": "shortcut_review",
        "start_menu_files": start_menu_files,
        "desktop_files": [str(p) for p in desktop.glob("Lockverity*")] if desktop.is_dir() else [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="b3b_acceptance")
    parser.add_argument("--installer", type=Path, default=DEFAULT_INSTALLER)
    parser.add_argument("--install-dir", type=Path, default=DEFAULT_INSTALL_DIR)
    parser.add_argument("--home-dir", type=Path, default=DEFAULT_RUNTIME_HOME)
    parser.add_argument("--port", type=int, default=18780)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args(argv)

    log_dir = args.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    # Make sure the install dir is clean
    if args.install_dir.exists():
        shutil.rmtree(args.install_dir, ignore_errors=True)
    args.install_dir.parent.mkdir(parents=True, exist_ok=True)

    steps: list[dict[str, object]] = []

    # Step 1: silent install
    steps.append(
        step_silent_install(args.installer, args.install_dir, log_dir / "b3b-step1-install.log")
    )

    # Step 2: verify installed payload
    steps.append(step_verify_installed_payload(args.install_dir))

    # Step 3: smoke
    steps.append(
        step_smoke(args.install_dir, args.home_dir, args.port, log_dir / "b3b-step3-smoke.log")
    )

    # Step 4: registry review
    steps.append(step_registry_review())

    # Step 5: shortcut review
    steps.append(step_shortcut_review(args.install_dir))

    # Step 6: uninstall (with running) — first we have to start
    # the app, then uninstall, then verify
    port2 = args.port + 1 if _port_free(args.port + 1) else args.port
    steps.append(
        step_uninstall_while_running(
            args.install_dir,
            args.home_dir,
            port2,
            log_dir / "b3b-step6-uninstall-running.log",
        )
    )

    # Step 7: reinstall while running. The uninstall at the end of
    # step 6 leaves the install dir with a runtime ``lockverity.sqlite``
    # file but no installed binaries, so we re-install first to set
    # up the reinstall-while-running test. The trigger is the absence
    # of the lockverity-cli.exe, not just the install dir existence
    # (Inno Setup's ``Deleting directory (145)`` aftereffects leave
    # the install dir itself in place for the test runtime).
    prep_steps: list[dict[str, object]] = []
    if not (args.install_dir / "app" / "lockverity-cli.exe").is_file():
        prep_step = step_silent_install(
            args.installer, args.install_dir, log_dir / "b3b-step7-reinstall-prep.log"
        )
        prep_steps.append(prep_step)
        steps.append({"step": "reinstall_prep", "rc": prep_step.get("rc")})
    port3 = args.port + 2 if _port_free(args.port + 2) else args.port
    steps.append(
        step_reinstall_while_running(
            args.installer,
            args.install_dir,
            args.home_dir,
            port3,
            log_dir / "b3b-step7-reinstall-running.log",
        )
    )

    # Step 8: uninstall (final cleanup)
    steps.append(
        step_uninstall(
            args.install_dir,
            args.home_dir,
            log_dir / "b3b-step8-uninstall-final.log",
        )
    )

    # Step 9: verify install dir removed. The Inno
    # Setup uninstaller renames ``unins000.exe`` to a
    # hidden name (``_unin*.tmp``) and the renamed
    # file deletes itself at the very end of the
    # uninstall. On a busy host (anti-virus scanning
    # the file, or a still-closing child Lockverity
    # process) the self-delete can take a few
    # seconds. We wait for the install dir to disappear
    # (the install dir cannot exist if the uninstaller
    # renamed itself, ran the file-deletion phase, and
    # self-deleted) up to a bounded timeout, then record
    # the result. A failure here means a manual operator
    # step would be required to clean up -- the test
    # reports it as ``install_dir_removed_after_wait=False``
    # instead of claiming success.
    _uninst_deadline = time.monotonic() + 30.0
    install_dir_after = args.install_dir.is_dir()
    while install_dir_after and time.monotonic() < _uninst_deadline:
        time.sleep(0.5)
        install_dir_after = args.install_dir.is_dir()
    install_dir_files = list(args.install_dir.glob("**/*"))[:20] if install_dir_after else []
    steps.append(
        {
            "step": "post_uninstall_install_dir_state",
            "install_dir_exists": install_dir_after,
            "install_dir_removed_after_wait": not install_dir_after,
            "install_dir_files": [str(p) for p in install_dir_files],
        }
    )

    # Step 10: runtime home preservation
    home_after = args.home_dir.is_dir()
    home_files = list(args.home_dir.glob("**/*"))[:20] if home_after else []
    home_dir_sqlite = (
        sorted(str(p) for p in (args.home_dir / "data").glob("*.sqlite"))
        if (args.home_dir / "data").is_dir()
        else []
    )
    home_dir_logs = (
        sorted(str(p) for p in (args.home_dir / "logs").glob("*.log"))
        if (args.home_dir / "logs").is_dir()
        else []
    )
    home_dir_state = (
        sorted(str(p) for p in (args.home_dir / "run").glob("*.json"))
        if (args.home_dir / "run").is_dir()
        else []
    )
    steps.append(
        {
            "step": "runtime_home_preservation",
            "home_dir_exists": home_after,
            "home_files_sample": [str(p) for p in home_files],
            "home_dir_data_sqlite": home_dir_sqlite,
            "home_dir_logs": home_dir_logs,
            "home_dir_state_files": home_dir_state,
            "database_preserved_in_home": bool(home_dir_sqlite),
        }
    )

    # Final registry review
    steps.append(step_registry_review())

    # Final shortcut review
    steps.append(step_shortcut_review(args.install_dir))

    if args.cleanup:
        # Only clean the install dir (NOT the home dir)
        shutil.rmtree(args.install_dir, ignore_errors=True)
        steps.append(
            {"step": "cleanup", "cleaned": str(args.install_dir), "preserved": str(args.home_dir)}
        )

    print(
        json.dumps(
            {
                "installer": str(args.installer),
                "install_dir": str(args.install_dir),
                "home_dir": str(args.home_dir),
                "port": args.port,
                "steps": steps,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
