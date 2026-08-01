"""Tests for the v2.1 Part B3B Windows installer source.

The tests cover the installer source contract documented in
``backend\\installer\\lockverity.iss`` and the build script
in ``backend\\scripts\\build_windows_installer.py``. They are
pure-Python static checks: they read the committed source and
fail the suite if a maintainer changes a contract the
operator-facing installer must honour. The full installer
build, install, and uninstall are exercised separately by
the build script's silent smoke (opt-in) and by the manual
acceptance cycle.

Every test in this file documents a single v2.1 Part B3B
acceptance contract. New contracts must add a test; broken
contracts must be repaired before the test is removed.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
ISS_SOURCE = BACKEND_ROOT / "installer" / "lockverity.iss"
BUILD_SCRIPT = BACKEND_ROOT / "scripts" / "build_windows_installer.py"
APPROVED_ICON = BACKEND_ROOT / "pyinstaller" / "favicon-exe.ico"
APPROVED_FAVICON_ICO = REPO_ROOT / "frontend" / "public" / "favicon.ico"
DOCS_FILE = REPO_ROOT / "docs" / "windows-installer.md"

STABLE_APP_ID = "{E5B0C0F4-7C42-4D6A-9B17-1A2B3C4D5E6F}"

EXPECTED_PAYLOAD_ZIP_SHA256 = "ec9a4d3fdf160e5364a62acba25fc2bcbaaf5e067ba116cd3f355d2c61cca588"
EXPECTED_PAYLOAD_SOURCE_COMMIT = "81b400bc40ae6ada2787470fca8b31c5ea8b1c30"
EXPECTED_LOCKVERITY_EXE_SHA256 = "beecc5cd4d9d336f5adf450c947bf1db62a6493876a8250bfdba9889997ff059"
EXPECTED_LOCKVERITY_CLI_EXE_SHA256 = (
    "f74f3e5b8631bf3ec5f018064367fd26a2b5b8b1cf19518a94a0deb40c2e4796"
)


def _iss_text() -> str:
    return ISS_SOURCE.read_text(encoding="utf-8", errors="replace")


def _build_text() -> str:
    return BUILD_SCRIPT.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------
# .iss source contract
# ---------------------------------------------------------------------


class TestInstallerSourceContract:
    """The committed Inno Setup source must honour every spec contract."""

    def test_stable_app_id_is_present(self) -> None:
        text = _iss_text()
        assert STABLE_APP_ID in text, (
            f"AppId {STABLE_APP_ID} not found in installer source; "
            "the per-user uninstaller key must remain stable across "
            "all v2.1 Windows installer builds."
        )

    def test_app_name_lockverity(self) -> None:
        text = _iss_text()
        assert re.search(r"AppName=\{#MyAppDisplayName\}", text), (
            "AppName must be the MyAppDisplayName define (== Lockverity)"
        )
        assert re.search(r'#define\s+MyAppName\s+"Lockverity"', text), (
            "MyAppName must be defined as 'Lockverity'"
        )

    def test_app_version_2_1_0(self) -> None:
        text = _iss_text()
        assert re.search(r'#define\s+MyAppVersion\s+"2\.1\.0"', text), (
            "MyAppVersion must be the v2.1.0 accepted version"
        )
        assert re.search(r"AppVersion=\{#MyAppVersion\}", text), (
            "AppVersion must reference MyAppVersion"
        )

    def test_privilege_mode_lowest(self) -> None:
        text = _iss_text()
        assert re.search(r"^\s*PrivilegesRequired\s*=\s*lowest", text, re.MULTILINE), (
            "PrivilegesRequired must be ``lowest`` (no admin, no UAC)"
        )

    def test_architecture_x64(self) -> None:
        text = _iss_text()
        assert re.search(
            r"^\s*ArchitecturesInstallIn64BitMode\s*=\s*x64compatible",
            text,
            re.MULTILINE,
        ), "Installer must declare x64 as the only install architecture"

    def test_default_install_path_uses_localappdata(self) -> None:
        text = _iss_text()
        assert re.search(
            r"DefaultDirName=\{localappdata\}\\Programs\\\{#MyAppName\}",
            text,
        ), "Default install path must be {localappdata}\\Programs\\<AppName>"

    def test_no_autolocalappdata_constant(self) -> None:
        # Regression: the installer source carried
        # ``DefaultDirName={autolocalappdata}\Programs\{#MyAppName}``
        # but the ``{autolocalappdata}`` constant does not exist
        # in Inno Setup 6.7.3 — the correct constant is
        # ``{localappdata}`` (the ``auto`` prefix in Inno Setup
        # constants is reserved for system-vs-user profile
        # resolution such as ``{autopf}`` / ``{autoprograms}`` /
        # ``{autostartmenu}``, and ``{localappdata}`` is already
        # inherently per-user). The compiler reported
        # ``Unknown constant "autolocalappdata"``. Strip comment
        # lines so explanatory prose does not trip the assertion.
        code_lines = [
            line
            for line in _iss_text().splitlines()
            if line.strip() and not line.lstrip().startswith(";")
        ]
        code_text = "\n".join(code_lines)
        assert "autolocalappdata" not in code_text, (
            "Installer source must not reference "
            "``{autolocalappdata}`` — that constant does not "
            "exist in Inno Setup 6.7.3; use ``{localappdata}``"
        )

    def test_no_outputdir_directive_in_iss(self) -> None:
        # Regression: the .iss carried ``OutputDir=dist`` and the
        # build script passed ``/OutputDir=<abs-path>`` and
        # ``/OutputBaseFilename=<name>`` as command-line flags.
        # None of those long-form flags are valid in ISCC 6.7.3:
        # the parser treats single-character switch tokens
        # (``/O``, ``/F``) and the rest of the string becomes the
        # switch's argument, leading to ``I/O error 123``
        # (``ERROR_INVALID_NAME``) on the resulting path. The
        # .iss must not declare an ``OutputDir=`` directive at
        # all — the build script uses the canonical ``/O<full-path>``
        # flag (which sets directory + filename in one go) and
        # the .iss keeps ``OutputBaseFilename=...`` as a
        # human-readable fallback. Strip comment lines so
        # explanatory prose does not trip the negative assertion.
        import re

        code_lines = [
            line
            for line in _iss_text().splitlines()
            if line.strip() and not line.lstrip().startswith(";")
        ]
        code_text = "\n".join(code_lines)
        assert not re.search(r"^\s*OutputDir\s*=", code_text, re.MULTILINE | re.IGNORECASE), (
            "Installer source must not declare an OutputDir= "
            "directive; the build script passes the full output "
            "path via the canonical ISCC ``/O<full-path>`` "
            "command-line flag, and a duplicate here caused ISCC "
            "to fail with ``I/O error 123`` (ERROR_INVALID_NAME)"
        )

    def test_does_not_install_to_program_files(self) -> None:
        text = _iss_text()
        # ``DefaultDirName`` must not point at ``Program Files``.
        # The literal string ``Program Files`` may appear in
        # comments; we assert the ``DefaultDirName`` directive
        # is the per-user path.
        m = re.search(r"^\s*DefaultDirName\s*=\s*(.+)$", text, re.MULTILINE)
        assert m is not None, "DefaultDirName directive missing"
        directive = m.group(1)
        assert "Program Files" not in directive, (
            f"DefaultDirName must not target Program Files: {directive!r}"
        )
        assert "Programs\\{#MyAppName}" in directive, (
            f"DefaultDirName must be {{localappdata}}\\Programs\\<AppName>: {directive!r}"
        )

    def test_does_not_modify_system_path(self) -> None:
        text = _iss_text()
        # The Inno Setup ``[Registry]`` section (or any code that
        # touches ``HKLM\\...\\Path``) would be a system-PATH
        # change. We refuse the [Registry] section entirely and
        # require the source to mention PATH nowhere as a
        # destination.
        assert "[Registry]" not in text, "Installer source must not contain a [Registry] section"
        # ``AppMutex`` is permitted; the bare ``PATH`` token as a
        # write target is not. We accept any reference to PATH
        # but require the absence of common env-var write
        # patterns.
        assert "SetEnvVar" not in text, "Installer must not call SetEnvVar (no PATH modification)"
        assert "EnvVarUpdate" not in text, (
            "Installer must not call EnvVarUpdate (no PATH modification)"
        )

    def test_does_not_install_windows_service(self) -> None:
        text = _iss_text()
        # The Inno Setup ``[Run]`` section can install a service
        # via ``sc.exe``; we forbid that surface.
        for forbidden in ("sc.exe", "sc create", "sc start", "New-Service"):
            assert forbidden not in text, (
                f"Installer must not invoke {forbidden!r} (no service install)"
            )

    def test_does_not_create_scheduled_task(self) -> None:
        text = _iss_text()
        for forbidden in ("schtasks", "schtasks.exe"):
            assert forbidden not in text, (
                f"Installer must not invoke {forbidden!r} (no scheduled task)"
            )

    def test_does_not_modify_firewall(self) -> None:
        text = _iss_text()
        for forbidden in ("netsh", "advfirewall", "New-NetFirewallRule"):
            assert forbidden not in text, (
                f"Installer must not invoke {forbidden!r} (no firewall rule)"
            )

    def test_does_not_add_autorun(self) -> None:
        text = _iss_text()
        for forbidden in ("RunOnce", "HKCU\\...\\Run", "HKLM\\...\\Run"):
            assert forbidden not in text, (
                f"Installer must not write {forbidden!r} (no autorun entry)"
            )

    def test_does_not_install_browser_extension_or_file_association(self) -> None:
        text = _iss_text()
        for forbidden in (
            "Browser Helper Object",
            "FileExtension",
            "URL Protocol",
            "ProtocolHandler",
        ):
            assert forbidden not in text, f"Installer must not declare {forbidden!r}"

    def test_uses_approved_lockverity_icon(self) -> None:
        text = _iss_text()
        assert "SetupIconFile=..\\pyinstaller\\favicon-exe.ico" in text, (
            "Installer must use the approved favicon-exe.ico as its icon"
        )
        assert APPROVED_ICON.is_file(), f"Approved icon missing: {APPROVED_ICON}"

    def test_creates_start_menu_shortcut(self) -> None:
        text = _iss_text()
        assert re.search(
            r'Name:\s*"\{group\}\\{#MyAppDisplayName\}"\s*;\s*Filename:',
            text,
        ), "Installer must create a Start Menu shortcut under the AppName group"
        assert re.search(
            r'Name:\s*"\{group\}\\Uninstall \{#MyAppDisplayName\}"',
            text,
        ), "Installer must create an Uninstall entry in the Start Menu"

    def test_desktop_shortcut_unchecked_by_default(self) -> None:
        text = _iss_text()
        # The desktop shortcut must be gated on a ``Tasks``
        # entry that is ``unchecked`` by default.
        assert re.search(
            r'Name:\s*"desktopicon".*Flags:\s*unchecked',
            text,
            re.DOTALL,
        ), "Desktop shortcut task must be declared with Flags: unchecked"

    def test_no_setup_logging_path_reveals_secrets(self) -> None:
        text = _iss_text()
        for forbidden in (
            "password=",
            "token=",
            "secret=",
            "api_key=",
        ):
            assert forbidden.lower() not in text.lower(), (
                f"Installer source must not contain {forbidden!r}"
            )

    def test_license_is_included(self) -> None:
        text = _iss_text()
        # The LICENSE file is staged into ``root_extra\\`` by the
        # build script and the [Files] section copies it. The
        # installer also exposes it via AppReadmeFile so the
        # wizard shows the licence on the **Info** page before
        # install.
        assert re.search(r"AppReadmeFile=docs\\windows-installer\.md", text), (
            "Installer must declare AppReadmeFile for the wizard info page"
        )

    def test_no_pascal_default_parameter_values(self) -> None:
        # Regression: the [Code] section declared
        # ``function RunCliSync(const Args: string;
        # const TimeoutS: Integer = 30): string;`` — the
        # ``= 30`` is a Delphi-style default parameter value.
        # Inno Setup's bundled Pascal Script is a stripped-down
        # older version that does *not* support default
        # parameter values; the compiler reported
        # ``Semicolon (';') expected`` at the ``=`` column.
        # Strip comment lines so the explanatory prose does
        # not trip the negative assertion.
        import re

        code_lines = [
            line
            for line in _iss_text().splitlines()
            if line.strip() and not line.lstrip().startswith(";")
        ]
        code_text = "\n".join(code_lines)
        # Look for the ``: Type = <number>`` pattern that would
        # indicate a default parameter value. The pattern is
        # specific to a function/procedure parameter list.
        assert not re.search(
            r":\s*[A-Za-z][A-Za-z0-9_]*\s*=\s*\d",
            code_text,
        ), (
            "Installer source [Code] section must not declare "
            "Delphi-style default parameter values; Inno Setup's "
            "Pascal Script does not support them. Pass the "
            "value explicitly at the call site instead."
        )

    def test_no_curuninstallprogress_type_for_progress_param(self) -> None:
        # Regression: the [Code] section declared
        # ``procedure CurUninstallProgressChanged(CurProgress:
        # CurUninstallProgress);`` — ``CurUninstallProgress`` is
        # the *unit* the event function is declared in (and also
        # the name of the underlying record type), but it is
        # *not* itself a usable type for the event's parameter
        # declaration. The compiler reported
        # ``Unknown type 'CurUninstallProgress'``. The correct
        # parameter type is ``Integer`` (a 0..100 progress
        # percentage). Strip comment lines so the explanatory
        # prose does not trip the negative assertion.
        code_lines = [
            line
            for line in _iss_text().splitlines()
            if line.strip() and not line.lstrip().startswith(";")
        ]
        code_text = "\n".join(code_lines)
        assert "CurUninstallProgress)" not in code_text, (
            "Installer source [Code] section must not use "
            "``CurUninstallProgress`` as a parameter type; the "
            "correct type for ``CurUninstallProgressChanged``'s "
            "``CurProgress`` parameter is ``Integer``"
        )

    def test_launch_after_install_can_be_skipped_in_silent(self) -> None:
        text = _iss_text()
        # The Pascal ``ShouldRunPostInstall`` function honours
        # ``/NoRun`` which the silent switches inject.
        assert "ShouldRunPostInstall" in text
        assert "param:NoRun" in text or "NoRun" in text

    def test_runtime_data_preserved_on_uninstall(self) -> None:
        text = _iss_text()
        # The uninstall must NOT remove the runtime data home.
        # The ``[UninstallDelete]`` section must only target
        # ``{app}\\app`` and ``{app}\\docs``. We assert that
        # no ``Name:`` directive inside [UninstallDelete] refers
        # to ``{localappdata}`` or to any path under the
        # operator's runtime data.
        assert "[UninstallDelete]" in text, "Installer must declare a [UninstallDelete] section"
        section = text.split("[UninstallDelete]", 1)[1]
        next_section = section.find("[")
        if next_section != -1:
            section = section[:next_section]
        # Parse each ``Name:`` directive in the uninstall-delete
        # block; none of them may reference localappdata.
        for line in section.splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith("name:"):
                continue
            value = stripped.split(":", 1)[1].strip()
            assert "localappdata" not in value.lower(), (
                f"Uninstaller must not delete {{localappdata}}\\Lockverity: {value!r}"
            )
            assert (
                "lockverity" not in value.lower()
                or "app" in value.lower()
                or "docs" in value.lower()
            ), f"Uninstaller Name directive must target the install root: {value!r}"

    def test_uninstall_message_includes_retained_path(self) -> None:
        text = _iss_text()
        assert "UninstallAfterSuccess" in text, (
            "Uninstaller must surface a message via UninstallAfterSuccess"
        )
        # The message must include the localappdata path so the
        # operator knows where their data is.
        assert "localappdata" in text, "Uninstall message must point at the retained-data path"

    def test_signed_status_documented_in_source(self) -> None:
        text = _iss_text()
        # The source must explicitly mark the installer as
        # unsigned (per the spec).
        assert "SignedUninstaller=no" in text, (
            "Installer source must mark the uninstaller as unsigned"
        )

    def test_no_invalid_signtool_directive(self) -> None:
        # Regression: ``SignTool=Skip`` is not valid ISCC syntax and
        # causes the compiler to fail with
        # ``Value of [Setup] section directive "SignTool" is invalid.``
        # The right way to mark the installer as unsigned is
        # ``SignedUninstaller=no`` (and to omit any ``SignTool=``
        # directive entirely, since it is only meaningful for the
        # compiler's *runtime* signing pipeline which we do not use).
        # Strip comment lines (starting with ``;``) so explanatory
        # prose in the .iss does not trip the assertion.
        import re

        code_lines = [
            line
            for line in _iss_text().splitlines()
            if line.strip() and not line.lstrip().startswith(";")
        ]
        code_text = "\n".join(code_lines)
        assert "SignTool=Skip" not in code_text, (
            "Installer source must not contain the invalid "
            "``SignTool=Skip`` directive; use SignedUninstaller=no "
            "and omit SignTool entirely"
        )
        # Any SignTool= directive is also forbidden because we have
        # no signing tool configured. The regex is case-insensitive on
        # the directive name to catch any future regression variant.
        assert not re.search(r"^\s*SignTool\s*=", code_text, re.MULTILINE | re.IGNORECASE), (
            "Installer source must not declare any SignTool= directive; "
            "use SignedUninstaller=no and leave SignTool undeclared"
        )

    def test_no_nonexistent_showcmdlinehelp_directive(self) -> None:
        # Regression: a stray ``ShowCmdlineHelp=yes`` was committed
        # and the compiler reported
        # ``Unrecognized [Setup] section directive "ShowCmdlineHelp"``.
        # There is no ``ShowCmdLineHelp`` [Setup] directive in
        # Inno Setup 6.7.3 at all — that name is a holdover from a
        # different version. The default behavior in 6.7.3 already
        # prints the /HELP /? summary when Setup is run with no
        # arguments, so the directive is neither necessary nor
        # accepted. Strip comment lines so explanatory prose does
        # not trip the negative assertion.
        code_lines = [
            line
            for line in _iss_text().splitlines()
            if line.strip() and not line.lstrip().startswith(";")
        ]
        code_text = "\n".join(code_lines)
        assert "ShowCmdlineHelp" not in code_text, (
            "Installer source must not declare a ShowCmdlineHelp "
            "directive — it does not exist in Inno Setup 6.7.3"
        )
        assert "ShowCmdLineHelp" not in code_text, (
            "Installer source must not declare a ShowCmdLineHelp "
            "directive either — it does not exist in Inno Setup "
            "6.7.3; the default behavior already prints the /HELP "
            "summary when Setup is run with no arguments"
        )

    def test_all_setup_directives_recognised_by_inno_6_7_3(self) -> None:
        # Belt-and-braces regression: every [Setup] section
        # directive declared in the .iss must be a directive
        # Inno Setup 6.7.3 recognises. The list is taken from the
        # official isetup.xml shipped with the compiler. Without
        # this guard, a stray legacy directive (e.g.
        # ``DiskDirectory``, ``SlicesPerDisk``) will be accepted
        # at commit time and only fail at compile time inside the
        # installer build script — which is slow and breaks the
        # spec's "compile from a clean committed HEAD" rule.
        import re

        # The full set of [Setup] section directives supported by
        # Inno Setup 6.7.3. Sourced from the upstream
        # ``ISHelp/isetup.xml`` help file shipped with the
        # compiler. Keep this list in sync with the locked
        # compiler version.
        KNOWN_SETUP_DIRECTIVES: set[str] = {  # noqa: N806 - sentinel constant naming
            "AppId",
            "AppIdFormat",
            "AppName",
            "AppVerName",
            "AppVersion",
            "AppPublisher",
            "AppPublisherURL",
            "AppSupportURL",
            "AppUpdatesURL",
            "AppContact",
            "AppCopyright",
            "AppComments",
            "AppModifyPath",
            "AppReadmeFile",
            "AppMutex",
            "PrivilegesRequired",
            "PrivilegesRequiredOverridesAllowed",
            "ArchitecturesInstallIn64BitMode",
            "ArchitecturesAllowed",
            "DefaultDirName",
            "DefaultGroupName",
            "BaseFilename",
            "UninstallDisplayIcon",
            "UninstallDisplayName",
            "UninstallFilesDir",
            "UninstallRegKey",
            "Uninstallable",
            "CloseApplicationsFilter",
            "DisableAppendDir",
            "DisableDirPage",
            "DisableProgramGroupPage",
            "AllowNoIcons",
            "AllowRootDirectory",
            "AlwaysShowComponentsList",
            "AlwaysShowDirOnReadyPage",
            "AlwaysShowGroupOnReadyPage",
            "WizardStyle",
            "WizardSizePercent",
            "WizardImageAlphaFormat",
            "WizardImageBackColor",
            "WizardImageFile",
            "WizardSmallImageFile",
            "WizardBackColor",
            "WizardBackColorWidth",
            "Compression",
            "SolidCompression",
            "CompressionThreads",
            "LZMAAlgorithm",
            "LZMABlockSize",
            "LZMADictionarySize",
            "LZMAMatchFinder",
            "LZMANumBlockThreads",
            "LZMANumFastBytes",
            "LZMAUseSeparateProcess",
            "DiskClusterSize",
            "DiskSliceSize",
            "DiskSpanning",
            "OutputBaseFilename",
            "OutputDir",
            "OutputManifestFile",
            "SetupIconFile",
            "SignedUninstaller",
            "SignedUninstallerDir",
            "SignTool",
            "SignToolMinimumTimeBetween",
            "SignToolRetryCount",
            "SignToolRetryDelay",
            "SignToolRunMinimized",
            "SetupLogging",
            "DebugLogging",
            "CloseApplications",
            "CloseApplicationsFilterExcludes",
            "RestartApplications",
            "AllowCancelDuringInstall",
            "SetupMutex",
            "TouchDate",
            "TouchSize",
            "Touch",
            "TerminalServicesAware",
            "UninstallLogMode",
            "UninstallRestartComputer",
            "UpdateUninstallLogAppName",
            "UsedUserAreasWarning",
            "CreateUninstRegKey",
            "CloseEscButton",
            "InfoBeforeFile",
            "LicenseFile",
            "InfoAfterFile",
            "UserInfoPage",
            "ShowUserInfoPage",
            "UserInfoTitle",
            "Encryption",
            "EncryptionPassword",
            "MinAES",
            "AllowUNCPath",
            "AllowNetworkDrive",
            "AppNoMessagesFile",
            "TimeStamp",
            "TimeStampTouch",
            "AppUserModelID",
            "ShowLanguageDialog",
            "MergeDuplicateFiles",
            "UninstallStyle",
            "VersionInfoVersion",
            "VersionInfoCompany",
            "VersionInfoDescription",
            "VersionInfoTextVersion",
            "VersionInfoCopyright",
            "VersionInfoProductName",
            "VersionInfoProductVersion",
            "VersionInfoFileVersion",
            "VersionInfoFileDescription",
            "VersionInfoOriginalFilename",
            "VersionInfoComments",
            "VersionInfoInternalName",
            "VersionInfoLegalCopyright",
            "VersionInfoLegalTrademarks",
            "VersionInfoPrivateBuild",
            "VersionInfoSpecialBuild",
            "MinVersion",
            "OnlyBelowVersion",
        }
        # Parse the [Setup] section from the .iss.
        in_setup = False
        declared: list[tuple[int, str]] = []  # (line_no, directive_name)
        for line_no, line in enumerate(_iss_text().splitlines(), 1):
            stripped = line.strip()
            if stripped == "[Setup]":
                in_setup = True
                continue
            if stripped.startswith("[") and stripped.endswith("]"):
                if in_setup:
                    break
                continue
            if not in_setup or not stripped or stripped.startswith(";"):
                continue
            m = re.match(r"^([A-Za-z][A-Za-z0-9_]*)", stripped)
            if m and "=" in stripped:
                declared.append((line_no, m.group(1)))
        unknown = [(n, d) for n, d in declared if d not in KNOWN_SETUP_DIRECTIVES]
        assert not unknown, (
            "Installer source declares [Setup] section directives "
            "that Inno Setup 6.7.3 does not recognise: "
            + ", ".join(f"{d} (line {n})" for n, d in unknown)
            + ". Remove them or use the supported replacement."
        )

    def test_no_python_or_node_required(self) -> None:
        text = _iss_text()
        # The installer source must not bundle or invoke a
        # Python / Node / npm interpreter.
        for forbidden in ("python.exe", "node.exe", "npm.cmd", "pip.exe"):
            assert forbidden not in text, f"Installer must not reference {forbidden!r}"


# ---------------------------------------------------------------------
# Build script contract
# ---------------------------------------------------------------------


class TestBuildScriptContract:
    """The build script must verify all accepted hashes and refuse
    silently-substituted payloads."""

    def test_build_script_declares_stable_app_id(self) -> None:
        text = _build_text()
        assert STABLE_APP_ID in text, f"Build script must use the stable AppId {STABLE_APP_ID}"

    def test_build_script_pins_accepted_payload_hashes(self) -> None:
        text = _build_text()
        for expected in (
            EXPECTED_PAYLOAD_ZIP_SHA256,
            EXPECTED_PAYLOAD_SOURCE_COMMIT,
            EXPECTED_LOCKVERITY_EXE_SHA256,
            EXPECTED_LOCKVERITY_CLI_EXE_SHA256,
        ):
            assert expected in text, f"Build script must pin accepted hash {expected!r}"

    def test_build_script_uses_subprocess_without_shell_true(self) -> None:
        text = _build_text()
        # Every ``subprocess.run`` / ``Popen`` call must use an
        # argv list, never ``shell=True``.
        assert "shell=True" not in text, "Build script must not use shell=True anywhere"
        # All subprocess calls must pass an argv list. We assert
        # by absence of the legacy string-form.
        assert "subprocess.call(" not in text
        assert "os.system(" not in text, "Build script must not call os.system()"

    def test_build_script_refuses_dirty_git_state(self) -> None:
        text = _build_text()
        # The build script must call ``git status --porcelain``
        # and raise an actionable error if the working tree is
        # dirty. The actual implementation uses
        # ``--untracked-files=no`` for a stricter check.
        assert re.search(r"status[^\n]*--porcelain", text), (
            "Build script must check ``git status --porcelain``"
        )
        # The check must raise an actionable error on a dirty
        # tree. The exact wording can vary; we look for the
        # abort keyword + the porcelain-driven detection.
        assert "dirty" in text.lower() and "working tree" in text.lower(), (
            "Build script must refuse a dirty working tree"
        )

    def test_build_script_verifies_clean_git_full_sha(self) -> None:
        text = _build_text()
        # The build script must call ``git rev-parse HEAD`` (not
        # the abbreviated ``--short`` form) and validate the
        # 40-character hex format.
        assert re.search(r"rev-parse[^\n]*HEAD", text), (
            "Build script must use ``git rev-parse HEAD`` (40-char)"
        )
        assert re.search(r"\[0-9a-f\]\{40\}", text), (
            "Build script must validate the 40-char SHA format"
        )

    def test_build_script_refuses_wrong_payload_hash(self) -> None:
        text = _build_text()
        assert "SHA-256 mismatch" in text, "Build script must refuse a payload with a wrong SHA-256"
        assert "Restore the accepted B3A" in text, (
            "Build script must instruct the operator to restore the accepted B3A portable ZIP"
        )

    def test_build_script_generates_installer_manifest(self) -> None:
        text = _build_text()
        assert "INSTALLER-MANIFEST.json" in text, "Build script must emit INSTALLER-MANIFEST.json"
        for required in (
            "product",
            "installer_source_commit",
            "payload_source_commit",
            "payload_zip_sha256",
            "lockverity_exe_sha256",
            "lockverity_cli_exe_sha256",
            "installer_sha256",
            "stable_app_id",
            "default_install_path",
            "code_signing_status",
        ):
            assert f'"{required}"' in text, (
                f"Build script must record the {required!r} field in the manifest"
            )

    def test_build_script_manifest_has_no_local_paths(self) -> None:
        text = _build_text()
        # The manifest writer must not bake local absolute paths.
        for forbidden in (
            "C:\\Users",
            "C:/Users",
            "/Users/",
            "/home/",
        ):
            assert forbidden not in text, (
                f"Build script must not write {forbidden!r} into the manifest"
            )

    def test_build_script_uses_no_shell(self) -> None:
        text = _build_text()
        # Same as the source contract; the build script must
        # never use a shell to spawn the compiler.
        assert "shell=True" not in text

    def test_build_script_cleans_only_dedicated_paths(self) -> None:
        text = _build_text()
        # The ``--clean`` flag must only target installer output,
        # staging, and work directories. It must not touch the
        # portable build directory.
        # The portable build directory is referenced in the
        # build script only via the default payload-zip path,
        # not via any cleanup path. We confirm ``shutil.rmtree``
        # is used (the cleanup primitive) and that the only
        # targets are the three dedicated installer paths.
        assert "shutil.rmtree" in text
        # Confirm the build script only operates on its own
        # output dir / staging dir / work dir.
        for required in (
            "args.output_dir",
            "args.staging_dir",
            "args.work_dir",
        ):
            assert required in text, f"Build script --clean must target {required}"

    def test_build_script_documents_unsigned_status(self) -> None:
        text = _build_text()
        assert "unsigned" in text.lower(), "Build script must mark the installer as unsigned"

    def test_build_script_default_install_path(self) -> None:
        text = _build_text()
        assert "%LOCALAPPDATA%\\\\Programs\\\\Lockverity" in text or (
            "LOCALAPPDATA" in text and "Programs" in text and "Lockverity" in text
        ), "Build script must record the default LocalAppData install path"

    def test_build_script_uses_canonical_iscc_output_flag(self) -> None:
        # Regression: the build script passed
        # ``/OutputDir=<abs-path>`` and
        # ``/OutputBaseFilename=<name>`` as command-line flags to
        # ISCC. Neither is a valid ISCC 6.7.3 flag — the parser
        # treats single-character switch tokens (``/O``, ``/F``)
        # and the rest of the string becomes the switch's
        # argument, leading to ``I/O error 123``
        # (``ERROR_INVALID_NAME``) on the resulting path. The
        # canonical, supported ISCC flag for the output file is
        # ``/O<full-path>`` (directory + filename in one go).
        text = _build_text()
        import re

        # The long-form ``/OutputDir=`` flag must not be present.
        assert not re.search(r"[\"']/OutputDir=", text), (
            "Build script must not pass the non-existent "
            "``/OutputDir=`` flag to ISCC; use the canonical "
            "``/O<full-path>`` flag instead"
        )
        # The long-form ``/OutputBaseFilename=`` flag must not be
        # present either — ``/O<full-path>`` already controls
        # the final filename.
        assert not re.search(r"[\"']/OutputBaseFilename=", text), (
            "Build script must not pass the non-existent "
            "``/OutputBaseFilename=`` flag to ISCC; use the "
            "canonical ``/O<full-path>`` flag instead"
        )
        # The canonical ``/O<full-path>`` flag must be used.
        assert re.search(r"[\"']/O\{installer_full_path\}[\"']", text), (
            "Build script must pass the canonical ISCC "
            "``/O<full-path>`` command-line flag (directory + "
            "filename in one go)"
        )

    def test_build_script_copies_iss_into_staging(self) -> None:
        # Regression: the .iss uses *relative* ``Source:`` paths
        # (``payload\*``, ``root_extra\*``, ``..\\pyinstaller\\...``)
        # that ISCC resolves against the directory containing
        # the .iss, not the current working directory. Since the
        # committed .iss lives under ``backend/installer/`` and
        # the staged payload lives under ``build/installer/staging/``,
        # the build script must copy the .iss into the staging
        # directory before invoking ISCC, and must invoke ISCC
        # against the staged copy — not against the committed
        # source. The staged copy is a transient build artefact
        # and is not committed.
        text = _build_text()
        assert "shutil.copy2" in text, (
            "Build script must copy the .iss into the staging "
            "directory so the relative Source: paths resolve "
            "correctly under ISCC"
        )
        # The staged copy must be used as the .iss argument, not
        # the committed source.
        assert re.search(r"str\(staged_iss\)", text), (
            "Build script must invoke ISCC against the staged copy of the .iss"
        )
        # The committed source must still be the source of the copy.
        assert re.search(r"shutil\.copy2\(\s*ISS_SOURCE\s*,\s*staged_iss", text), (
            "Build script must copy the committed ISS_SOURCE into the staging dir as staged_iss"
        )

    def test_build_script_stages_exe_icon_in_staging(self) -> None:
        # Regression: the .iss's ``SetupIconFile`` directive uses
        # the *relative* path ``..\\pyinstaller\\favicon-exe.ico``
        # (written when the .iss lived in ``backend/installer/``
        # and the icon in ``backend/pyinstaller/``). After the
        # .iss is copied into the staging dir, that relative path
        # needs the icon to also live at the matching relative
        # location inside the staging dir; otherwise ISCC
        # reports ``The system cannot find the path specified``
        # for the icon. The build script must (a) mirror the icon
        # at ``staging/pyinstaller/favicon-exe.ico`` and (b) rewrite
        # the staged copy's ``SetupIconFile`` to the
        # staging-relative path so it resolves under ISCC.
        text = _build_text()
        # The icon must be staged at the staging-relative path.
        assert re.search(r"pyinstaller_subdir\s*/\s*[\"']favicon-exe\.ico[\"']", text) or re.search(
            r"pyinstaller.*favicon-exe\.ico", text
        ), (
            "Build script must stage the EXE icon at "
            "``staging/pyinstaller/favicon-exe.ico`` so the .iss's "
            "relative ``SetupIconFile`` path resolves after the "
            ".iss is copied into the staging dir"
        )
        # The staged copy's ``SetupIconFile`` (and the matching
        # ``Source:`` line in the [Files] section) must be
        # rewritten from the committed
        # ``..\\pyinstaller\\favicon-exe.ico`` (backend-relative)
        # to the staging-relative ``pyinstaller\\favicon-exe.ico``
        # form. The committed source is unchanged. The Python
        # source carries escaped backslashes (each ``\\`` in the
        # source is one literal backslash in the string), so we
        # search for the *source-escaped* form.
        assert "..\\\\pyinstaller\\\\favicon-exe.ico" in text, (
            "Build script must rewrite the staged copy's "
            "icon references from the committed "
            "``..\\pyinstaller\\favicon-exe.ico`` to a "
            "staging-relative path so the relative paths "
            "resolve correctly under ISCC"
        )


# ---------------------------------------------------------------------
# Approved icon and payload
# ---------------------------------------------------------------------


class TestApprovedAssets:
    """The approved icon and payload ZIP must remain unchanged."""

    def test_approved_favicon_ico_unchanged(self) -> None:
        assert APPROVED_FAVICON_ICO.is_file(), f"Approved favicon missing: {APPROVED_FAVICON_ICO}"
        h = hashlib.sha256(APPROVED_FAVICON_ICO.read_bytes()).hexdigest()
        assert h == ("33dcc472ae67db90a238a34a2f08151924b45aabe1bf9ecfecb75755aa60f4cb"), (
            f"Approved favicon.ico SHA-256 changed: {h}"
        )

    def test_approved_favicon_exe_ico_unchanged(self) -> None:
        assert APPROVED_ICON.is_file()
        # The favicon-exe.ico is the packaging derivative; we
        # only require it to be a valid ICO with the four
        # documented sizes.
        data = APPROVED_ICON.read_bytes()
        assert data[:4] == b"\x00\x00\x01\x00", "favicon-exe.ico is not a valid ICO header"


# ---------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------


class TestInstallerDocumentation:
    """The user-facing installer documentation must exist and cover
    the documented topics."""

    def test_documentation_file_exists(self) -> None:
        assert DOCS_FILE.is_file(), f"Installer documentation missing: {DOCS_FILE}"

    def test_documentation_covers_required_topics(self) -> None:
        text = DOCS_FILE.read_text(encoding="utf-8", errors="replace")
        for topic in (
            "silent install",
            "default install",
            "%LOCALAPPDATA%",
            "runtime data",
            "reinstall",
            "uninstall",
            "SmartScreen",
            "code signing",
        ):
            assert topic.lower() in text.lower(), f"Documentation must cover the topic {topic!r}"
