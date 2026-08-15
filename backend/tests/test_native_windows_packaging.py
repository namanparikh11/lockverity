"""Static packaging contracts for the native Windows desktop shell."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


def test_runtime_dependency_pins_pywebview() -> None:
    project = (BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"pywebview==6.2.1"' in project


def test_graphical_spec_collects_edgechromium_runtime() -> None:
    spec = (BACKEND_ROOT / "pyinstaller" / "lockverity.spec").read_text(encoding="utf-8")
    assert '"webview"' in spec
    assert '"webview.platforms.edgechromium"' in spec
    assert "console=False" in spec
    assert "favicon-exe.ico" in spec


def test_cli_spec_remains_console_only_without_webview_import() -> None:
    spec = (BACKEND_ROOT / "pyinstaller" / "cli.spec").read_text(encoding="utf-8")
    assert "console=True" in spec
    assert "webview.platforms.edgechromium" not in spec


def test_portable_builder_merges_native_gui_pyinstaller_payload() -> None:
    builder = (BACKEND_ROOT / "scripts" / "build_windows_portable.py").read_text(encoding="utf-8")
    assert 'launcher_spec = PYINSTALLER_DIR / "lockverity.spec"' in builder
    assert "_pyinstaller_build(" in builder
    assert "source_layout=pyinstaller_out" in builder
    assert 'frozen_executables=["Lockverity.exe", "lockverity-cli.exe"]' in builder


def test_installer_embeds_and_conditionally_runs_official_webview2_bootstrapper() -> None:
    source = (BACKEND_ROOT / "installer" / "lockverity.iss").read_text(encoding="utf-8")
    assert 'Source: "webview2\\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy' in source
    assert "function WebView2RuntimeInstalled: Boolean;" in source
    assert "F3017226-FE2A-4295-8BDF-00C3A9A7E4C5" in source
    assert "function EnsureWebView2Runtime: string;" in source
    assert "ExtractTemporaryFile(WEBVIEW2_BOOTSTRAPPER)" in source
    assert "'/silent /install'" in source
    assert "Result := EnsureWebView2Runtime();" in source


def test_installer_builder_uses_microsoft_fwlink_and_authenticode_gate() -> None:
    builder = (BACKEND_ROOT / "scripts" / "build_windows_installer.py").read_text(encoding="utf-8")
    assert "https://go.microsoft.com/fwlink/p/?LinkId=2124703" in builder
    assert "Get-AuthenticodeSignature" in builder
    assert "LOCKVERITY_AUTHENTICODE_TARGET" in builder
    assert "$args[0]" not in builder
    assert 'status != "Valid"' in builder
    assert '"Microsoft Corporation" not in subject' in builder
    assert '"webview2_bootstrapper_sha256"' in builder
    assert "WEBVIEW2_BOOTSTRAPPER_MAX_BYTES" in builder


def test_installer_shortcuts_still_target_native_gui_and_cli_is_preserved() -> None:
    source = (BACKEND_ROOT / "installer" / "lockverity.iss").read_text(encoding="utf-8")
    assert '#define MyAppExeName "Lockverity.exe"' in source
    assert '#define MyAppCliExeName "lockverity-cli.exe"' in source
    assert 'Name: "{group}\\{#MyAppDisplayName}"' in source
    assert 'Filename: "{app}\\{#MyAppPayloadDir}\\{#MyAppExeName}"' in source


def test_published_release_materials_are_not_build_inputs_for_webview2() -> None:
    builder = (BACKEND_ROOT / "scripts" / "build_windows_installer.py").read_text(encoding="utf-8")
    assert "checkpoint-v2.1.2-public-release" not in builder
    assert "SignPath" not in builder
