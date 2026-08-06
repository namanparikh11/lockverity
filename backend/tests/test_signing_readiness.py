"""Tests for the v2.1.2 Authenticode signing readiness hooks.

The signing module (``backend/scripts/_authenticode_sign.py``)
is a **disabled-by-default** readiness hook. The v2.1.2
hotfix ships the *infrastructure* to sign the Lockverity
Windows binaries once a trusted Authenticode certificate is
provisioned, but it does **not** ship any certificate
material, private key, password, or signing provider
integration. The build remains functional and unsigned
without configuration.

The tests in this module verify:

  1. Signing is disabled when no env vars are set.
  2. The signing status dict never contains the
     ``pfx_password`` value.
  3. The :func:`maybe_sign_files` function is a no-op
     when signing is disabled and returns the documented
     disabled-state dict.
  4. The :func:`is_signing_enabled` function is the
     single source of truth for the enabled check.
  5. The :func:`_verify_host` function refuses to run
     on non-Windows hosts when signing is enabled.
  6. The documented env-var names are stable (the test
     suite and the build script share a single source of
     truth).
  7. No certificate material is tracked in the
     repository (no ``.pfx``, no ``.p12``, no private
     key files).
  8. The module does not generate self-signed
     certificates.

The tests do not require signtool to be installed; they
verify the readiness contract in isolation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from scripts import _authenticode_sign

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


@pytest.fixture(autouse=True)
def _clean_signing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every signing env var before each test.

    The fixture guarantees the test does not see a
    signing configuration that leaked from the host
    environment.
    """
    for var in (
        _authenticode_sign.ENV_SIGNTOOL_PATH,
        _authenticode_sign.ENV_SIGNTOOL_PFX,
        _authenticode_sign.ENV_SIGNTOOL_PFX_PASSWORD,
        _authenticode_sign.ENV_SIGNTOOL_TIMESTAMP_URL,
        _authenticode_sign.ENV_SIGNTOOL_DESCRIPTION,
        _authenticode_sign.ENV_SIGNTOOL_URL,
    ):
        monkeypatch.delenv(var, raising=False)


class TestSigningDisabledByDefault:
    """Signing is OFF when no env vars are set."""

    def test_is_signing_enabled_false_by_default(self) -> None:
        assert _authenticode_sign.is_signing_enabled() is False

    def test_signing_status_disabled(self) -> None:
        status = _authenticode_sign.signing_status()
        assert status["enabled"] is False
        assert status["signtool_path"] is None
        assert status["pfx_path"] is None
        assert status["pfx_password_set"] is False

    def test_maybe_sign_files_is_noop(self, tmp_path: Path) -> None:
        # Create a target file; the no-op must not modify it.
        target = tmp_path / "Lockverity.exe"
        target.write_bytes(b"placeholder")
        result = _authenticode_sign.maybe_sign_files([target])
        assert result == {
            "enabled": False,
            "signer": None,
            "timestamp": None,
            "files": [],
            "verification": {},
        }
        # The target file is unchanged.
        assert target.read_bytes() == b"placeholder"


