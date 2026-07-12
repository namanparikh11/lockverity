"""Parser base classes and the parser registry.

A :class:`ManifestParser` consumes the bytes of a single manifest
and returns a deterministic list of *component records*. The shape
of a record is documented in :data:`COMPONENT_RECORD_FIELDS`.

The registry in this module maps ``manifest_type`` strings to
parser instances. The orchestrator can iterate the registry to
dispatch by ``manifest_type`` without importing every concrete
parser explicitly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.providers.contracts import ManifestParser
from app.providers.results import ParserResult, ParserWarning

# The list of field names a component record is allowed to use.
# Parsers must produce records that are subsets of this set; the
# dependency-graph analyzer is the canonical consumer and relies on
# these names being present when a field is meaningful.
COMPONENT_RECORD_FIELDS: frozenset[str] = frozenset(
    {
        "kind",
        "ecosystem",
        "package_name",
        "scope",
        "version",
        "version_source",
        "package_url",
        "relationship",
        "direct",
        "development",
        "optional",
        "integrity",
        "extras",
        "marker",
        "specifier",
        "is_unsupported",
        "unsupported_kind",
        "unsupported_detail",
        "source_path",
        "edges",
    }
)

# Valid string values for ``version_source``. Mirrors the ORM enum
# but without requiring SQLAlchemy at import time.
VALID_VERSION_SOURCES: frozenset[str] = frozenset(
    {"MANIFEST", "LOCKFILE", "OVERRIDE", "UNRESOLVED", "UNKNOWN"}
)

VALID_RELATIONSHIPS: frozenset[str] = frozenset(
    {"direct", "transitive", "optional", "development", "peer", "unknown"}
)

VALID_UNSUPPORTED_KINDS: frozenset[str] = frozenset(
    {
        "git_ref",
        "url_ref",
        "file_ref",
        "path_ref",
        "link_ref",
        "workspace_ref",
        "editable",
        "tarball",
        "unknown",
    }
)


class ParserError(ValueError):
    """Raised by a concrete parser for unrecoverable parse errors."""


@dataclass(frozen=True, slots=True)
class ParserRegistration:
    """A parser registered for a specific manifest type."""

    manifest_type: str
    ecosystem: str
    parser: ManifestParser
    description: str = ""


class ParserRegistry:
    """In-process registry of manifest parsers.

    The registry is intentionally process-local. Concrete parsers
    register themselves via :meth:`register`. The orchestrator
    resolves ``manifest_type`` to a parser via :meth:`get`.
    """

    def __init__(self) -> None:
        self._by_type: dict[str, ParserRegistration] = {}

    def register(self, registration: ParserRegistration) -> None:
        if registration.manifest_type in self._by_type:
            raise ValueError(
                f"Parser for manifest_type={registration.manifest_type!r} is already registered."
            )
        self._by_type[registration.manifest_type] = registration

    def get(self, manifest_type: str) -> ParserRegistration | None:
        return self._by_type.get(manifest_type)

    def all(self) -> tuple[ParserRegistration, ...]:
        return tuple(self._by_type[m] for m in sorted(self._by_type))

    def ecosystems(self) -> frozenset[str]:
        return frozenset(r.ecosystem for r in self._by_type.values())


def make_parser_warning(
    code: str,
    message: str,
    location: str | None = None,
) -> ParserWarning:
    """Return a :class:`ParserWarning` with the given fields."""
    if not isinstance(code, str) or not code:
        raise ValueError("warning code must be a non-empty string.")
    if not isinstance(message, str):
        raise ValueError("warning message must be a string.")
    return ParserWarning(code=code, message=message, location=location)


def validate_record(record: Mapping[str, Any]) -> None:
    """Raise :class:`ValueError` if ``record`` has unknown fields.

    The function is conservative: extra fields are an error rather
    than a warning because downstream analyzers key off this
    document. The check does not validate *values*, only field
    *names*.
    """
    unknown = set(record) - COMPONENT_RECORD_FIELDS
    if unknown:
        raise ParserError(f"Component record has unknown fields: {sorted(unknown)!r}.")


def build_package_url(ecosystem: str, name: str, version: str | None) -> str | None:
    """Return a Package URL string for a package, or ``None`` if invalid.

    Follows the PURL spec at https://github.com/package-url/purl-spec.
    """
    if not isinstance(ecosystem, str) or not ecosystem:
        return None
    if not isinstance(name, str) or not name:
        return None
    if version is not None and not isinstance(version, str):
        return None
    purl_type = {
        "npm": "npm",
        "pypi": "pypi",
    }.get(ecosystem)
    if purl_type is None:
        return None
    encoded_name = name.replace("@", "%40") if ecosystem == "pypi" else name
    if version is None or not version:
        return f"pkg:{purl_type}/{encoded_name}"
    return f"pkg:{purl_type}/{encoded_name}@{version}"


def dedupe_records(records: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Return records deduplicated by ``(package_name, version, source_path)``.

    Parsers can produce duplicate records (for example, a lockfile
    and a manifest that both declare the same package). The
    dependency-graph analyzer keys components on this triple.
    """
    seen: set[tuple[str, str | None, str | None]] = set()
    out: list[dict[str, Any]] = []
    for record in records:
        key = (
            record.get("package_name", ""),
            record.get("version"),
            record.get("source_path"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(record))
    return tuple(out)


@dataclass(slots=True)
class _Collector:
    warnings: list[ParserWarning] = field(default_factory=list)

    def warn(self, code: str, message: str, location: str | None = None) -> None:
        self.warnings.append(make_parser_warning(code, message, location))


def finalize_parse(
    collector: _Collector, data: list[dict[str, Any]]
) -> ParserResult[list[dict[str, Any]]]:
    """Return a :class:`ParserResult` for ``data`` and the collected warnings."""
    return ParserResult(
        data=tuple(data),
        warnings=tuple(collector.warnings),
        records_processed=len(data),
    )
