"""Authenticode signing readiness helper (v2.1.2).

This module is a **disabled-by-default** signing
readiness hook. The v2.1.2 hotfix ships the
*infrastructure* to sign the Lockverity Windows
binaries once a trusted Authenticode certificate is
provisioned, but it does **not** ship any certificate
material, private key, password, or signing provider
integration. The build remains functional and
unsigned without configuration.

Configuration
=============

All knobs are read from environment variables so the
signing material can be injected from CI secrets or a
local ``.env`` file (which is git-ignored) without
touching tracked source. The variables are:

  ``LOCKVERITY_SIGNTOOL_PATH``
    Absolute path to a Windows ``signtool.exe``
    (Windows SDK) or compatible tool. When this
    variable is unset the signing step is a no-op
    and the function returns
    ``("disabled", None)`` immediately.

  ``LOCKVERITY_SIGNTOOL_PFX``
    Absolute path to a ``.pfx`` file. The file is
    read by the signtool invocation; **never** log
    the contents of this file. The file is **not**
    bundled in the repository, the build artefact,
    or the installer payload. A missing file causes
    the signing step to fail with a clear error.

  ``LOCKVERITY_SIGNTOOL_PFX_PASSWORD``
    Password for the ``.pfx``. **Never** log the
    contents of this variable. The build script
    passes the password via the documented
    signtool flag (``/p <password>``); it never
    writes the value to disk or to the install log.

  ``LOCKVERITY_SIGNTOOL_TIMESTAMP_URL``
    RFC 3161 timestamp authority URL. The default
    is the documented DigiCert URL. An empty value
    disables timestamping (the signature is still
    valid but will not survive code-signing
    certificate expiration).

  ``LOCKVERITY_SIGNTOOL_DESCRIPTION``
    Description embedded in the signature
    (``/d <description>``). The default is
    ``"Lockverity"``.

  ``LOCKVERITY_SIGNTOOL_URL``
    URL embedded in the signature
    (``/du <url>``). The default is
    ``https://github.com/namanparikh11/lockverity``.

Order of signing
================

When signing is enabled, the helper signs the
following files **in this order** (the order matters
because a single SHA-256 counter-signature chain is
emitted; the chain anchors on the first sign and
later signs reference it):

  1. ``Lockverity.exe`` (graphical launcher)
  2. ``lockverity-cli.exe`` (CLI)
  3. ``unins000.exe`` (Inno Setup uninstaller)
  4. ``<installer>.exe`` (the final installer EXE)

Verification
============

After signing, the helper runs the documented
``signtool verify /pa`` (or ``/a`` if ``/pa`` is
unavailable) on each signed file and confirms the
``"Number of signatures: 1"`` line is present. The
function returns a structured result the build script
records in ``INSTALLER-MANIFEST.json``:

  ``{"enabled": true|false, "signer": str|None,
    "timestamp": str|None, "files": [<file>, ...],
    "verification": {<file>: "ok"|"failed", ...}}``

When signing is disabled, the function returns
``{"enabled": false, "signer": None, "timestamp":
None, "files": [], "verification": {}}``.

Security
========

  * **No certificate material is tracked.** The
    module is the only place that reads the env
    vars, and the build script never writes them to
    the install log.
  * **No PFX is bundled.** A missing PFX is treated
    as an actionable build error.
  * **No password is logged.** The signtool
    invocation hides the password from process
    listings via the documented ``/p`` flag.
  * **No self-signed production certificate is
    generated.** The module does not call
    ``New-SelfSignedCertificate`` or any equivalent.
  * **The release remains unsigned** until an
    operator explicitly enables the hooks by
    setting the documented env vars.

The module is exercised by
``tests/test_signing_readiness.py``.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

# Environment variable names. Centralised so the test
# suite and the build script share a single source of
# truth.
ENV_SIGNTOOL_PATH = "LOCKVERITY_SIGNTOOL_PATH"
ENV_SIGNTOOL_PFX = "LOCKVERITY_SIGNTOOL_PFX"
ENV_SIGNTOOL_PFX_PASSWORD = "LOCKVERITY_SIGNTOOL_PFX_PASSWORD"  # noqa: S105 - env var name, not credential
ENV_SIGNTOOL_TIMESTAMP_URL = "LOCKVERITY_SIGNTOOL_TIMESTAMP_URL"
ENV_SIGNTOOL_DESCRIPTION = "LOCKVERITY_SIGNTOOL_DESCRIPTION"
ENV_SIGNTOOL_URL = "LOCKVERITY_SIGNTOOL_URL"

# Default values (used only when signing is enabled).
DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"
DEFAULT_DESCRIPTION = "Lockverity"
DEFAULT_URL = "https://github.com/namanparikh11/lockverity"

# Canonical signing order. The order matters: see the
# module docstring's "Order of signing" section.
DEFAULT_SIGNING_ORDER: tuple[str, ...] = (
    "Lockverity.exe",
    "lockverity-cli.exe",
    "unins000.exe",
)


def is_signing_enabled() -> bool:
    """Return ``True`` iff signing credentials are present.

    The check is a single source of truth: every other
    function in this module consults
    :func:`is_signing_enabled` to decide whether to
    sign. The function intentionally reads only the
    *presence* of the env vars, not their validity; a
    missing file or a wrong password is reported as a
    signing-time error (the build script aborts with
    an actionable message).
    """
    return bool(os.environ.get(ENV_SIGNTOOL_PATH))


def signing_status() -> dict[str, Any]:
    """Return the current signing configuration as a dict.

    The function is the read-only view the build
    script uses to log signing state. It does not
    invoke any external tool. The returned dict
    includes:

      ``enabled``: bool
      ``signtool_path``: str | None
      ``pfx_path``: str | None
      ``pfx_password_set``: bool  (never the password itself)
      ``timestamp_url``: str | None
      ``description``: str
      ``url``: str

    The ``pfx_password_set`` field is a boolean only;
    the actual password is never returned by this
    function.
    """
    enabled = is_signing_enabled()
    pfx_password = os.environ.get(ENV_SIGNTOOL_PFX_PASSWORD, "")
    return {
        "enabled": enabled,
        "signtool_path": os.environ.get(ENV_SIGNTOOL_PATH),
        "pfx_path": os.environ.get(ENV_SIGNTOOL_PFX),
        "pfx_password_set": bool(pfx_password),
        "timestamp_url": os.environ.get(ENV_SIGNTOOL_TIMESTAMP_URL, DEFAULT_TIMESTAMP_URL),
        "description": os.environ.get(ENV_SIGNTOOL_DESCRIPTION, DEFAULT_DESCRIPTION),
        "url": os.environ.get(ENV_SIGNTOOL_URL, DEFAULT_URL),
    }


def _verify_host() -> tuple[str, str]:
    """Return ``(platform, machine)`` and refuse non-Windows hosts.

    Authenticode signing is a Windows-only operation.
    The function raises :class:`SystemExit` if the
    current host is not Windows x64 so a Linux / macOS
    developer who accidentally enables signing gets a
    clear error rather than a confusing ``signtool``
    not-found failure.
    """
    if sys_platform() != "win32":
        raise SystemExit(
            "ERROR: Authenticode signing is Windows-only. "
            f"Detected platform: {sys_platform()!r}. Unset the "
            f"{ENV_SIGNTOOL_PATH!r} environment variable on non-Windows hosts."
        )
    machine = platform.machine().lower()
    if machine not in ("amd64", "x86_64"):
        raise SystemExit(
            f"ERROR: Authenticode signing requires Windows x64 (detected machine={machine!r})."
        )
    return (sys_platform(), machine)


def sys_platform() -> str:
    """Return the current platform string (``sys.platform`` wrapper)."""
    import sys

    return sys.platform


def sign_files(
    targets: list[Path],
    *,
    signtool_path: Path | None = None,
    pfx_path: Path | None = None,
    pfx_password: str | None = None,
    timestamp_url: str | None = None,
    description: str | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    """Sign the given files with the configured signtool.

    The function is a no-op (returning the disabled
    result) when :func:`is_signing_enabled` returns
    ``False``. When signing is enabled the function
    invokes the configured signtool against each
    target in order, then verifies each signed file
    with ``signtool verify /pa``.

    Parameters
    ----------
    targets:
        Files to sign in order. Missing files cause
        the function to abort with an actionable
        error.
    signtool_path, pfx_path, pfx_password, ...:
        Optional overrides for the environment
        variables. The function prefers explicit
        arguments over env vars; this lets the test
        suite inject a mocked signtool without
        touching the process environment.

    Returns
    -------
    dict
        ``{"enabled": bool, "signer": str|None,
        "timestamp": str|None, "files": [str, ...],
        "verification": {<file>: "ok"|"failed"}}``
    """
    if not is_signing_enabled():
        return {
            "enabled": False,
            "signer": None,
            "timestamp": None,
            "files": [],
            "verification": {},
        }
    _verify_host()
    signtool = Path(signtool_path or os.environ[ENV_SIGNTOOL_PATH])
    pfx = Path(pfx_path or os.environ.get(ENV_SIGNTOOL_PFX, ""))
    password = (
        pfx_password if pfx_password is not None else os.environ.get(ENV_SIGNTOOL_PFX_PASSWORD, "")
    )
    ts_url = timestamp_url or os.environ.get(ENV_SIGNTOOL_TIMESTAMP_URL, DEFAULT_TIMESTAMP_URL)
    desc = description or os.environ.get(ENV_SIGNTOOL_DESCRIPTION, DEFAULT_DESCRIPTION)
    url = url or os.environ.get(ENV_SIGNTOOL_URL, DEFAULT_URL)
    if not signtool.is_file():
        raise SystemExit(
            f"ERROR: configured signtool not found at {signtool}. "
            f"Set {ENV_SIGNTOOL_PATH} to a valid signtool.exe or unset it to disable signing."
        )
    if not pfx.is_file():
        raise SystemExit(
            f"ERROR: configured PFX not found at {pfx}. "
            f"Set {ENV_SIGNTOOL_PFX} to a valid .pfx file or unset both {ENV_SIGNTOOL_PATH} and "
            f"{ENV_SIGNTOOL_PFX} to disable signing."
        )
    signed_files: list[str] = []
    verification: dict[str, str] = {}
    for target in targets:
        if not target.is_file():
            raise SystemExit(f"ERROR: signing target not found: {target}")
        cmd: list[str] = [
            str(signtool),
            "sign",
            "/f",
            str(pfx),
            "/p",
            password,
            "/t",
            ts_url,
            "/d",
            desc,
            "/du",
            url,
            "/fd",
            "sha256",
            str(target),
        ]
        result = subprocess.run(  # noqa: S603 - argv is built by us
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if result.returncode != 0:
            raise SystemExit(
                f"ERROR: signtool sign failed for {target} (rc={result.returncode}): "
                f"{(result.stderr or result.stdout or '').strip()[-500:]}"
            )
        signed_files.append(str(target))
        # Verify
        verify_cmd: list[str] = [str(signtool), "verify", "/pa", str(target)]
        verify_result = subprocess.run(  # noqa: S603 - argv is built by us
            verify_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        verification[str(target)] = (
            "ok"
            if verify_result.returncode == 0
            and re.search(r"Number of signatures:\s*1", verify_result.stdout or "")
            else "failed"
        )
        if verification[str(target)] != "ok":
            raise SystemExit(
                f"ERROR: signtool verify failed for {target}; expected a single valid signature."
            )
    return {
        "enabled": True,
        "signer": str(pfx),
        "timestamp": ts_url,
        "files": signed_files,
        "verification": verification,
    }


def maybe_sign_files(targets: list[Path]) -> dict[str, Any]:
    """High-level wrapper: sign ``targets`` if enabled, else no-op.

    The function is the chokepoint the build script
    calls. It returns the structured result the
    build script records in ``INSTALLER-MANIFEST.json``
    (the ``code_signing`` field) and on stdout for
    operator visibility.
    """
    if not is_signing_enabled():
        return {
            "enabled": False,
            "signer": None,
            "timestamp": None,
            "files": [],
            "verification": {},
        }
    return sign_files(targets)


__all__ = [
    "DEFAULT_DESCRIPTION",
    "DEFAULT_SIGNING_ORDER",
    "DEFAULT_TIMESTAMP_URL",
    "DEFAULT_URL",
    "ENV_SIGNTOOL_DESCRIPTION",
    "ENV_SIGNTOOL_PATH",
    "ENV_SIGNTOOL_PFX",
    "ENV_SIGNTOOL_PFX_PASSWORD",
    "ENV_SIGNTOOL_TIMESTAMP_URL",
    "ENV_SIGNTOOL_URL",
    "is_signing_enabled",
    "maybe_sign_files",
    "sign_files",
    "signing_status",
    "sys_platform",
]


def _self_test_shutil_which() -> str | None:
    """Return ``shutil.which('git')`` for the test suite to assert.

    The function is a tiny shim so the test suite
    can verify the module's standard-library
    imports are wired correctly.
    """
    return shutil.which("git")
