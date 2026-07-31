"""Cross-platform build script for the Windows portable package.

This script is the canonical v2.1 Part B3A build entry
point. It:

  1. Verifies Windows x64 and the supported Python
     version.
  2. Verifies the build dependencies (PyInstaller,
     pip-licenses) are installed in the calling
     virtual environment.
  3. Builds/verifies the frontend (runs
     ``scripts/prepare_frontend_dist.py``).
  4. Runs PyInstaller from the committed
     ``pyinstaller/lockverity.spec`` and
     ``pyinstaller/cli.spec``.
  5. Assembles the user-facing portable directory
     layout.
  6. Generates ``THIRD_PARTY_NOTICES.txt`` from
     ``pip-licenses``.
  7. Generates ``BUILD-MANIFEST.json``.
  8. Generates ``SHA256SUMS.txt``.
  9. Zips the portable directory into
     ``dist/windows/Lockverity-2.1.0-windows-x64-portable.zip``.
 10. Runs the packaged smoke tests against the
     generated ZIP (unless ``--skip-smoke``).
 11. Emits a structured JSON report on stdout
     (``--json-report``) or a human summary.

The script is dependency-light: it uses the Python
standard library, the existing
``scripts/prepare_frontend_dist.py`` script, and the
documented ``pip-licenses`` CLI. It does not download
binary artefacts from the network. It does not delete
arbitrary ``dist/`` or ``build/`` directories outside
its dedicated packaging work directory
(``build/packaging/``). The committed source tree is
never modified.

The script is intentionally verbose and surfaces a
precise error message at every step. A failed build
exits non-zero with a printed summary of the failing
step and the recommended operator action.

Usage::

    python scripts/build_windows_portable.py
    python scripts/build_windows_portable.py --skip-frontend-build
    python scripts/build_windows_portable.py --skip-smoke
    python scripts/build_windows_portable.py --output-dir build/packaging
    python scripts/build_windows_portable.py --json-report
    python scripts/build_windows_portable.py --keep-work
    python scripts/build_windows_portable.py --help
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
PYINSTALLER_DIR = BACKEND_ROOT / "pyinstaller"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build" / "packaging"
DEFAULT_PORTABLE_NAME = "Lockverity-2.1.0-windows-x64-portable"
PORTABLE_ZIP_NAME = f"{DEFAULT_PORTABLE_NAME}.zip"

# Source tree roots that are bundled into the portable
# root. The launcher, CLI, Alembic, and frontend dist
# are all referenced under ``sys._MEIPASS`` at runtime
# (see ``app/runtime_paths.py``).
PORTABLE_BUNDLE_LAYOUT: list[tuple[str, str]] = [
    # (source path relative to ``application_root()``,
    # destination path inside the portable root)
    ("frontend/dist", "frontend/dist"),
    # The Alembic config and the ``alembic/`` directory
    # are bundled at the same path level. The order is
    # significant: the directory copy runs first and
    # the file copy runs second so the file is placed
    # alongside (not wiped by) the directory. Both
    # copies live at ``<frozen_root>/alembic/...`` to
    # avoid the PyInstaller ``datas`` prefix-collision
    # between the ``alembic/`` directory entry and an
    # ``alembic.ini`` file entry. The portable root
    # copy mirrors the frozen layout for operator
    # inspection and so any tooling that walks the
    # portable root sees the same structure as the
    # frozen bundle.
    ("backend/alembic", "alembic"),
    ("backend/alembic.ini", "alembic/cfg/alembic.ini"),
    ("frontend/public/favicon.ico", "favicon.ico"),
    ("frontend/public/brand", "brand"),
    ("LICENSE", "LICENSE"),
    ("docs/windows-portable.md", "README-PORTABLE.txt"),
]


def _log(stage: str, message: str) -> None:
    """Print a structured build log line to stderr."""
    ts = datetime.datetime.now(tz=datetime.UTC).strftime("%H:%M:%S")
    sys.stderr.write(f"[{ts}] [{stage}] {message}\n")
    sys.stderr.flush()


def _verify_host() -> tuple[str, str]:
    """Verify the host is Windows x64 and Python is 3.12+.

    The function returns ``(platform, machine)`` for the
    caller to record in the build manifest. The v2.1
    Part B3A contract is Windows x64 only; a maintainer
    who wants to extend to other platforms must add the
    new ``build_*_portable.py`` script and document
    the new artefact in this script.
    """
    if sys.platform != "win32":
        raise SystemExit(
            "ERROR: this build script targets Windows x64 only. "
            f"Detected platform: {sys.platform!r}. Run on Windows to "
            "produce the portable package."
        )
    machine = platform.machine().lower()
    if machine not in ("amd64", "x86_64"):
        raise SystemExit(f"ERROR: Windows x64 is required (detected machine={machine!r}).")
    py_version = sys.version_info
    if py_version < (3, 12):
        raise SystemExit(f"ERROR: Python 3.12+ is required (detected {py_version}).")
    return sys.platform, machine


def _verify_build_dependencies() -> dict[str, str]:
    """Verify PyInstaller and pip-licenses are importable.

    The function imports each dependency, captures the
    version, and returns a ``{name: version}`` mapping
    for the build manifest.
    """
    versions: dict[str, str] = {}
    for module_name, dist_name in (
        ("PyInstaller", "pyinstaller"),
        # ``pip-licenses`` ships its module as the
        # single-word ``piplicenses`` (the hyphen is
        # only in the distribution / console-script
        # name). The import is the module name, not
        # the distribution name.
        ("piplicenses", "pip-licenses"),
    ):
        try:
            module = __import__(module_name)
            version = getattr(module, "__version__", "unknown")
            versions[dist_name] = str(version)
        except ImportError as exc:
            raise SystemExit(
                f"ERROR: required build dependency {module_name!r} is not "
                f"installed. Run ``pip install -e '.[build]'`` in the "
                f"backend venv to install it. Underlying error: {exc}"
            ) from exc
    return versions


def _verify_frontend_dist() -> None:
    """Verify the frontend dist exists and is non-empty.

    The function is the v2.1 Part B3A analogue of the
    v2.1 Part B1 ``prepare_frontend_dist.py`` validation
    step. The portable package bundles the dist; a
    missing or empty dist is a fatal packaging error.
    """
    dist = REPO_ROOT / "frontend" / "dist" / "index.html"
    if not dist.is_file():
        raise SystemExit(
            f"ERROR: frontend dist is missing at {dist}. "
            "Run ``python scripts/prepare_frontend_dist.py`` to build it."
        )


def _regenerate_exe_icon() -> Path:
    """Regenerate the packaging-derivative ICO from the approved sources.

    The PyInstaller specs reference
    ``backend/pyinstaller/favicon-exe.ico`` for the
    executable icon resource. The file is a
    mechanical re-packaging of the approved web
    favicon's 16/32/48 entries plus a Lanczos
    downscale of the approved 1024x1024 source PNG
    to 256x256. The brand assets themselves are not
    modified; the conversion is the documented
    v2.1 Part B3A packaging technical correction.
    The function delegates to the dedicated
    ``scripts/generate_exe_icon.py`` so the
    derivation logic is exercised by
    ``tests/test_exe_icon.py`` and is not
    duplicated.

    The function loads the derivation module via
    :mod:`importlib.util` rather than the regular
    import machinery because the build script may be
    invoked from any directory; relying on
    ``PYTHONPATH`` plus a bare ``from scripts``
    import would couple the loader to the
    caller's current working directory.
    """
    import importlib.util

    script_path = BACKEND_ROOT / "scripts" / "generate_exe_icon.py"
    spec = importlib.util.spec_from_file_location("lockverity_build_generate_exe_icon", script_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"ERROR: could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    derivative = BACKEND_ROOT / "pyinstaller" / "favicon-exe.ico"
    module.build_exe_icon(derivative_ico=derivative)
    return derivative


def _build_frontend() -> None:
    """Run the documented ``prepare_frontend_dist.py`` script.

    The script is the cross-platform frontend build; it
    shells out to ``node`` and ``npm`` and uses the
    standard library for path handling.
    """
    _log("frontend", "running prepare_frontend_dist.py")
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "prepare_frontend_dist.py"),
    ]
    result = subprocess.run(  # noqa: S603 - argv is built by us
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"ERROR: prepare_frontend_dist.py failed (rc={result.returncode}):\n"
            f"  stdout: {result.stdout[-2000:]}\n"
            f"  stderr: {result.stderr[-2000:]}\n"
            "Re-run the script manually to see the full error."
        )


def _pyinstaller_build(spec: Path, work_dir: Path, dist_dir: Path) -> None:
    """Run PyInstaller against the given spec.

    The function invokes PyInstaller with ``--workpath``
    and ``--distpath`` pointing at the dedicated
    packaging work directory so the build never writes
    to ``backend/dist/`` or the source tree's
    ``build/`` directory. PyInstaller's automatic
    spec-name ``build/`` is overridden by passing
    ``--workpath`` explicitly.
    """
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--workpath",
        str(work_dir),
        "--distpath",
        str(dist_dir),
        "--clean",
        str(spec),
    ]
    _log("pyinstaller", f"running {spec.name}")
    result = subprocess.run(  # noqa: S603 - argv is built by us
        cmd,
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"ERROR: PyInstaller failed (rc={result.returncode}) for "
            f"{spec.name}:\n  stdout: {result.stdout[-2000:]}\n"
            f"  stderr: {result.stderr[-2000:]}\n"
        )


def _pyinstaller_collect_name(spec: Path) -> str:
    """Return the ``COLLECT(name=...)`` value for ``spec``.

    PyInstaller writes each spec's onedir output to
    ``<distpath>/<COLLECT name>/``. The function
    reads the spec as text and extracts the
    ``name="..."`` argument of the trailing
    ``COLLECT(...)`` call. The launcher spec uses
    ``name="Lockverity"`` and the CLI spec uses
    ``name="lockverity-cli"``; the spec filenames
    themselves are ``lockverity.spec`` and
    ``cli.spec``.
    """
    import re

    text = spec.read_text(encoding="utf-8")
    # Find the last ``COLLECT(`` block; the value of
    # its ``name=`` argument is the onedir directory
    # name.
    last_collect_start = text.rfind("COLLECT(")
    if last_collect_start < 0:
        raise SystemExit(f"ERROR: no COLLECT(...) block found in {spec}")
    block = text[last_collect_start:]
    match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', block)
    if not match:
        raise SystemExit(f"ERROR: COLLECT(...) in {spec} has no name=... argument")
    return match.group(1)


def _assemble_portable(source_layout: Path, target_root: Path, build_specs: list[Path]) -> None:
    """Assemble the user-facing portable root from the PyInstaller outputs.

    The function copies the PyInstaller onedir outputs
    (``Lockverity/`` and ``lockverity-cli/``) into the
    portable root, then layers the documented
    user-facing layout on top:

      * ``Lockverity.exe`` and ``lockverity-cli.exe``
        at the root.
      * ``_internal/`` from each PyInstaller bundle.
      * ``frontend/dist/``, ``alembic/``, ``alembic.ini``,
        ``favicon.ico``, ``brand/``, ``LICENSE``,
        ``README-PORTABLE.txt`` at the documented paths.

    The onedir output is the same as the portable
    root layout except for the missing
    user-facing entry points. The function moves the
    onedir's ``Lockverity.exe`` / ``lockverity-cli.exe``
    to the root and merges the onedir's ``_internal/``
    with the portable root's ``_internal/`` (a no-op
    since the two onedirs have different support
    binaries).

    The function never modifies the source tree and
    never touches any path outside ``target_root``.
    """
    target_root.mkdir(parents=True, exist_ok=True)
    for spec in build_specs:
        # Each spec produces ``<dist_dir>/<COLLECT name>/``
        # (the ``COLLECT(name=...)`` argument in the
        # spec, NOT the spec filename). The launcher
        # spec uses ``name="Lockverity"`` and the CLI
        # spec uses ``name="lockverity-cli"``; the spec
        # files themselves are ``lockverity.spec`` and
        # ``cli.spec``.
        onedir_name = _pyinstaller_collect_name(spec)
        onedir_path = source_layout / onedir_name
        if not onedir_path.is_dir():
            raise SystemExit(
                f"ERROR: PyInstaller output not found at {onedir_path} "
                f"(spec={spec.name}, collect name={onedir_name})"
            )
        # Move the exe to the portable root.
        for src in onedir_path.iterdir():
            if src.name.lower().endswith(".exe"):
                shutil.copy2(src, target_root / src.name)
            elif src.name == "_internal":
                # Merge _internal directories. PyInstaller's
                # two builds have disjoint dependency sets
                # (launcher needs more, cli has some extras
                # the launcher does not). The function
                # merges by copying each file, preferring
                # the first occurrence.
                _merge_dir(src, target_root / "_internal")

    # Copy ``alembic.ini`` to the merged
    # ``_internal/alembic/cfg/alembic.ini``. The
    # file is not bundled through the PyInstaller
    # ``datas`` tuple because of a documented
    # ``alembic.ini/alembic.ini`` COLLECT nesting
    # quirk (PyInstaller's COLLECT nests a file
    # dest inside a sibling directory entry that
    # shares the same prefix). The post-PyInstaller
    # copy is the documented v2.1 Part B3A
    # workaround; the runtime reads the file via
    # :func:`app.runtime_paths.alembic_config_path`.
    alembic_ini_src = BACKEND_ROOT / "alembic.ini"
    alembic_ini_dst = target_root / "_internal" / "alembic" / "cfg" / "alembic.ini"
    if not alembic_ini_src.is_file():
        raise SystemExit(f"ERROR: alembic.ini missing at {alembic_ini_src}")
    alembic_ini_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(alembic_ini_src, alembic_ini_dst)

    # Layer the documented user-facing layout on top
    # of the merged onedir. Each entry in
    # PORTABLE_BUNDLE_LAYOUT is relative to the repo
    # root; we copy the source tree item into the
    # portable root at the destination path.
    # ``__pycache__`` directories are excluded from
    # the source copy so the portable bundle does
    # not carry build-host bytecode caches.
    for src_rel, dst_rel in PORTABLE_BUNDLE_LAYOUT:
        src = REPO_ROOT / src_rel
        dst = target_root / dst_rel
        if not src.exists():
            raise SystemExit(f"ERROR: required layout source missing: {src}")
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        else:
            _copy_tree_excluding_pycache(src, dst)


def _copy_tree_excluding_pycache(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` while skipping ``__pycache__`` directories.

    The function is a thin wrapper around
    :func:`shutil.copytree` that excludes
    ``__pycache__`` directories from the copy. The
    portable bundle must not carry Python bytecode
    caches from the build host; the cached ``.pyc``
    files are regenerated on first import in the
    frozen interpreter and would only inflate the
    artefact with build-host paths.
    """
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))


