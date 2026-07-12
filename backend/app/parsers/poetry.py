"""poetry.lock parser.

poetry.lock is a TOML file (despite the extension). The structure
is:

- ``[[package]]`` - a list of tables, one per resolved package
- ``[package.<name>.dependencies]`` - the package's children
- ``[package.<name>.group.<group>.dependencies]`` - group-scoped
  children
- ``[metadata]`` - lockfile metadata; the ``content-hash`` field
  is recorded as evidence.

The parser uses :mod:`tomllib` (Python 3.11+ stdlib) and
:class:`app.utils.yaml_safe.safe_load_yaml_bytes` is **not**
applicable because the format is TOML, not YAML.
"""

from __future__ import annotations

import tomllib as _toml  # type: ignore[no-redef, import-not-found]
from typing import Any

from app.parsers.base import (
    ParserError,
    _Collector,
    build_package_url,
    finalize_parse,
    validate_record,
)
from app.providers.results import ParserResult


def _normalize_marker(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _classify_optional(markers: Any) -> bool:
    if not isinstance(markers, str):
        return False
    lower = markers.lower()
    return "extra" in lower and "==" in lower


def _version_from_value(value: Any) -> tuple[str | None, str]:
    if isinstance(value, str):
        if not value.strip():
            return None, "UNRESOLVED"
        return value.strip(), "LOCKFILE"
    if isinstance(value, dict):
        v = value.get("version")
        if isinstance(v, str):
            return v.strip(), "LOCKFILE"
    return None, "UNRESOLVED"


class PoetryLockParser:
    ecosystem = "pypi"
    manifest_type = "poetry_lock"

    def parse(self, *, content: bytes, path: str) -> ParserResult[list[dict[str, Any]]]:
        collector = _Collector()
        try:
            data = _toml.loads(content.decode("utf-8"))
        except _toml.TOMLDecodeError as exc:  # type: ignore[attr-defined]
            raise ParserError(f"poetry.lock is not valid TOML: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise ParserError(f"poetry.lock is not valid UTF-8: {exc}") from exc
        if not isinstance(data, dict):
            raise ParserError("poetry.lock root must be a table.")

        records: list[dict[str, Any]] = []
        packages = data.get("package")
        if not isinstance(packages, list):
            collector.warn(
                "poetry_lock_missing_packages",
                "poetry.lock had no [[package]] entries.",
                location=path,
            )
            return finalize_parse(collector, records)

        for entry in packages:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                collector.warn(
                    "poetry_lock_entry_missing_name",
                    "poetry.lock entry missing 'name'.",
                    location=path,
                )
                continue
            version = entry.get("version")
            version_str = version if isinstance(version, str) else None
            category = entry.get("category")
            is_dev = category == "dev"
            optional_marker = entry.get("optional")
            is_optional = bool(optional_marker) if isinstance(optional_marker, bool) else False
            markers = _normalize_marker(entry.get("markers"))
            if not is_optional and markers is not None:
                is_optional = _classify_optional(markers)
            extras = entry.get("extras")
            extras_list: list[str] | None = None
            if isinstance(extras, list):
                extras_list = [str(e) for e in extras if isinstance(e, str)]
            elif isinstance(extras, str):
                extras_list = [extras]
            source = entry.get("source")
            source_url: str | None = None
            if isinstance(source, dict):
                url = source.get("url")
                if isinstance(url, str):
                    source_url = url
            content_hash = entry.get("content-hash") or entry.get("hash")
            integrity: str | None = None
            if isinstance(content_hash, str) and content_hash:
                integrity = f"sha256:{content_hash}"
            unsupported = source is not None and not (
                isinstance(source, dict) and (source.get("type") in (None, "url"))
            )
            unsupported_kind: str | None = None
            if unsupported:
                if isinstance(source, dict):
                    kind_raw = source.get("type")
                    unsupported_kind = str(kind_raw) if isinstance(kind_raw, str) else "unknown"
                else:
                    unsupported_kind = "unknown"

            relationship = "transitive"
            if is_dev:
                relationship = "development"
            elif is_optional:
                relationship = "optional"

            edges = self._build_edges(entry.get("dependencies"))
            record: dict[str, Any] = {
                "kind": "package",
                "ecosystem": self.ecosystem,
                "package_name": name,
                "scope": None,
                "version": version_str,
                "version_source": "LOCKFILE" if version_str else "UNRESOLVED",
                "package_url": (
                    build_package_url(self.ecosystem, name, version_str)
                    if version_str
                    else build_package_url(self.ecosystem, name, None)
                ),
                "relationship": relationship,
                "direct": False,
                "development": is_dev,
                "optional": is_optional,
                "integrity": integrity,
                "extras": extras_list,
                "marker": markers,
                "specifier": version_str,
                "is_unsupported": unsupported,
                "unsupported_kind": unsupported_kind,
                "unsupported_detail": source_url,
                "source_path": path,
                "edges": edges,
            }
            validate_record(record)
            records.append(record)

        return finalize_parse(collector, records)

    def _build_edges(self, deps: Any) -> list[dict[str, Any]] | None:
        if not isinstance(deps, dict):
            return None
        edges: list[dict[str, Any]] = []
        for child_name, child_value in deps.items():
            if not isinstance(child_name, str) or not child_name:
                continue
            child_version, child_source = _version_from_value(child_value)
            edge: dict[str, Any] = {
                "parent_name": None,
                "parent_version": None,
                "child_name": child_name,
                "child_version": child_version,
                "child_specifier": child_version,
                "child_version_source": child_source,
                "child_is_unsupported": False,
                "child_unsupported_kind": None,
                "child_unsupported_detail": None,
                "relationship": "runtime",
                "depth": 1,
            }
            edges.append(edge)
            if len(edges) >= 256:
                break
        return edges or None
