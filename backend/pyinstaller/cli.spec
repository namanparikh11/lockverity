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
    # See ``lockverity.spec`` for the rationale of
    # bundling ``alembic.ini`` at
    # ``<frozen_root>/alembic/alembic.ini`` (the
    # PyInstaller prefix-collision workaround).
    # See ``lockverity.spec`` for the rationale of
    # not bundling ``alembic.ini`` through the
    # ``datas`` tuple.
    (str(BACKEND_ROOT / "alembic"), "alembic"),
    (str(REPO_ROOT / "frontend" / "public" / "favicon.ico"), "favicon.ico"),
    # The packaging-derivative ICO (16/32/48/256)
    # is bundled alongside the approved ICO for
    # future Windows shell integrations. See
    # ``lockverity.spec`` for the rationale.
    (str(BACKEND_ROOT / "pyinstaller" / "favicon-exe.ico"), "favicon-exe.ico"),
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
    # See ``lockverity.spec`` for the rationale;
    # ``alembic.config`` and the rotating log handler
    # both pull these in dynamically.
    "logging.config",
    "logging.handlers",
    # The CLI is the migration entry point in
    # frozen mode (via the in-process
    # ``alembic.command.upgrade`` path); the
    # ``app.models`` and ``app.db.base`` modules
    # register the SQLAlchemy metadata that the
    # migration targets.
    "app.models",
    "app.db.base",
    # The private serve entry point
    # (``app.cli._serve``) launches Uvicorn with
    # ``app.main:app`` as the ASGI module string;
    # Uvicorn imports the module at runtime and the
    # static scan only sees the CLI's import graph.
    # The hidden import ensures the FastAPI factory
    # and its dependency graph (routers, middleware,
    # settings, providers) are bundled.
    "app.main",
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
    # The packaging-derivative ICO is the icon
    # resource; see ``lockverity.spec`` for the
    # rationale. The approved 16/32/48 ICO is
    # bundled at the frozen root for the web UI to
    # serve unchanged.
    icon=str(BACKEND_ROOT / "pyinstaller" / "favicon-exe.ico"),
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
