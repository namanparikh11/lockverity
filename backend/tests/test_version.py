"""Version consistency tests.

The product version is a single source of truth in
``app/_version.py``. These tests guard against silent drift
between the version constant and the artefacts that publish it.
"""

from __future__ import annotations

import re

import app
from app._version import __version__
from app.core.config import get_settings


def test_package_version_constant_is_semver() -> None:
    # ``0.2.0`` form. We allow trailing ``.postN`` / ``.devN`` /
    # ``.rcN`` for pre-release tags added in future milestones.
    assert re.match(r"^\d+\.\d+\.\d+(?:\.(?:post|dev|rc)\d+)?$", __version__), (
        f"app._version.__version__ is not in semver form: {__version__!r}"
    )


def test_package_attribute_matches_constant() -> None:
    assert app.__version__ == __version__


def test_settings_app_version_matches_constant() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.app_version == __version__


def test_settings_app_version_independent_of_environment_override() -> None:
    """``LOCKVERITY_APP_VERSION`` should be honoured when set, but
    the default must still match the package constant. This guards
    against the version being accidentally parameterised away from
    the single source of truth."""
    get_settings.cache_clear()
    base = get_settings().app_version
    assert base == __version__