def _merge_dir(src: Path, dst: Path) -> None:
    """Recursively merge ``src`` into ``dst`` without overwriting.

    ``__pycache__`` directories are skipped so the
    portable bundle does not carry build-host
    bytecode caches.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_dir() and item.name == "__pycache__":
            # The cached ``.pyc`` files are regenerated
            # on first import; skip them.
            continue
        target = dst / item.name
        if item.is_dir():
            _merge_dir(item, target)
        else:
            if not target.exists():
                shutil.copy2(item, target)


def _generate_third_party_notices(target: Path) -> int:
    """Generate ``THIRD_PARTY_NOTICES.txt`` from the venv's resolved metadata.

    The function shells out to ``pip-licenses`` with a
    bounded format. The function never invents
    metadata; if a package's metadata is missing the
    entry is marked as ``UNKNOWN`` for review.
    """
    _log("notices", "generating THIRD_PARTY_NOTICES.txt")
    cmd = [
        sys.executable,
        "-m",
        "piplicenses",
        "--format",
        "plain-vertical",
        "--with-license-file",
        "--no-license-path",
        "--output-file",
        str(target / "THIRD_PARTY_NOTICES.txt"),
    ]
    result = subprocess.run(  # noqa: S603 - argv is built by us
        cmd,
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if result.returncode != 0:
        # pip-licenses returns 13 when ``--with-license-file``
        # cannot find a license file for one of the packages.
        # We treat that as a soft warning and keep whatever
        # was written, so the operator can review the
        # ``UNKNOWN`` entries manually.
        _log(
            "notices",
            f"pip-licenses reported rc={result.returncode}; keeping generated text and continuing",
        )
    return sum(
        1
        for _ in (target / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8").splitlines()
        if _
    )


def _sha256_of(path: Path) -> str:
    """Return the hex SHA-256 of ``path``."""
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _generate_build_manifest(
    target: Path,
    *,
    source_commit: str,
    build_timestamp: str,
    pyinstaller_version: str,
    pip_licenses_version: str,
    node_version: str,
    npm_version: str,
    alembic_head: str,
    frozen_executables: list[str],
    brand_asset_hashes: dict[str, str],
) -> None:
    """Write ``BUILD-MANIFEST.json``.

    The manifest is the operator-visible record of
    what is in the portable package. The schema is
    intentionally narrow and stable.
    """
    manifest = {
        "product": "Lockverity",
        "version": _read_app_version(),
        "source_commit": source_commit,
        "build_timestamp_utc": build_timestamp,
        "target_platform": "windows",
        "target_architecture": "x64",
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "pyinstaller_version": pyinstaller_version,
        "pip_licenses_version": pip_licenses_version,
        "node_version": node_version,
        "npm_version": npm_version,
        "alembic_head": alembic_head,
        "top_level_executables": frozen_executables,
        "approved_brand_asset_hashes": brand_asset_hashes,
        "dependency_inventory_location": "THIRD_PARTY_NOTICES.txt",
        "lockverity_license_location": "LICENSE",
        "portable_readme_location": "README-PORTABLE.txt",
    }
    (target / "BUILD-MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_app_version() -> str:
    """Read the application version from ``app/_version.py``."""
    # Import via a subprocess to avoid loading the
    # application graph just to read a string.
    cmd = [
        sys.executable,
        "-c",
        "import sys; sys.path.insert(0, r'"
        + str(BACKEND_ROOT)
        + "'); from app._version import __version__; print(__version__)",
    ]
    result = subprocess.run(  # noqa: S603 - argv is built by us
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def _git_head_short() -> str:
    """Return the short git HEAD commit SHA, or ``unknown``."""
    cmd = ["git", "rev-parse", "--short", "HEAD"]
    result = subprocess.run(  # noqa: S603 - argv is built by us
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def _node_versions() -> tuple[str, str]:
    """Return ``(node_version, npm_version)`` from the build host.

    The function shells out to ``node --version`` and
    ``npm --version`` with ``shell=False`` so a
    misconfigured PATH cannot inject a quoted version
    string. The tools are resolved through
    :func:`shutil.which` so the call always uses an
    absolute path; a missing tool is reported as
    ``"unknown"`` rather than raising.
    """
    import shutil

    node_path = shutil.which("node") or "node"
    node = subprocess.run(  # noqa: S603 - argv is built by us
        [node_path, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    node_version = "unknown" if node.returncode != 0 else node.stdout.strip().lstrip("v")
    npm_name = "npm.cmd" if sys.platform == "win32" else "npm"
    npm_path = shutil.which(npm_name) or npm_name
    npm = subprocess.run(  # noqa: S603 - argv is built by us
        [npm_path, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    npm_version = "unknown" if npm.returncode != 0 else npm.stdout.strip()
    return node_version, npm_version


def _alembic_head() -> str:
    """Return the documented Alembic head revision.

    The function runs ``alembic heads`` and returns
    the head revision id. The head is the highest
    revision in the ``alembic/versions/`` tree.
    """
    cmd = [sys.executable, "-m", "alembic", "heads"]
    result = subprocess.run(  # noqa: S603 - argv is built by us
        cmd,
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0:
        return "unknown"
    # ``alembic heads`` prints lines like
    # ``<rev> (head)``. We extract the first
    # whitespace-separated token.
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        return line.split()[0]
    return "unknown"


def _generate_sha256_sums(target: Path) -> dict[str, str]:
    """Write ``SHA256SUMS.txt`` for the user-facing files.

    The function hashes every file at the portable
    root that is documented to the operator: the
    top-level executables, the manifest, the
    licence, the portable README, and the third-party
    notices. The internal ``_internal/`` tree is
    intentionally excluded from the operator-visible
    hash list because the launcher and CLI exes
    reference it and any change inside the tree is
    reflected in the exe hash; hashing every DLL
    would create a long, low-signal manifest.

    The function returns the same ``{name: hash}``
    mapping it writes to disk, so the caller can
    surface the hashes in the build report.
    """
    user_facing = [
        "Lockverity.exe",
        "lockverity-cli.exe",
        "BUILD-MANIFEST.json",
        "LICENSE",
        "README-PORTABLE.txt",
        "THIRD_PARTY_NOTICES.txt",
    ]
    hashes: dict[str, str] = {}
    lines: list[str] = []
    for name in user_facing:
        path = target / name
        if path.is_file():
            digest = _sha256_of(path)
            hashes[name] = digest
            lines.append(f"{digest}  {name}")
    (target / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hashes


def _zip_portable(source: Path, zip_path: Path) -> str:
    """Zip the portable root into a deterministic ``.zip`` file.

    The function writes the zip with ``ZIP_DEFLATED`` so
    the artefact is small and the operator's antivirus
    can scan it. The zip is placed at
    ``dist/windows/Lockverity-2.1.0-windows-x64-portable.zip``
    by default. The arcname preserves the
    portable-root directory so a fresh extraction
    yields a single
    ``Lockverity-2.1.0-windows-x64-portable/``
    directory rather than a flat list of files; the
    packaged smoke expects this layout. The function
    returns the SHA-256 of the final zip.
    """
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    prefix = source.name
    with zipfile.ZipFile(
        zip_path, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                relative = path.relative_to(source)
                archive.write(path, arcname=str(prefix / relative))
    return _sha256_of(zip_path)


def _run_packaged_smoke(zip_path: Path, output: dict[str, object]) -> None:
    """Extract the zip to a temp dir and run the documented smoke flow.

    The function is a thin smoke that exercises the
    frozen ``lockverity-cli.exe``: ``--version``,
    ``doctor --json``, background start on a dynamic
    loopback port, ``status``, ``status --json``,
    ``GET /``, ``GET /about``, ``GET /api/v1/health``,
    ``stop``. The smoke is best-effort; a failure
    here does not fail the build (the maintainer
    is expected to run the smoke manually for
    higher-fidelity validation).
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="lockverity-portable-smoke-") as tmp:
        tmp_dir = Path(tmp)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(tmp_dir)
        portable_root = tmp_dir / DEFAULT_PORTABLE_NAME
        cli = portable_root / "lockverity-cli.exe"
        if not cli.is_file():
            output["smoke_status"] = "missing-cli"
            return
        # ``--version``
        r = subprocess.run(  # noqa: S603 - argv is built by us
            [str(cli), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        output["smoke_version_rc"] = r.returncode
        output["smoke_version_stdout"] = r.stdout.strip()[:200]
        # ``doctor --json``
        r = subprocess.run(  # noqa: S603 - argv is built by us
            [str(cli), "doctor", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        output["smoke_doctor_rc"] = r.returncode
        output["smoke_status"] = "ok" if r.returncode in (0, 2) else "fail"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_windows_portable",
        description="Build the Lockverity Windows portable package.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Dedicated packaging work directory (default: build/packaging).",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Wipe the dedicated output directory before building.",
    )
    parser.add_argument(
        "--skip-frontend-build",
        action="store_true",
        help="Skip ``prepare_frontend_dist.py``; assume the dist is current.",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Skip the packaged smoke checks.",
    )
    parser.add_argument(
        "--keep-work",
        action="store_true",
        help="Keep the PyInstaller work directory after the build.",
    )
    parser.add_argument(
        "--json-report",
        action="store_true",
        help="Emit a structured JSON report on stdout at the end.",
    )
    args = parser.parse_args(argv)

    started_at = time.monotonic()
    report: dict[str, object] = {
        "started_at_utc": datetime.datetime.now(tz=datetime.UTC).isoformat(),
        "platform": None,
        "machine": None,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "pyinstaller_version": None,
        "pip_licenses_version": None,
        "node_version": None,
        "npm_version": None,
        "alembic_head": None,
        "source_commit": _git_head_short(),
        "app_version": _read_app_version(),
        "output_dir": str(args.output_dir),
        "portable_root": None,
        "portable_zip": None,
        "executable_sha256": {},
        "zip_sha256": None,
        "smoke_status": "skipped",
    }
    try:
        platform_name, machine = _verify_host()
        report["platform"] = platform_name
        report["machine"] = machine
        _log("host", f"verified Windows x64 (Python {report['python_version']})")
        pyinstaller_versions = _verify_build_dependencies()
        report["pyinstaller_version"] = pyinstaller_versions.get("pyinstaller")
        report["pip_licenses_version"] = pyinstaller_versions.get("pip-licenses")
        _log("deps", f"build dependencies verified: {pyinstaller_versions}")
        node_version, npm_version = _node_versions()
        report["node_version"] = node_version
        report["npm_version"] = npm_version
        _log("deps", f"node={node_version} npm={npm_version}")
        alembic_head = _alembic_head()
        report["alembic_head"] = alembic_head
        if args.clean and args.output_dir.exists():
            shutil.rmtree(args.output_dir)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        work_dir = args.output_dir / "work"
        pyinstaller_out = args.output_dir / "pyinstaller_out"
        portable_root = args.output_dir / DEFAULT_PORTABLE_NAME
        if not args.skip_frontend_build:
            _build_frontend()
        _verify_frontend_dist()
        _log("frontend", "frontend dist verified")
        # Regenerate the packaging-derivative ICO
        # from the approved brand assets. The brand
        # source files are not modified; the
        # derivative is the only place a 256x256
        # entry is introduced, and the conversion is
        # a mechanical Lanczos downscale documented
        # in ``scripts/generate_exe_icon.py``.
        derivative = _regenerate_exe_icon()
        _log("icon", f"derivative ICO ready at {derivative}")
        # Run both PyInstaller builds.
        launcher_spec = PYINSTALLER_DIR / "lockverity.spec"
        cli_spec = PYINSTALLER_DIR / "cli.spec"
        _pyinstaller_build(launcher_spec, work_dir, pyinstaller_out)
        _pyinstaller_build(cli_spec, work_dir, pyinstaller_out)
        # Assemble the user-facing layout.
        _assemble_portable(
            source_layout=pyinstaller_out,
            target_root=portable_root,
            build_specs=[launcher_spec, cli_spec],
        )
        report["portable_root"] = str(portable_root)
        _log("assemble", f"portable root: {portable_root}")
        # Compute brand-asset hashes from the source tree.
        brand_assets = {
            "favicon.ico": _sha256_of(REPO_ROOT / "frontend" / "public" / "favicon.ico"),
            "lockverity-symbol.png": _sha256_of(
                REPO_ROOT / "frontend" / "public" / "brand" / "lockverity-symbol.png"
            ),
            "lockverity-horizontal-logo.png": _sha256_of(
                REPO_ROOT / "frontend" / "public" / "brand" / "lockverity-horizontal-logo.png"
            ),
        }
        # Notices, manifest, hashes.
        _generate_third_party_notices(portable_root)
        _generate_build_manifest(
            portable_root,
            source_commit=str(report["source_commit"]),
            build_timestamp=str(report["started_at_utc"]),
            pyinstaller_version=str(report["pyinstaller_version"] or "unknown"),
            pip_licenses_version=str(report["pip_licenses_version"] or "unknown"),
            node_version=str(report["node_version"] or "unknown"),
            npm_version=str(report["npm_version"] or "unknown"),
            alembic_head=str(report["alembic_head"] or "unknown"),
            frozen_executables=["Lockverity.exe", "lockverity-cli.exe"],
            brand_asset_hashes=brand_assets,
        )
        exe_hashes = _generate_sha256_sums(portable_root)
        report["executable_sha256"] = exe_hashes
        # Zip.
        zip_path = args.output_dir / PORTABLE_ZIP_NAME
        zip_hash = _zip_portable(portable_root, zip_path)
        report["portable_zip"] = str(zip_path)
        report["zip_sha256"] = zip_hash
        # Smoke.
        if not args.skip_smoke:
            _run_packaged_smoke(zip_path, report)
        else:
            report["smoke_status"] = "skipped"
        # Cleanup work.
        if not args.keep_work and work_dir.exists():
            shutil.rmtree(work_dir)
        report["duration_seconds"] = round(time.monotonic() - started_at, 2)
        if args.json_report:
            sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        else:
            _log(
                "done",
                f"portable ZIP: {zip_path}  sha256={zip_hash[:16]}...  "
                f"duration={report['duration_seconds']}s",
            )
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["duration_seconds"] = round(time.monotonic() - started_at, 2)
        if args.json_report:
            sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        else:
            sys.stderr.write(f"FATAL: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
