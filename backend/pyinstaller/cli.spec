# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Lockverity console CLI.

This spec produces the v2.1 Part B3A ``lockverity-cli.exe``
console command. The CLI is the cross-platform
``lockverity`` command surface wrapped in a Windows
executable; the same ``main`` function is exposed as
``python -m app.cli`` for source-based usage.

The CLI build is one of two PyInstaller outputs in the
v2.1 Part B3A portable package. The other is
``lockverity.spec`` (the graphical launcher build). The
two specs share the same data files but differ in
``console=True`` (this spec) vs ``console=False`` (the
launcher spec) and the entry point module.
"""

from pathlib import Path

BACKEND_ROOT = Path(SPECPATH).resolve().parent  # type: ignore[name-defined]  # noqa: F821
REPO_ROOT = BACKEND_ROOT.parent

FROZEN_BUNDLE_DATA: list[tuple[str, str]] = [
    (str(REPO_ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(BACKEND_ROOT / "alembic.ini"), "alembic.ini"),
    (str(BACKEND_ROOT / "alembic"), "alembic"),
    (str(REPO_ROOT / "frontend" / "public" / "favicon.ico"), "favicon.ico"),
    (str(REPO_ROOT / "frontend" / "public" / "brand"), "brand"),
    (str(REPO_ROOT / "LICENSE"), "LICENSE"),
    (str(REPO_ROOT / "docs" / "windows-portable.md"), "README-PORTABLE.txt"),
]

HIDDENIMPORTS: list[str] = [
    "alembic.runtime.migration",
    "alembic.operations.ops",
    "psutil",
    "psutil._pswindows",
    "psutil._psutil_windows",
]


a = Analysis(  # type: ignore[name-defined]  # noqa: F821
    [str(BACKEND_ROOT / "app" / "cli" / "__main__.py")],
    pathex=[str(BACKEND_ROOT)],
    binaries=[],
    datas=FROZEN_BUNDLE_DATA,
    hiddenimports=HIDDENIMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "doctest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure)  # type: ignore[name-defined]  # noqa: F821

exe = EXE(  # type: ignore[name-defined]  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="lockverity-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # Console CLI: the documented ``lockverity-cli.exe`` is interactive.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(REPO_ROOT / "frontend" / "public" / "favicon.ico"),
)

coll = COLLECT(  # type: ignore[name-defined]  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="lockverity-cli",
)
