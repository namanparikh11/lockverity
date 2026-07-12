"""Parser registry singleton.

Imports every concrete parser and registers it. Tests and
orchestrator code use :func:`get_registry` to obtain a single
process-wide instance.
"""

from __future__ import annotations

from app.parsers.base import ParserRegistration, ParserRegistry
from app.parsers.npm import PackageJsonParser, PackageLockJsonParser
from app.parsers.pnpm import PnpmLockParser
from app.parsers.poetry import PoetryLockParser
from app.parsers.pyproject import PyprojectTomlParser
from app.parsers.requirements import RequirementsTxtParser
from app.parsers.yarn import YarnLockParser


def build_default_registry() -> ParserRegistry:
    """Return a fresh registry populated with every built-in parser."""
    registry = ParserRegistry()
    registry.register(
        ParserRegistration(
            manifest_type="package_json",
            ecosystem="npm",
            parser=PackageJsonParser(),
        )
    )
    registry.register(
        ParserRegistration(
            manifest_type="package_lock",
            ecosystem="npm",
            parser=PackageLockJsonParser(),
        )
    )
    registry.register(
        ParserRegistration(
            manifest_type="pnpm_lock",
            ecosystem="npm",
            parser=PnpmLockParser(),
        )
    )
    registry.register(
        ParserRegistration(
            manifest_type="yarn_lock",
            ecosystem="npm",
            parser=YarnLockParser(),
        )
    )
    registry.register(
        ParserRegistration(
            manifest_type="requirements_txt",
            ecosystem="pypi",
            parser=RequirementsTxtParser(),
        )
    )
    registry.register(
        ParserRegistration(
            manifest_type="pyproject_toml",
            ecosystem="pypi",
            parser=PyprojectTomlParser(),
        )
    )
    registry.register(
        ParserRegistration(
            manifest_type="poetry_lock",
            ecosystem="pypi",
            parser=PoetryLockParser(),
        )
    )
    return registry


_REGISTRY: ParserRegistry | None = None


def get_registry() -> ParserRegistry:
    """Return the process-wide parser registry.

    The registry is created lazily so the parser modules can be
    imported without side effects during type checking.
    """
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_default_registry()
    return _REGISTRY


def reset_registry() -> None:
    """Reset the singleton (used by tests)."""
    global _REGISTRY
    _REGISTRY = None
