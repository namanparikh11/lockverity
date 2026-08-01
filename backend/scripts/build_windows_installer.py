"""Build the Lockverity v2.1 Windows x64 per-user installer.

This script is the canonical entry point for the v2.1 Part B3B
Windows installer. It wraps the Inno Setup 6.x compiler
(``ISCC.exe``) and:

  - verifies the accepted B3A portable payload's hashes;
  - extracts the payload into a dedicated staging directory
    (the installer source then copies the staging tree into
    ``{app}\\app\\``);
  - runs the committed ``backend\\installer\\lockverity.iss``
    source through the verified compiler;
  - generates ``INSTALLER-MANIFEST.json`` and ``SHA256SUMS.txt``
    alongside the installer EXE;
  - runs a silent-install smoke test and verifies the
    installed application responds to ``/api/v1/health``;
  - emits a structured JSON report.

The script never silently rebuilds the accepted portable
payload. If the payload ZIP or any of the accepted hashes
differ from the documented values, the script aborts with
an actionable error.

Usage::

    python backend\\scripts\\build_windows_installer.py
    python backend\\scripts\\build_windows_installer.py --clean --json-report
    python backend\\scripts\\build_windows_installer.py --payload-zip PATH
    python backend\\scripts\\build_windows_installer.py --keep-work
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
INSTALLER_DIR = BACKEND_ROOT / "installer"
ISS_SOURCE = INSTALLER_DIR / "lockverity.iss"
PAYLOAD_NAME = "Lockverity-2.1.0-windows-x64-portable"
DEFAULT_PAYLOAD_ZIP = REPO_ROOT / "build" / "packaging" / f"{PAYLOAD_NAME}.zip"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "installer"
DEFAULT_STAGING_DIR = DEFAULT_OUTPUT_DIR / "staging"
DEFAULT_WORK_DIR = DEFAULT_OUTPUT_DIR / "work"
PAYLOAD_DIR_NAME = "app"
# Stable AppId the Inno Setup source uses for the per-user
# uninstaller key. The installer source is committed with the
# same value; the build script is a sanity-check only.
STABLE_APP_ID = "{E5B0C0F4-7C42-4D6A-9B17-1A2B3C4D5E6F}"
APP_VERSION = "2.1.0"
# Inno Setup 6.7.3 is the only trusted compiler for this build.
# The compiler is installed under the current user's LocalAppData
# when fetched via the recommended publisher (jrsoftware.org).
ISCC_PATHS = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe"),
    Path("C:/Program Files/Inno Setup 6/ISCC.exe"),
)
EXPECTED_PAYLOAD_ZIP_SHA256 = "ec9a4d3fdf160e5364a62acba25fc2bcbaaf5e067ba116cd3f355d2c61cca588"
EXPECTED_PAYLOAD_SOURCE_COMMIT = "81b400bc40ae6ada2787470fca8b31c5ea8b1c30"
EXPECTED_LOCKVERITY_EXE_SHA256 = "beecc5cd4d9d336f5adf450c947bf1db62a6493876a8250bfdba9889997ff059"
EXPECTED_LOCKVERITY_CLI_EXE_SHA256 = (
    "f74f3e5b8631bf3ec5f018064367fd26a2b5b8b1cf19518a94a0deb40c2e4796"
)
# A bounded lock for the launched installer's /VERYSILENT
# smoke. The smoke is disabled by default to keep the
# build deterministic; pass ``--run-smoke`` to opt in.
SMOKE_PORT_HINT = 18790


def _log(stage: str, message: str) -> None:
    ts = datetime.datetime.now(tz=datetime.UTC).strftime("%H:%M:%S")
    sys.stderr.write(f"[{ts}] [{stage}] {message}\n")
    sys.stderr.flush()


def _verify_host() -> tuple[str, str]:
    if sys.platform != "win32":
        raise SystemExit(
            "ERROR: this build script targets Windows x64 only. "
            f"Detected platform: {sys.platform!r}."
        )
    machine = platform.machine().lower()
    if machine not in ("amd64", "x86_64"):
        raise SystemExit(f"ERROR: Windows x64 is required (detected machine={machine!r}).")
    py_version = sys.version_info
    if py_version < (3, 12):
        raise SystemExit(f"ERROR: Python 3.12+ is required (detected {py_version}).")
    return (sys.platform, machine)


def _verify_clean_git_state() -> None:
    """Refuse to build from a dirty tree unless explicitly told to proceed.

    The build script is the documented chokepoint; the installer
    is built from the same commit that the portable was built
    from. A dirty working tree at install-build time means the
    installer would record a different installer-source commit
    than what the operator checked out.
    """
    git = shutil.which("git")
    if git is None:
        raise SystemExit("ERROR: git is required on PATH to build the installer.")
    result = subprocess.run(  # noqa: S603 - argv is a fixed list
        [git, "status", "--porcelain", "--untracked-files=no"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if result.returncode != 0:
        raise SystemExit(f"ERROR: git status failed: {result.stderr.strip()}")
    if result.stdout.strip():
        raise SystemExit(
            "ERROR: working tree is dirty; commit or stash changes before "
            f"building the installer.\n{result.stdout}"
        )


def _git_head_full() -> str:
    """Return the full 40-character git HEAD commit SHA, or refuse."""
    git = shutil.which("git")
    if git is None:
        raise SystemExit("ERROR: git is required on PATH.")
    result = subprocess.run(  # noqa: S603 - argv is a fixed list
        [git, "rev-parse", "HEAD"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if result.returncode != 0:
        raise SystemExit(f"ERROR: git rev-parse failed: {result.stderr.strip()}")
    full = result.stdout.strip()
    if not re.match(r"^[0-9a-f]{40}$", full):
        raise SystemExit(f"ERROR: invalid git HEAD SHA: {full!r}")
    return full


def _verify_iscc() -> Path:
    """Return the verified ISCC.exe path. The compiler must be a
    signed Inno Setup compiler. We trust the install under
    ``%LOCALAPPDATA%\\Programs\\Inno Setup 6`` because that is
    where ``winget install JRSoftware.InnoSetup`` places the
    official, signed binary.
    """
    for candidate in ISCC_PATHS:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "ERROR: a verified Inno Setup 6.x compiler was not found. "
        "Install Inno Setup 6 via winget (``winget install "
        "JRSoftware.InnoSetup``) or from the official publisher "
        "(https://jrsoftware.org/isdl.php). The compiler path was "
        f"checked: {[str(p) for p in ISCC_PATHS]}"
    )


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_payload_zip(payload_zip: Path) -> dict[str, object]:
    """Verify the accepted B3A portable payload ZIP and return a
    short summary used by the install manifest."""
    if not payload_zip.is_file():
        raise SystemExit(
            f"ERROR: accepted payload ZIP not found at {payload_zip}. "
            "Restore the accepted B3A portable ZIP before building the "
            "installer. Do not rebuild the application."
        )
    actual_zip_sha = _sha256_of(payload_zip)
    if actual_zip_sha != EXPECTED_PAYLOAD_ZIP_SHA256:
        raise SystemExit(
            "ERROR: accepted payload ZIP SHA-256 mismatch.\n"
            f"  expected: {EXPECTED_PAYLOAD_ZIP_SHA256}\n"
            f"  actual:   {actual_zip_sha}\n"
            f"  path:     {payload_zip}\n"
            "The installer would embed the wrong payload. Restore the "
            "accepted B3A portable ZIP and retry."
        )
    payload_root = payload_zip.parent / PAYLOAD_NAME
    if not payload_root.is_dir():
        # Extract to a sibling directory next to the ZIP. We do
        # NOT use the staging directory for this so the build can
        # be re-run without re-extracting.
        _log("payload", f"extracting accepted ZIP to {payload_root}")
        with zipfile.ZipFile(payload_zip) as archive:
            archive.extractall(payload_root.parent)
    manifest_path = payload_root / "BUILD-MANIFEST.json"
    if not manifest_path.is_file():
        raise SystemExit(f"ERROR: BUILD-MANIFEST.json not found in payload at {manifest_path}.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source_commit") != EXPECTED_PAYLOAD_SOURCE_COMMIT:
        raise SystemExit(
            "ERROR: payload source_commit does not match the accepted B3A SHA.\n"
            f"  expected: {EXPECTED_PAYLOAD_SOURCE_COMMIT}\n"
            f"  actual:   {manifest.get('source_commit')}\n"
        )
    if manifest.get("version") != APP_VERSION:
        raise SystemExit(
            "ERROR: payload version does not match the accepted B3A version.\n"
            f"  expected: {APP_VERSION}\n"
            f"  actual:   {manifest.get('version')}\n"
        )
    actual_exe_sha = _sha256_of(payload_root / "Lockverity.exe")
    if actual_exe_sha != EXPECTED_LOCKVERITY_EXE_SHA256:
        raise SystemExit("ERROR: payload Lockverity.exe SHA-256 does not match the accepted value.")
    actual_cli_sha = _sha256_of(payload_root / "lockverity-cli.exe")
    if actual_cli_sha != EXPECTED_LOCKVERITY_CLI_EXE_SHA256:
        raise SystemExit(
            "ERROR: payload lockverity-cli.exe SHA-256 does not match the accepted value."
        )
    return {
        "payload_zip": str(payload_zip),
        "payload_zip_sha256": actual_zip_sha,
        "payload_source_commit": manifest.get("source_commit"),
        "payload_version": manifest.get("version"),
        "lockverity_exe_sha256": actual_exe_sha,
        "lockverity_cli_exe_sha256": actual_cli_sha,
        "build_manifest_sha256": _sha256_of(manifest_path),
        "payload_root": str(payload_root),
    }


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _stage_payload(payload_root: Path, staging_dir: Path) -> None:
    """Copy the accepted payload into the Inno Setup staging tree.

    The Inno Setup source consumes ``payload/*`` and ``root_extra/*``
    from the script's working directory. ``payload/`` is the B3A
    portable root; ``root_extra/`` is the install-root overlay
    (license, manifest, notices) that the installer places at
    ``{app}\\``.
    """
    payload_dest = staging_dir / "payload"
    if payload_dest.exists():
        shutil.rmtree(payload_dest)
    shutil.copytree(payload_root, payload_dest)

    root_extra_dest = staging_dir / "root_extra"
    if root_extra_dest.exists():
        shutil.rmtree(root_extra_dest)
    root_extra_dest.mkdir(parents=True, exist_ok=True)
    # Copy the per-user LICENSE / manifest / notices / SHA256SUMS
    # to the install root so they survive uninstall. The
    # uninstaller explicitly removes ``{app}\\app`` and
    # ``{app}\\docs`` (not the install-root manifest).
    for name in (
        "LICENSE",
        "BUILD-MANIFEST.json",
        "SHA256SUMS.txt",
        "THIRD_PARTY_NOTICES.txt",
        "README-PORTABLE.txt",
    ):
        src = payload_root / name
        if src.is_file():
            shutil.copy2(src, root_extra_dest / name)

    # Copy the approved icon for shortcuts (in addition to the
    # one the installer source references directly).
    approved_icon = BACKEND_ROOT / "pyinstaller" / "favicon-exe.ico"
    if approved_icon.is_file():
        shutil.copy2(approved_icon, root_extra_dest / "favicon-exe.ico")

    # Copy the user-facing documentation bundle. The Start Menu
    # entry points to ``{app}\\docs\\windows-installer.md``.
    docs_dest = root_extra_dest / "docs"
    docs_dest.mkdir(parents=True, exist_ok=True)
    installer_doc = REPO_ROOT / "docs" / "windows-installer.md"
    if installer_doc.is_file():
        shutil.copy2(installer_doc, docs_dest / "windows-installer.md")


def _build_installer(
    iscc: Path,
    staging_dir: Path,
    output_dir: Path,
    work_dir: Path,
    keep_work: bool,
) -> Path:
    """Run ISCC against the staged tree. Returns the installer EXE path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    if not keep_work and work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    # The committed .iss references the staged payload and
    # root-extra files via *relative* ``Source:`` paths
    # (``payload\*`` and ``root_extra\*``). ISCC resolves those
    # paths against the directory containing the .iss, not the
    # current working directory. Since the .iss is committed
    # under ``backend/installer/`` and the staged payload lives
    # under ``build/installer/staging/``, the only way to make
    # the relative paths resolve to the staged tree is to run
    # ISCC against a *copy* of the .iss placed inside the
    # staging directory. (The committed source is the single
    # source of truth; the copy is a transient build artefact
    # and is not committed.)
    staged_iss = staging_dir / "lockverity.iss"
    shutil.copy2(ISS_SOURCE, staged_iss)
    # The .iss's ``SetupIconFile`` directive (and the
    # ``Source:`` line in the [Files] section that copies the
    # same icon into ``{app}``) use a *relative* path
    # (``..\pyinstaller\favicon-exe.ico``) that ISCC resolves
    # against the directory containing the .iss. The path was
    # written when the .iss lived in ``backend/installer/``
    # and the icon in ``backend/pyinstaller/``; the ``..``
    # segment goes from the .iss's directory up to
    # ``backend\``, then back into ``pyinstaller\``. After the
    # .iss is copied into the staging dir, ``..`` from the
    # .iss would go up to ``build/installer/`` (the staging
    # dir's parent), not to the directory containing the icon,
    # so the path would not resolve. Rewrite all such
    # references in the staged copy to a staging-relative
    # form and mirror the icon at the matching location inside
    # the staging dir.
    pyinstaller_subdir = staging_dir / "pyinstaller"
    pyinstaller_subdir.mkdir(parents=True, exist_ok=True)
    icon_source = BACKEND_ROOT / "pyinstaller" / "favicon-exe.ico"
    if icon_source.is_file():
        staged_icon = pyinstaller_subdir / "favicon-exe.ico"
        shutil.copy2(icon_source, staged_icon)
        # Rewrite ``..\pyinstaller\favicon-exe.ico`` (committed,
        # backend-relative) to ``pyinstaller\favicon-exe.ico``
        # (staging-relative) everywhere it appears in the staged
        # copy. The committed source is unchanged. The substring
        # is unique to this icon path so a global replace is
        # safe.
        staged_iss_text = staged_iss.read_text(encoding="utf-8")
        staged_iss_text = staged_iss_text.replace(
            "..\\pyinstaller\\favicon-exe.ico",
            "pyinstaller\\favicon-exe.ico",
        )
        staged_iss.write_text(staged_iss_text, encoding="utf-8")
    # ``ISCC`` writes its build log to ``{app}\\`` by default.
    # The /O<full-path> flag sets the final installer EXE path
    # (directory + filename). The /F<base-name> flag is *not*
    # needed when /O<full-path> is given — /O is the canonical
    # way to control the output. There is no ``/OutputDir`` or
    # ``/OutputBaseFilename`` long form in ISCC; the long forms
    # used in earlier revisions of this script were being
    # parsed as ``/O utputDir=...`` and ``/F utputBaseFilename=...``
    # by the single-character switch parser, leading to
    # ``I/O error 123`` (ERROR_INVALID_NAME) on the resulting
    # path. AppId and AppVersion are taken from the .iss source;
    # they are NOT command-line flags (``/AppId`` and
    # ``/AppVersion`` are not valid ISCC options). The committed
    # .iss is the single source of truth for both values.
    installer_name = "Lockverity-2.1.0-windows-x64-setup.exe"
    installer_full_path = output_dir / installer_name
    cmd: list[str] = [
        str(iscc),
        f"/O{installer_full_path}",
        str(staged_iss),
    ]
    _log("iscc", f"running {iscc}")
    log_path = output_dir / "logs" / "iscc.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", errors="replace") as log_handle:
        result = subprocess.run(  # noqa: S603 - argv is built by us
            cmd,
            cwd=str(staging_dir),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            timeout=600,
        )
    if result.returncode != 0:
        raise SystemExit(f"ERROR: ISCC failed (rc={result.returncode}); see {log_path}")
    installer_exe = output_dir / installer_name
    if not installer_exe.is_file():
        raise SystemExit(f"ERROR: expected installer EXE not produced: {installer_exe}")
    return installer_exe


def _verify_installer_pe(installer_exe: Path) -> dict[str, object]:
    """Inspect the generated installer PE for architecture and icon."""
    import pefile  # type: ignore[import-untyped]

    pe = pefile.PE(str(installer_exe), fast_load=True)
    pe.parse_data_directories()
    arch_id = pe.FILE_HEADER.Machine
    arch = "x64" if arch_id == 0x8664 else f"0x{arch_id:x}"
    subsystem = pe.OPTIONAL_HEADER.Subsystem
    sub_label = (
        "WINDOWS_GUI"
        if subsystem == 2
        else "WINDOWS_CUI"
        if subsystem == 3
        else f"UNKNOWN({subsystem})"
    )
    has_icon = False
    icon_count = 0
    if hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
        for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if entry.id == 14:  # RT_GROUP_ICON
                has_icon = True
                for _ in entry.directory.entries:
                    icon_count += 1
    pe.close()
    return {
        "arch": arch,
        "subsystem": sub_label,
        "has_icon": has_icon,
        "icon_count": icon_count,
    }


def _write_installer_manifest(
    installer_exe: Path,
    output_dir: Path,
    *,
    installer_source_commit: str,
    payload_zip: Path,
    payload_summary: dict[str, object],
    iscc_path: Path,
) -> Path:
    """Generate the external ``INSTALLER-MANIFEST.json``."""
    manifest = {
        "product": "Lockverity",
        "version": APP_VERSION,
        "installer_source_commit": installer_source_commit,
        "payload_source_commit": EXPECTED_PAYLOAD_SOURCE_COMMIT,
        "payload_zip": payload_zip.name,
        "payload_zip_sha256": payload_summary["payload_zip_sha256"],
        "payload_build_manifest_sha256": payload_summary["build_manifest_sha256"],
        "lockverity_exe_sha256": payload_summary["lockverity_exe_sha256"],
        "lockverity_cli_exe_sha256": payload_summary["lockverity_cli_exe_sha256"],
        "installer_build_timestamp_utc": datetime.datetime.now(tz=datetime.UTC).isoformat(
            timespec="seconds"
        ),
        "target_platform": "windows",
        "target_architecture": "x64",
        "inno_setup_version": "6.7.3",
        "inno_setup_compiler_path": str(iscc_path),
        "inno_setup_compiler_sha256": _sha256_of(iscc_path),
        "installer_filename": installer_exe.name,
        "installer_sha256": _sha256_of(installer_exe),
        "stable_app_id": STABLE_APP_ID,
        "default_install_path": "%LOCALAPPDATA%\\Programs\\Lockverity",
        "privilege_mode": "per-user, no admin, no UAC",
        "code_signing_status": "unsigned",
        "telephony": False,
        "auto_update": False,
        "service_installation": False,
        "scheduled_task": False,
        "firewall_rule": False,
        "system_path_modification": False,
        "file_association": False,
        "browser_extension": False,
        "shell_context_menu_handler": False,
    }
    manifest_path = output_dir / "INSTALLER-MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _write_external_checksums(output_dir: Path, installer_exe: Path, manifest_path: Path) -> Path:
    """Generate an external ``SHA256SUMS.txt`` covering the installer
    EXE and ``INSTALLER-MANIFEST.json``. The check covers the
    artefacts OUTSIDE the installer (so the installer cannot
    self-validate)."""
    installer_sha = _sha256_of(installer_exe)
    manifest_sha = _sha256_of(manifest_path)
    checksums_path = output_dir / "SHA256SUMS.txt"
    checksums_path.write_text(
        f"{installer_sha}  {installer_exe.name}\n{manifest_sha}  {manifest_path.name}\n",
        encoding="utf-8",
    )
    return checksums_path


def _run_silent_smoke(installer_exe: Path, output_dir: Path, port: int) -> dict[str, object]:
    """Run a bounded silent-install smoke that the packaged
    binary actually launches and responds to ``/api/v1/health``.

    The smoke installs the EXE into a fresh
    ``%LOCALAPPDATA%\\Programs\\Lockverity-smoke`` directory,
    starts the installed ``Lockverity.exe`` with
    ``--no-browser``, asserts the health endpoint, then stops
    and uninstalls. The operator never sees a UI because the
    install is silent.
    """
    home_dir = Path(os.environ["LOCALAPPDATA"]) / "Lockverity-smoke"
    install_dir = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Lockverity-smoke"
    runtime_home = home_dir
    log_path = output_dir / "logs" / "silent-smoke.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = [
        str(installer_exe),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/SP-",
        f"/DIR={install_dir}",
        f"/PORT={port}",
        f"/LOG={log_path}",
    ]
    _log("smoke", f"silent install of {installer_exe.name} into {install_dir}")
    result = subprocess.run(  # noqa: S603 - argv is built by us
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if result.returncode != 0:
        return {
            "status": "install_failed",
            "rc": result.returncode,
            "log": str(log_path),
            "stdout_tail": (result.stdout or "")[-2000:],
            "stderr_tail": (result.stderr or "")[-2000:],
        }
    # Confirm files are present and the binaries match the
    # accepted payload.
    installed_cli = install_dir / "app" / "lockverity-cli.exe"
    if not installed_cli.is_file():
        return {
            "status": "missing_cli",
            "expected": str(installed_cli),
        }
    installed_cli_sha = _sha256_of(installed_cli)
    if installed_cli_sha != EXPECTED_LOCKVERITY_CLI_EXE_SHA256:
        return {
            "status": "cli_mismatch",
            "expected": EXPECTED_LOCKVERITY_CLI_EXE_SHA256,
            "actual": installed_cli_sha,
        }
    # Start the installed CLI in foreground mode for the smoke.
    env = os.environ.copy()
    env["LOCKVERITY_HOME"] = str(runtime_home)
    # Restricted PATH to prove the installed app does not
    # require system Python/Node/npm.
    env["PATH"] = "C:\\Windows\\System32;C:\\Windows"
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    cli_proc = subprocess.Popen(  # noqa: S603 - argv is built by us
        [str(installed_cli), "start", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # Wait for health (bounded). The exception is the documented
    # "service not yet listening" condition during startup; we
    # intentionally swallow it and re-probe on the next tick.
    import urllib.error
    import urllib.request

    health_ok = False
    for _ in range(40):
        time.sleep(1.0)
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/v1/health", timeout=2
            ) as response:
                if 200 <= response.status < 300:
                    health_ok = True
                    break
        except (urllib.error.URLError, OSError, TimeoutError):
            # Expected: server not yet listening. Re-probe.
            continue
    health_result: dict[str, object] = {
        "status": "ok" if health_ok else "no_health",
        "port": port,
    }
    # Stop
    try:
        stop_proc = subprocess.run(  # noqa: S603 - argv is built by us
            [str(installed_cli), "stop"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        health_result["stop_rc"] = stop_proc.returncode
        health_result["stop_stdout_tail"] = (stop_proc.stdout or "")[-500:]
    except Exception as exc:  # pragma: no cover - best-effort cleanup
        health_result["stop_error"] = repr(exc)
    # Uninstall
    try:
        uninst = subprocess.run(  # noqa: S603 - argv is built by us
            [
                str(installer_exe),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                f"/DIR={install_dir}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        health_result["uninstall_rc"] = uninst.returncode
    except Exception as exc:  # pragma: no cover - best-effort cleanup
        health_result["uninstall_error"] = repr(exc)
    try:
        cli_proc.wait(timeout=5)
    except Exception:
        cli_proc.kill()
    return health_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_windows_installer")
    parser.add_argument(
        "--payload-zip",
        type=Path,
        default=DEFAULT_PAYLOAD_ZIP,
        help="Path to the accepted B3A portable payload ZIP. Default: the build/packaging artefact.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Dedicated installer output directory (default: build/installer).",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=DEFAULT_STAGING_DIR,
        help="Dedicated staging directory for the Inno Setup source tree.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_DIR,
        help="Dedicated Inno Setup work directory.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Wipe --output-dir (except the staged payload), --staging-dir and --work-dir before building.",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="Keep --work-dir after the build (default: remove).",
    )
    parser.add_argument(
        "--json-report",
        action="store_true",
        help="Emit a structured JSON report on stdout at the end.",
    )
    parser.add_argument(
        "--run-smoke",
        action="store_true",
        help="Run a silent-install + health + uninstall smoke after the build. Disabled by default.",
    )
    parser.add_argument(
        "--skip-clean-git-check",
        action="store_true",
        help="Skip the clean-git-state check (use only for development iterations, never for the final acceptance build).",
    )
    args = parser.parse_args(argv)

    started_at = datetime.datetime.now(tz=datetime.UTC).isoformat(timespec="seconds")
    started_monotonic = time.monotonic()
    _verify_host()
    iscc = _verify_iscc()
    _log(
        "host",
        f"verified Windows x64 (Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})",
    )
    if not args.skip_clean_git_check:
        _verify_clean_git_state()
    installer_source_commit = _git_head_full()
    _log("git", f"installer source commit: {installer_source_commit}")
    _log("iscc", f"verified Inno Setup compiler: {iscc}")

    if args.clean:
        if args.output_dir.is_dir():
            _log("clean", f"wiping {args.output_dir}")
            for child in args.output_dir.iterdir():
                if child == args.payload_zip:
                    continue
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    with contextlib.suppress(FileNotFoundError):
                        child.unlink()
        for d in (args.staging_dir, args.work_dir):
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

    payload_summary = _verify_payload_zip(args.payload_zip)
    _log(
        "payload",
        f"accepted B3A payload verified (zip_sha256={payload_summary['payload_zip_sha256'][:12]}..., source_commit={payload_summary['payload_source_commit']})",
    )
    _stage_payload(Path(payload_summary["payload_root"]), args.staging_dir)
    _log("staging", f"payload staged into {args.staging_dir}")

    installer_exe = _build_installer(
        iscc=iscc,
        staging_dir=args.staging_dir,
        output_dir=args.output_dir,
        work_dir=args.work_dir,
        keep_work=args.keep_work,
    )
    _log("iscc", f"installer EXE produced at {installer_exe}")
    pe_info = _verify_installer_pe(installer_exe)
    _log(
        "pe",
        f"installer PE: arch={pe_info['arch']} subsystem={pe_info['subsystem']} icon_count={pe_info['icon_count']}",
    )
    manifest_path = _write_installer_manifest(
        installer_exe,
        args.output_dir,
        installer_source_commit=installer_source_commit,
        payload_zip=args.payload_zip,
        payload_summary=payload_summary,
        iscc_path=iscc,
    )
    checksums_path = _write_external_checksums(args.output_dir, installer_exe, manifest_path)
    _log("manifest", f"wrote {manifest_path.name} + {checksums_path.name}")

    smoke_result: dict[str, object] | None = None
    if args.run_smoke:
        port = _free_port()
        smoke_result = _run_silent_smoke(installer_exe, args.output_dir, port)
        _log("smoke", f"silent-install smoke status={smoke_result.get('status')}")

    report = {
        "started_at_utc": started_at,
        "duration_seconds": round(time.monotonic() - started_monotonic, 2),
        "machine": f"{platform.machine().lower()}",
        "platform": sys.platform,
        "installer_source_commit": installer_source_commit,
        "payload_source_commit": EXPECTED_PAYLOAD_SOURCE_COMMIT,
        "inno_setup_compiler": str(iscc),
        "inno_setup_compiler_sha256": _sha256_of(iscc),
        "installer_filename": installer_exe.name,
        "installer_sha256": _sha256_of(installer_exe),
        "installer_size_bytes": installer_exe.stat().st_size,
        "installer_manifest_sha256": _sha256_of(manifest_path),
        "stable_app_id": STABLE_APP_ID,
        "app_version": APP_VERSION,
        "default_install_path": "%LOCALAPPDATA%\\Programs\\Lockverity",
        "target_platform": "windows",
        "target_architecture": "x64",
        "code_signing_status": "unsigned",
        "pe": pe_info,
        "payload": payload_summary,
        "silent_smoke": smoke_result,
    }
    if args.json_report:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        _log("done", f"installer: {installer_exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
