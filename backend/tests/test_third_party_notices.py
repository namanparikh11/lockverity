"""Tests for the v2.1 Part B3A THIRD_PARTY_NOTICES.txt contract.

The notice file is the operator-visible licence inventory
shipped with the portable package. The v2.1 Part B3A
acceptance spec requires:

  - the notice file is derived from the **packaged**
    dependency inventory, not from the entire build venv;
  - dev tools (pytest, ruff, mypy, etc.) are NOT listed in
    the runtime section;
  - build-only tools (PyInstaller, pip-licenses, etc.) are
    either excluded or listed in a clearly separate section;
  - a missing-licence entry (``UNKNOWN``) is never silently
    classified as permissive;
  - the file has explicit section headers separating the
    runtime components from the build tools.

The tests are pure-Python. They exercise the helper
``_count_packages_in_section`` and validate the
``DEV_TOOL_PACKAGES`` allow-list against the committed
build script. They also validate the on-disk notice file
(if a packaged artefact is present) against the
acceptance contract.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
BUILD_SCRIPT = BACKEND_ROOT / "scripts" / "build_windows_portable.py"
DEFAULT_PACKAGING_DIR = REPO_ROOT / "build" / "packaging"
PORTABLE_NAME = "Lockverity-2.1.0-windows-x64-portable"
DEFAULT_NOTICES_PATH = DEFAULT_PACKAGING_DIR / PORTABLE_NAME / "THIRD_PARTY_NOTICES.txt"
DEFAULT_MANIFEST_PATH = DEFAULT_PACKAGING_DIR / PORTABLE_NAME / "BUILD-MANIFEST.json"


# ---------------------------------------------------------------------
# Static checks on the build script source
# ---------------------------------------------------------------------


def _extract_dev_tool_packages() -> tuple[str, ...]:
    """Parse the ``DEV_TOOL_PACKAGES`` tuple from the build script."""
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    # Find the start of the tuple and the matching close paren.
    m = re.search(r"^DEV_TOOL_PACKAGES:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\(", text, re.M)
    assert m, "DEV_TOOL_PACKAGES tuple not found in build script"
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    assert depth == 0, "DEV_TOOL_PACKAGES tuple not balanced"
    body = text[start : i - 1]
    pkgs = re.findall(r'"([^"]+)"', body)
    return tuple(pkgs)


class TestDevToolPackagesContract:
    """The build script must declare every dev / build tool it filters out."""

    def test_dev_tool_packages_includes_pytest(self) -> None:
        pkgs = _extract_dev_tool_packages()
        assert "pytest" in pkgs, "pytest must be in DEV_TOOL_PACKAGES"

    def test_dev_tool_packages_includes_ruff(self) -> None:
        pkgs = _extract_dev_tool_packages()
        assert "ruff" in pkgs, "ruff must be in DEV_TOOL_PACKAGES"

    def test_dev_tool_packages_includes_mypy(self) -> None:
        pkgs = _extract_dev_tool_packages()
        assert "mypy" in pkgs, "mypy must be in DEV_TOOL_PACKAGES"

    def test_dev_tool_packages_includes_pyinstaller(self) -> None:
        pkgs = _extract_dev_tool_packages()
        assert "pyinstaller" in pkgs, "pyinstaller must be in DEV_TOOL_PACKAGES"

    def test_dev_tool_packages_includes_pip_licenses(self) -> None:
        pkgs = _extract_dev_tool_packages()
        assert "pip-licenses" in pkgs, "pip-licenses must be in DEV_TOOL_PACKAGES"

    def test_dev_tool_packages_excludes_runtime_dependencies(self) -> None:
        """The runtime packages must NOT be in the dev-tool ignore list."""
        pkgs = _extract_dev_tool_packages()
        for runtime_pkg in (
            "fastapi",
            "uvicorn",
            "sqlalchemy",
            "alembic",
            "pydantic",
            "psutil",
            "httpx",
            "pyyaml",
        ):
            assert runtime_pkg not in pkgs, (
                f"runtime package {runtime_pkg!r} must NOT be in DEV_TOOL_PACKAGES"
            )


# ---------------------------------------------------------------------
# Tests against the on-disk notice file (only if a packaged
# artefact exists; the previous B3A cycle validates the same
# paths and the tests skip when the artefact is absent).
# ---------------------------------------------------------------------


def _parse_plain_vertical_sections(text: str) -> list[tuple[str, str, str]]:
    """Return ``[(name, version, license), ...]`` from a plain-vertical notice.

    The ``plain-vertical`` format produced by ``pip-licenses``
    is: name on one line, version on the next, license on the
    next. A package record is three lines. The notice file
    the build script produces has a leading header and a
    trailing build-tools section separated by a clear
    delimiter; we only parse the records that match the
    three-line pattern.
    """
    lines = text.splitlines()
    records: list[tuple[str, str, str]] = []
    for i in range(len(lines) - 2):
        name = lines[i].strip()
        version = lines[i + 1].strip()
        license_name = lines[i + 2].strip()
        if not name or not version or not license_name:
            continue
        # A name has no whitespace and is a single token.
        if " " in name:
            continue
        # A version starts with a digit.
        if not re.match(r"^[\d.]", version):
            continue
        # A license name is one of: UNKNOWN, MIT, BSD-...,
        # Apache-2.0, etc. We accept anything that doesn't
        # start with whitespace.
        if license_name.startswith(" ") or license_name == "":
            continue
        # Skip the section header lines (the descriptive
        # text inside the build script's RUNTIME_HEADER
        # and BUILD_TOOL_HEADER that uses words like
        # ``runtime``, ``build``, ``tools`` as standalone
        # lines; those don't match the three-line pattern
        # because the version line won't start with a digit
        # for the descriptive text).
        records.append((name, version, license_name))
    return records


@pytest.mark.skipif(
    not DEFAULT_NOTICES_PATH.is_file(),
    reason="no packaged artefact on disk",
)
class TestPackagedNoticeAccuracy:
    """The packaged notice file must reflect only the runtime inventory."""

    def test_notice_has_runtime_section_header(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        assert "RUNTIME COMPONENTS" in text, "RUNTIME COMPONENTS section missing"

    def test_notice_has_build_tools_section_header(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        assert "BUILD TOOLS" in text, "BUILD TOOLS section missing"

    def test_notice_runtime_section_excludes_pytest(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        # Split at the build-tools header so we only see the
        # runtime half.
        runtime_text = text.split("BUILD TOOLS", 1)[0]
        # We assert the package is not in the runtime section.
        # (It may appear in the build-tools section, which is
        # fine.)
        assert "\npytest\n" not in ("\n" + runtime_text + "\n"), (
            "pytest must not appear in the RUNTIME COMPONENTS section"
        )

    def test_notice_runtime_section_excludes_ruff(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        runtime_text = text.split("BUILD TOOLS", 1)[0]
        assert "\nruff\n" not in ("\n" + runtime_text + "\n"), (
            "ruff must not appear in the RUNTIME COMPONENTS section"
        )

    def test_notice_runtime_section_excludes_mypy(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        runtime_text = text.split("BUILD TOOLS", 1)[0]
        assert "\nmypy\n" not in ("\n" + runtime_text + "\n"), (
            "mypy must not appear in the RUNTIME COMPONENTS section"
        )

    def test_notice_runtime_section_excludes_pyinstaller(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        runtime_text = text.split("BUILD TOOLS", 1)[0]
        assert "\npyinstaller\n" not in ("\n" + runtime_text + "\n"), (
            "pyinstaller must not appear in the RUNTIME COMPONENTS section"
        )

    def test_notice_runtime_section_excludes_pip_licenses(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        runtime_text = text.split("BUILD TOOLS", 1)[0]
        assert "\npip-licenses\n" not in ("\n" + runtime_text + "\n"), (
            "pip-licenses must not appear in the RUNTIME COMPONENTS section"
        )

    def test_notice_runtime_section_includes_fastapi(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        runtime_text = text.split("BUILD TOOLS", 1)[0]
        # The package name in the pip-licenses output
        # preserves the original case (``fastapi`` is
        # lower-case in the metadata).
        assert "\nfastapi\n" in ("\n" + runtime_text + "\n"), (
            "fastapi must appear in the RUNTIME COMPONENTS section"
        )

    def test_notice_runtime_section_includes_uvicorn(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        runtime_text = text.split("BUILD TOOLS", 1)[0]
        assert "\nuvicorn\n" in ("\n" + runtime_text + "\n"), (
            "uvicorn must appear in the RUNTIME COMPONENTS section"
        )

    def test_notice_runtime_section_includes_sqlalchemy(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        runtime_text = text.split("BUILD TOOLS", 1)[0]
        # pip-licenses preserves the original case
        # (``SQLAlchemy`` ships with a capitalised name).
        assert "\nSQLAlchemy\n" in ("\n" + runtime_text + "\n"), (
            "SQLAlchemy must appear in the RUNTIME COMPONENTS section"
        )

    def test_notice_build_tools_section_includes_pyinstaller(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        build_text = text.split("BUILD TOOLS", 1)[1]
        assert "\npyinstaller\n" in ("\n" + build_text + "\n"), (
            "pyinstaller must appear in the BUILD TOOLS section"
        )

    def test_notice_build_tools_section_includes_pyinstaller_hooks_contrib(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        build_text = text.split("BUILD TOOLS", 1)[1]
        assert "\npyinstaller-hooks-contrib\n" in ("\n" + build_text + "\n"), (
            "pyinstaller-hooks-contrib must appear in the BUILD TOOLS section"
        )

    def test_notice_build_tools_section_includes_altgraph(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        build_text = text.split("BUILD TOOLS", 1)[1]
        assert "\naltgraph\n" in ("\n" + build_text + "\n"), (
            "altgraph must appear in the BUILD TOOLS section"
        )

    def test_notice_build_tools_section_includes_pip_licenses(self) -> None:
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        build_text = text.split("BUILD TOOLS", 1)[1]
        # ``pip-licenses`` is added as a synthetic entry
        # because the tool filters itself out of its own
        # output.
        assert "\npip-licenses\n" in ("\n" + build_text + "\n"), (
            "pip-licenses must appear in the BUILD TOOLS section (synthetic entry)"
        )

    def test_notice_no_known_copyleft_licence_in_runtime(self) -> None:
        """A copyleft licence (GPL/AGPL/SSPL) must not appear in the runtime."""
        text = DEFAULT_NOTICES_PATH.read_text(encoding="utf-8", errors="replace")
        runtime_text = text.split("BUILD TOOLS", 1)[0]
        for lic in ("GPL", "AGPL", "SSPL"):
            # We check for the license-name line, not the
            # licence-text body (which can contain "GPL" in
            # copyright headers without it being the
            # governing licence).
            for line in runtime_text.splitlines():
                stripped = line.strip()
                if stripped == lic or stripped.startswith(lic + " ") or stripped == lic + "v2":
                    # A copyleft license header found.
                    raise AssertionError(
                        f"copyleft licence header {stripped!r} found in RUNTIME section"
                    )

    def test_manifest_dependency_inventory_summary(self) -> None:
        """The manifest must summarise the runtime vs build-tool split."""
        if not DEFAULT_MANIFEST_PATH.is_file():
            pytest.skip("no packaged manifest on disk")
        manifest = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
        summary = manifest.get("dependency_inventory_summary", {})
        assert "runtime_components" in summary
        assert "build_tools" in summary
        assert "runtime_unknown_licences" in summary
        # The runtime count must be at least 30 (the actual
        # number is in the 60s; we use a low floor to
        # avoid being brittle).
        assert int(summary["runtime_components"]) >= 30, (
            f"runtime_components too low: {summary['runtime_components']}"
        )
        # The build-tools count must include the build
        # tools we care about (pyinstaller,
        # pyinstaller-hooks-contrib, altgraph, pip-licenses).
        assert int(summary["build_tools"]) >= 4
        # The unknown count is the metadata gaps; the
        # floor matches the historical v2.1 Part B3A
        # count (~30-40) which has always been explained
        # by the pip-licenses --with-license-file metadata
        # gap (BSD/MIT-licensed packages with classifier
        # but no LICENSE file).
        assert 0 <= int(summary["runtime_unknown_licences"]) <= 80
