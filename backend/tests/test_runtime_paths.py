"""Tests for the v2.1 Part B3A frozen-resource resolver.

The tests in this module exercise ``app.runtime_paths``
in both the source mode (the pytest process itself,
which never sets ``sys._MEIPASS``) and the frozen
mode (simulated via ``monkeypatch.setattr(sys, ...,
...)``).

The tests are deliberately small and do not need
PyInstaller to be installed; they are a pure-Python
unit test of the resolver's branching.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from app import runtime_paths


class TestSourceMode:
    """The resolver returns the source-checkout paths.

    The pytest process is a source process; these
    tests verify the documented source-mode
    contract.
    """

    def setup_method(self) -> None:
        # Make sure no frozen-mode attribute is set;
        # the test runner is a source process by
        # construction.
        assert not runtime_paths.is_frozen()

    def test_is_source(self) -> None:
        assert runtime_paths.is_source() is True
        assert runtime_paths.is_frozen() is False

    def test_source_root_is_repo_root(self) -> None:
        # The source root is the parent of ``backend``,
        # i.e. the repository root.
        root = runtime_paths.source_root()
        assert (root / "backend").is_dir()
        assert (root / "frontend").is_dir()

    def test_frontend_dist_path_source(self) -> None:
        # In source mode the dist is at
        # ``<repo_root>/frontend/dist``.
        path = runtime_paths.frontend_dist_path()
        assert path.name == "dist"
        assert path.parent.name == "frontend"

    def test_frozen_root_raises_in_source(self) -> None:
        with pytest.raises(RuntimeError, match="PyInstaller"):
            runtime_paths.frozen_root()

    def test_frozen_exe_dir_raises_in_source(self) -> None:
        with pytest.raises(RuntimeError, match="PyInstaller"):
            runtime_paths.frozen_exe_dir()

    def test_alembic_paths_source(self) -> None:
        cfg = runtime_paths.alembic_config_path()
        versions = runtime_paths.alembic_versions_dir()
        assert cfg.name == "alembic.ini"
        assert versions.name == "versions"

    def test_favicon_and_brand_paths(self) -> None:
        # The source-mode paths point at the
        # repository's approved assets. The exact
        # path under public/ is the Part A contract.
        assert runtime_paths.favicon_path().name == "favicon.ico"
        assert runtime_paths.brand_symbol_path().name == "lockverity-symbol.png"


def _build_synthetic_bundle(bundle: Path) -> None:
    """Populate ``bundle`` with the documented frozen layout."""
    (bundle / "frontend" / "dist" / "assets").mkdir(parents=True)
    (bundle / "frontend" / "dist" / "index.html").write_text(
        "<!doctype html><html><body></body></html>", encoding="utf-8"
    )
    (bundle / "alembic" / "versions").mkdir(parents=True)
    (bundle / "alembic.ini").write_text("[alembic]\npath_separator = os\n", encoding="utf-8")
    (bundle / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")
    (bundle / "brand").mkdir()
    (bundle / "brand" / "lockverity-symbol.png").write_bytes(b"\x89PNG")
    (bundle / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (bundle / "README-PORTABLE.txt").write_text("Readme\n", encoding="utf-8")


@pytest.fixture
def frozen_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a synthetic frozen bundle and patch ``sys`` accordingly.

    The fixture is the documented entry point for any
    test that needs the resolver in frozen mode. The
    teardown restores the original ``sys.frozen`` and
    ``sys._MEIPASS`` values.
    """
    bundle = tmp_path / "lockverity-fake-bundle"
    bundle.mkdir()
    _build_synthetic_bundle(bundle)
    # ``monkeypatch.setattr`` is the documented way to
    # mutate ``sys`` attributes from a test; the
    # function restores the original value on teardown.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    return bundle


class TestFrozenMode:
    """The resolver returns ``sys._MEIPASS`` paths when frozen.

    The tests use the :func:`frozen_bundle` fixture to
    inject a synthetic bundle root and patch the two
    ``sys`` attributes PyInstaller sets at launch.
    """

    def test_is_frozen(self, frozen_bundle: Path) -> None:
        assert runtime_paths.is_frozen() is True
        assert runtime_paths.is_source() is False

    def test_frozen_root_returns_meipass(self, frozen_bundle: Path) -> None:
        assert runtime_paths.frozen_root() == frozen_bundle.resolve()

    def test_application_root_uses_frozen_in_frozen_mode(self, frozen_bundle: Path) -> None:
        assert runtime_paths.application_root() == frozen_bundle.resolve()

    def test_frontend_dist_path_frozen(self, frozen_bundle: Path) -> None:
        path = runtime_paths.frontend_dist_path()
        assert path == frozen_bundle / "frontend" / "dist"
        assert (path / "index.html").is_file()

    def test_alembic_paths_frozen(self, frozen_bundle: Path) -> None:
        assert runtime_paths.alembic_config_path() == frozen_bundle / "alembic.ini"
        assert runtime_paths.alembic_versions_dir() == frozen_bundle / "alembic" / "versions"

    def test_favicon_path_frozen(self, frozen_bundle: Path) -> None:
        assert runtime_paths.favicon_path() == frozen_bundle / "favicon.ico"

    def test_brand_path_frozen(self, frozen_bundle: Path) -> None:
        assert (
            runtime_paths.brand_symbol_path() == frozen_bundle / "brand" / "lockverity-symbol.png"
        )

    def test_license_and_readme_frozen(self, frozen_bundle: Path) -> None:
        assert runtime_paths.license_path() == frozen_bundle / "LICENSE"
        assert runtime_paths.portable_readme_path() == frozen_bundle / "README-PORTABLE.txt"

    def test_source_root_raises_in_frozen(self, frozen_bundle: Path) -> None:
        with pytest.raises(RuntimeError, match="PyInstaller"):
            runtime_paths.source_root()

    def test_frozen_exe_dir_returns_exe_parent(
        self, frozen_bundle: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The frozen exe dir is the parent of
        # ``sys.executable``; the fixture pins the
        # attribute to the bundle parent so the test
        # works on every host.
        monkeypatch.setattr(sys, "executable", str(frozen_bundle / "Lockverity.exe"))
        assert runtime_paths.frozen_exe_dir() == frozen_bundle