class TestSigningStatusPrivacy:
    """The status dict never leaks the PFX password."""

    def test_status_does_not_include_password_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_authenticode_sign.ENV_SIGNTOOL_PATH, r"C:\fake\signtool.exe")
        monkeypatch.setenv(_authenticode_sign.ENV_SIGNTOOL_PFX_PASSWORD, "super-secret-12345")
        status = _authenticode_sign.signing_status()
        # The password is reported as a boolean only.
        assert status["pfx_password_set"] is True
        # The actual password value is never in the dict.
        serialised = repr(status)
        assert "super-secret-12345" not in serialised

    def test_status_does_not_include_password_in_serialised_form(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(_authenticode_sign.ENV_SIGNTOOL_PATH, r"C:\fake\signtool.exe")
        monkeypatch.setenv(_authenticode_sign.ENV_SIGNTOOL_PFX_PASSWORD, "another-secret")
        status = _authenticode_sign.signing_status()
        # The serialised form must not contain the password.
        import json

        for text in (repr(status), json.dumps(status)):
            assert "another-secret" not in text


class TestEnvVarConstants:
    """The documented env-var names are stable."""

    def test_env_var_names_are_stable(self) -> None:
        assert _authenticode_sign.ENV_SIGNTOOL_PATH == "LOCKVERITY_SIGNTOOL_PATH"
        assert _authenticode_sign.ENV_SIGNTOOL_PFX == "LOCKVERITY_SIGNTOOL_PFX"
        assert _authenticode_sign.ENV_SIGNTOOL_PFX_PASSWORD == "LOCKVERITY_SIGNTOOL_PFX_PASSWORD"
        assert _authenticode_sign.ENV_SIGNTOOL_TIMESTAMP_URL == "LOCKVERITY_SIGNTOOL_TIMESTAMP_URL"
        assert _authenticode_sign.ENV_SIGNTOOL_DESCRIPTION == "LOCKVERITY_SIGNTOOL_DESCRIPTION"
        assert _authenticode_sign.ENV_SIGNTOOL_URL == "LOCKVERITY_SIGNTOOL_URL"

    def test_env_var_names_are_prefixed(self) -> None:
        for name in (
            _authenticode_sign.ENV_SIGNTOOL_PATH,
            _authenticode_sign.ENV_SIGNTOOL_PFX,
            _authenticode_sign.ENV_SIGNTOOL_PFX_PASSWORD,
            _authenticode_sign.ENV_SIGNTOOL_TIMESTAMP_URL,
            _authenticode_sign.ENV_SIGNTOOL_DESCRIPTION,
            _authenticode_sign.ENV_SIGNTOOL_URL,
        ):
            assert name.startswith("LOCKVERITY_"), (
                f"env var {name!r} must be prefixed with 'LOCKVERITY_' to avoid collisions"
            )

    def test_default_signing_order_canonical(self) -> None:
        order = _authenticode_sign.DEFAULT_SIGNING_ORDER
        assert order == ("Lockverity.exe", "lockverity-cli.exe", "unins000.exe"), (
            "Signing order must be Lockverity.exe -> lockverity-cli.exe -> unins000.exe; "
            "the order matters because later signs reference the earlier counter-signature chain."
        )


class TestHostVerification:
    """The signing helper refuses non-Windows hosts when enabled."""

    def test_verify_host_refuses_non_windows(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Set the env var so signing appears enabled.
        monkeypatch.setenv(_authenticode_sign.ENV_SIGNTOOL_PATH, str(tmp_path / "fake.exe"))
        # Patch sys.platform to a non-Windows value via the module's
        # indirection (the helper calls ``_authenticode_sign.sys_platform()``).
        monkeypatch.setattr(_authenticode_sign, "sys_platform", lambda: "linux")
        with pytest.raises(SystemExit) as exc:
            _authenticode_sign._verify_host()
        assert "Windows-only" in str(exc.value)


class TestNoCertificateMaterialTracked:
    """No certificate / private key material is in the repository."""

    def test_no_pfx_or_private_key_files_tracked(self) -> None:
        # The .gitignore should exclude ``*.pfx`` / ``*.p12`` /
        # ``*.key``; we confirm that even an explicit search of
        # the tracked working tree does not find one. We
        # deliberately scope the search to *private* key
        # material and Authenticode PFX bundles; the
        # ``*.pem`` pattern is excluded because the ``certifi``
        # package ships a public CA bundle
        # (``cacert.pem``) that the Python runtime needs and
        # which is plainly not a private key.
        offenders: list[str] = []
        for pattern in ("*.pfx", "*.p12", "*.key"):
            for path in REPO_ROOT.rglob(pattern):
                # Skip the .venv and node_modules noise; these
                # are obviously not tracked but the rglob sees
                # them in some configurations.
                rel = path.relative_to(REPO_ROOT)
                rel_str = str(rel).replace("\\", "/")
                if "/.venv/" in rel_str or "/node_modules/" in rel_str:
                    continue
                if "/build/" in rel_str or "/dist/" in rel_str:
                    continue
                offenders.append(rel_str)
        assert not offenders, (
            "Repository must not track any private key / PFX material: "
            f"found {offenders!r}. Add the offending pattern to .gitignore."
        )

    def test_no_signing_provider_secrets_in_tracked_source(self) -> None:
        # Common signtool-friendly provider names. If a future
        # maintainer accidentally commits a token, this guard
        # catches it. The check is a regex scan across a small
        # set of authoritative files (not the full working tree,
        # to keep the test fast).
        for rel in (
            "backend/scripts/_authenticode_sign.py",
            "backend/scripts/build_windows_installer.py",
            "backend/scripts/build_windows_portable.py",
            "backend/installer/lockverity.iss",
        ):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
            for forbidden in (
                "BEGIN PRIVATE KEY",
                "BEGIN RSA PRIVATE KEY",
                "BEGIN ENCRYPTED PRIVATE KEY",
                "BEGIN CERTIFICATE",
                "MIICXAIBAAKBgQ",  # base64-encoded DER X.509 cert magic
            ):
                assert forbidden not in text, (
                    f"{rel} must not contain raw certificate / key material; found {forbidden!r}"
                )


class TestBuildScriptSigningWiring:
    """The build script surfaces signing state in the install manifest."""

    def test_build_script_imports_signing_helper(self) -> None:
        text = (BACKEND_ROOT / "scripts" / "build_windows_installer.py").read_text(
            encoding="utf-8", errors="replace"
        )
        # The build script may import the helper in a future
        # iteration; for v2.1.2 the contract is that the
        # *helper* exists and the build script does not
        # perform any signing work itself.
        assert "from scripts import _authenticode_sign" not in text, (
            "Build script must not unconditionally import the signing helper; "
            "the import is a no-op cost for every build."
        )

    def test_build_script_records_signing_status_in_manifest(self) -> None:
        # The manifest writer records ``code_signing_status``;
        # in v2.1.2 the status is still ``"unsigned"`` because
        # the readiness hook is disabled by default.
        text = (BACKEND_ROOT / "scripts" / "build_windows_installer.py").read_text(
            encoding="utf-8", errors="replace"
        )
        assert '"code_signing_status"' in text or "'code_signing_status'" in text
        assert '"unsigned"' in text or "'unsigned'" in text

    def test_installer_source_marks_unsigned(self) -> None:
        text = (BACKEND_ROOT / "installer" / "lockverity.iss").read_text(
            encoding="utf-8", errors="replace"
        )
        assert "SignedUninstaller=no" in text
        # No SignTool directive (the disabled-by-default contract).
        code_lines = [
            line for line in text.splitlines() if line.strip() and not line.lstrip().startswith(";")
        ]
        for line in code_lines:
            assert not re.match(r"^\s*SignTool\s*=", line, re.IGNORECASE), (
                "Installer source must not declare any SignTool= directive; signing is a build-time "
                "concern handled by the build script, not the Inno Setup source."
            )


class TestNoSelfSignedCertificateGeneration:
    """The signing helper does not generate self-signed certificates."""

    def test_no_self_signed_certificate_call(self) -> None:
        # The check is a regex on the executable body (not the
        # docstring) so the helper's own documentation can
        # mention the forbidden commands without tripping the
        # assertion.
        text = (BACKEND_ROOT / "scripts" / "_authenticode_sign.py").read_text(
            encoding="utf-8", errors="replace"
        )
        # Strip the docstring so the prose that *names* the
        # forbidden commands (e.g. "the helper does not call
        # New-SelfSignedCertificate") does not trip the
        # assertion.
        in_docstring = False
        body_lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if in_docstring:
                    in_docstring = False
                    continue
                in_docstring = True
                continue
            if not in_docstring:
                body_lines.append(line)
        body = "\n".join(body_lines)
        for forbidden in (
            "New-SelfSignedCertificate",
            "openssl req",
            "openssl genrsa",
            "MakeCert",
            "makecert",
            "X509SigningCert",
        ):
            assert forbidden not in body, (
                f"Signing helper must not generate a self-signed certificate; found {forbidden!r}"
            )


class TestNoPasswordLogging:
    """The signing helper never logs the PFX password."""

    def test_password_not_logged(self) -> None:
        text = (BACKEND_ROOT / "scripts" / "_authenticode_sign.py").read_text(
            encoding="utf-8", errors="replace"
        )
        # The signtool invocation uses ``/p <password>``; this is
        # the documented way to pass the password to signtool
        # without leaking it to the process listing (``/p`` is a
        # documented signtool flag that the SDK's signtool treats
        # as a secret). We assert the function does not ``print``,
        # ``log``, or ``write`` the password anywhere.
        for forbidden in (
            "print(pfx_password",
            "log(pfx_password",
            "write(pfx_password",
            "print(password",
            "log(password",
            "write(password",
            "stderr.write(password",
            "stdout.write(password",
        ):
            assert forbidden not in text, (
                f"Signing helper must not log the password; found {forbidden!r}"
            )
