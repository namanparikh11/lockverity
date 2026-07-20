"""Regression tests for the v2.0.3 ruff pin.

v2.0 shipped with ``ruff>=0.4.0`` in the ``dev`` extras. A clean
checkout resolves the latest release, which has produced a
destructive change in the formatter (ruff 0.15.22 deletes
module-level docstrings the older format preserved). The
``scripts/verify_release.py`` script runs
``python -m ruff format --check app tests scripts``; on a clean
checkout with the unpinned dev extras, that check fails with
``196 files would be reformatted``.

v2.0.3 pins ``ruff==0.15.21`` in the dev extras. These tests
guard the pin against future drift.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


def _load_pyproject() -> dict:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as f:
        return tomllib.load(f)


def test_dev_extras_pin_ruff_exact_patch() -> None:
    """The dev extras must pin ``ruff`` to a specific patch.

    The pin is required for the release-validation script to
    pass on a clean checkout. A lower-bound-only spec
    (``ruff>=X.Y``) lets the resolver pull a future release
    whose formatter disagrees with the committed format.
    """
    data = _load_pyproject()
    dev = data["project"]["optional-dependencies"]["dev"]
    ruff_specs = [s for s in dev if s.startswith("ruff")]
    assert ruff_specs, "ruff must be declared in the dev extras"
    ruff = ruff_specs[0]
    match = re.fullmatch(r"ruff(==|>=)(\S+)", ruff)
    assert match is not None, f"unexpected ruff spec format: {ruff!r}"
    op, version = match.group(1), match.group(2)
    # The patch number (after the second dot) must be pinned.
    # ``>=0.4.0`` and ``>=0.15.0`` would silently regress;
    # only ``==0.15.21`` (or a similarly patch-pinned spec) is
    # acceptable.
    assert op == "==", (
        f"ruff spec must be an exact pin (``==``), not a range. "
        f"Got {ruff!r}; the committed format is matched by a "
        f"specific patch and a range would silently regress on "
        f"a future release."
    )
    parts = version.split(".")
    assert len(parts) >= 3 and all(p.isdigit() for p in parts), (
        f"ruff pin {ruff!r} must be a semver version"
    )


def test_dev_extras_contains_known_required_tools() -> None:
    """The dev extras must still cover the tools ``verify_release.py`` runs."""
    data = _load_pyproject()
    dev = data["project"]["optional-dependencies"]["dev"]
    joined = " ".join(dev).lower()
    for tool in ("pytest", "ruff", "mypy"):
        assert tool in joined, f"dev extras must include {tool!r}"


def test_verify_release_uses_in_scope_ruff_command() -> None:
    """``scripts/verify_release.py`` must invoke ``ruff format --check``."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_release.py"
    src = script.read_text(encoding="utf-8")
    assert "ruff" in src
    assert "format" in src
    assert "--check" in src
