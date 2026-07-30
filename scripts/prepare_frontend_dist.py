"""Cross-platform build preparation for the single-port runtime.

This script is the canonical "build before start" step for
the v2.1 Part B1 single-port production runtime. It runs
the existing reproducible Vite build process and verifies
the output before the backend is started in
``LOCKVERITY_SERVE_FRONTEND=true`` mode.

The script is intentionally dependency-light: it shells
out to ``node`` and ``npm`` and uses the Python standard
library for path and version handling. It does not
download Node, does not modify global packages, and does
not silently hide failures.

Steps:

  1. Locate the repository root from this script's path.
  2. Verify the supported Node toolchain
     (``node >= 22.22.0`` and a matching ``npm``).
  3. Run ``npm ci`` in ``frontend/`` (idempotent and
     reproducible install).
  4. Run ``npm run build`` in ``frontend/`` (the
     production build).
  5. Verify ``frontend/dist/index.html`` exists.
  6. Verify the approved brand assets are in the dist
     directory (Vite copies files from ``frontend/public/``
     into ``dist/`` at build time).

Usage::

    python scripts/prepare_frontend_dist.py
    python scripts/prepare_frontend_dist.py --skip-install
    python scripts/prepare_frontend_dist.py --help

A non-zero exit code indicates a failure. The script
prints the failing step and the recommended operator
action so the failure is actionable.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Node.js floor: react-router 8.x requires ``node >=22.22.0``.
# The v2.0.6 release checklist documents this floor in
# ``docs/release-checklist.md``. The build script enforces
# the same floor so a developer on an older toolchain gets
# a clear error before npm starts.
NODE_VERSION_MIN = (22, 22, 0)

# Required build artefacts. The backend's static-frontend
# module mounts these from the dist directory; a missing
# file is a fatal startup error.
REQUIRED_DIST_FILES = (
    "index.html",
    "favicon.ico",
    "favicon-16x16.png",
    "favicon-32x32.png",
    "favicon-48x48.png",
    "favicon-180x180.png",
    "favicon-256x256.png",
    "favicon-512x512.png",
    "apple-touch-icon.png",
    "favicon-source.png",
)

REQUIRED_BRAND_FILES = (
    "brand/lockverity-symbol.png",
    "brand/lockverity-horizontal-logo.png",
)


def _repo_root() -> Path:
    """Return the absolute path to the repository root."""
    return Path(__file__).resolve().parents[1]


def _parse_node_version(raw: str) -> tuple[int, int, int] | None:
    """Parse a Node.js version string like ``v22.22.0``."""
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", raw.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _verify_node() -> None:
    """Verify ``node`` is installed and meets the floor."""
    node = shutil.which("node")
    if not node:
        print(
            "ERROR: node is not on PATH. Install Node.js "
            f">={NODE_VERSION_MIN[0]}.{NODE_VERSION_MIN[1]}.{NODE_VERSION_MIN[2]} "
            "before running this script.",
            file=sys.stderr,
        )
        sys.exit(2)
    result = subprocess.run(
        [node, "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"ERROR: node --version failed: {result.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(2)
    parsed = _parse_node_version(result.stdout)
    if parsed is None:
        print(
            f"ERROR: could not parse node version: {result.stdout!r}",
            file=sys.stderr,
        )
        sys.exit(2)
    if parsed < NODE_VERSION_MIN:
        print(
            f"ERROR: node {parsed[0]}.{parsed[1]}.{parsed[2]} is below "
            f"the required floor {NODE_VERSION_MIN[0]}."
            f"{NODE_VERSION_MIN[1]}.{NODE_VERSION_MIN[2]}. "
            "Upgrade Node.js before running this script.",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"node {parsed[0]}.{parsed[1]}.{parsed[2]} OK")


def _verify_npm() -> None:
    """Verify ``npm`` is installed."""
    npm = shutil.which("npm")
    if not npm:
        print(
            "ERROR: npm is not on PATH. Install npm (the Node.js "
            "package manager that ships with Node.js) before running "
            "this script.",
            file=sys.stderr,
        )
        sys.exit(2)
    result = subprocess.run(
        [npm, "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"ERROR: npm --version failed: {result.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"npm {result.stdout.strip()} OK")


def _run_npm(args: list[str], cwd: Path) -> None:
    """Run ``npm <args>`` in ``cwd`` and abort on failure."""
    npm = shutil.which("npm")
    assert npm is not None  # _verify_npm guarantees this
    print(f"running: npm {' '.join(args)} (cwd={cwd})")
    result = subprocess.run([npm, *args], cwd=str(cwd), check=False)
    if result.returncode != 0:
        print(
            f"ERROR: npm {' '.join(args)} exited with code "
            f"{result.returncode}.",
            file=sys.stderr,
        )
        sys.exit(result.returncode)


def _verify_dist(repo_root: Path) -> None:
    """Verify the dist directory contains the required artefacts."""
    dist = repo_root / "frontend" / "dist"
    if not dist.is_dir():
        print(
            f"ERROR: dist directory is missing: {dist}. The build did "
            "not produce frontend/dist; check the Vite output above "
            "for the failure cause.",
            file=sys.stderr,
        )
        sys.exit(1)
    missing: list[str] = []
    for relative in REQUIRED_DIST_FILES + REQUIRED_BRAND_FILES:
        if not (dist / relative).is_file():
            missing.append(relative)
    if missing:
        print(
            "ERROR: dist is missing required assets: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        sys.exit(1)
    index_html = dist / "index.html"
    try:
        text = index_html.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: cannot read {index_html}: {exc}", file=sys.stderr)
        sys.exit(1)
    if "<div id=\"root\"" not in text:
        print(
            f"ERROR: {index_html} is missing the React mount point. "
            "The Vite build output is incomplete or stale.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(
        f"dist OK: {dist} ({_count_files(dist)} files, "
        f"index.html {len(text)} bytes)"
    )


def _count_files(root: Path) -> int:
    """Return the total file count under ``root`` (recursive)."""
    return sum(1 for _ in root.rglob("*") if _.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the Lockverity frontend dist for the "
        "single-port production runtime.",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip `npm ci`; useful for repeated local builds where "
        "node_modules is already in sync with package-lock.json.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    frontend_dir = repo_root / "frontend"
    if not frontend_dir.is_dir():
        print(
            f"ERROR: frontend directory not found: {frontend_dir}",
            file=sys.stderr,
        )
        return 1
    package_json = frontend_dir / "package.json"
    if not package_json.is_file():
        print(
            f"ERROR: package.json not found: {package_json}",
            file=sys.stderr,
        )
        return 1

    _verify_node()
    _verify_npm()

    if not args.skip_install:
        _run_npm(["ci"], cwd=frontend_dir)
    _run_npm(["run", "build"], cwd=frontend_dir)
    _verify_dist(repo_root)
    print("OK: frontend dist is ready for the single-port runtime.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
