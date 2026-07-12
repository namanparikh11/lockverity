"""pyproject.toml parser.

Python 3.11+ ships :mod:`tomllib` in the standard library; we use
it because we never need to write TOML and a hostile pyproject
must not be able to invoke user code. We accept the dependency
groups defined in PEP 735 (a recent, stable shape) as well as
Poetry's ``[tool.poetry.dependencies]`` and ``[tool.poetry.group.*]``
sections when present.
"""

from __future__ import annotations

import re
import tomllib as _toml  # type: ignore[no-redef, import-not-found]
from typing import Any

from app.parsers.base import (
    ParserError,
    _Collector,
    build_package_url,
    finalize_parse,
)
from app.parsers.requirements import _PIN_RE, _name_to_pypi_normalized
from app.providers.results import ParserResult

_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(.*)$")


def _classify_unsupported(ref: Any) -> tuple[bool, str | None, str | None]:
    if not isinstance(ref, str):
        return False, None, None
    s = ref.strip()
    if not s:
        return False, None, None
    # Handle the PEP 508 ``name @ ref`` syntax. The reference is
    # the part after the ``@``.
    if " @ " in s:
        _, _, ref_part = s.partition(" @ ")
        return _classify_unsupported(ref_part)
    if s.startswith("git+") or s.startswith("git@") or s.startswith("git://"):
        return True, "git_ref", s
    if s.startswith("https://") or s.startswith("http://"):
        return True, "url_ref", s
    if s.startswith("file://") or s.startswith("./") or s.startswith("/") or s.startswith(".."):
        return True, "path_ref", s
    return False, None, None


def _version_from_value(value: Any) -> tuple[str | None, str]:
    """Return ``(version, version_source)`` for a TOML dependency value."""
    if isinstance(value, str):
        match = _PIN_RE.search(value)
        if match is None:
            return None, "UNRESOLVED"
        op, version = match.group(1), match.group(2)
        if op in ("==", "==="):
            return version, "MANIFEST"
        return version, "UNRESOLVED"
    if isinstance(value, dict):
        # PEP 508 dict form: { version = "1.0", optional = true, markers = "...", ... }
        version = value.get("version")
        if isinstance(version, str):
            match = _PIN_RE.search(version)
            if match is None:
                return None, "UNRESOLVED"
            op, ver = match.group(1), match.group(2)
            if op in ("==", "==="):
                return ver, "MANIFEST"
            return ver, "UNRESOLVED"
        if version is None:
            return None, "UNRESOLVED"
    return None, "UNRESOLVED"


class PyprojectTomlParser:
    ecosystem = "pypi"
    manifest_type = "pyproject_toml"

    def parse(self, *, content: bytes, path: str) -> ParserResult[list[dict[str, Any]]]:
        collector = _Collector()
        try:
            data = _toml.loads(content.decode("utf-8"))
        except _toml.TOMLDecodeError as exc:  # type: ignore[attr-defined]
            raise ParserError(f"pyproject.toml is not valid TOML: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise ParserError(f"pyproject.toml is not valid UTF-8: {exc}") from exc
        if not isinstance(data, dict):
            raise ParserError("pyproject.toml root must be a table.")

        records: list[dict[str, Any]] = []
        seen_normalized: set[str] = set()

        # [project] section (PEP 621).
        project = data.get("project")
        if isinstance(project, dict):
            self._emit_section(
                project.get("dependencies"),
                path=path,
                relationship="direct",
                development=False,
                optional=False,
                records=records,
                seen=seen_normalized,
                collector=collector,
            )
            optional_deps = project.get("optional-dependencies")
            if isinstance(optional_deps, dict):
                for extra, entries in optional_deps.items():
                    if not isinstance(extra, str):
                        continue
                    self._emit_section(
                        entries,
                        path=path,
                        relationship="optional",
                        development=False,
                        optional=True,
                        extras=[extra],
                        records=records,
                        seen=seen_normalized,
                        collector=collector,
                    )

        # [dependency-groups] section (PEP 735) lives at the top
        # level, not under ``[project]``.
        dep_groups = data.get("dependency-groups")
        if isinstance(dep_groups, dict):
            for group_name, group_entries in dep_groups.items():
                if not isinstance(group_name, str):
                    continue
                is_dev = group_name in {"dev", "test", "lint", "typecheck", "docs"}
                self._emit_section(
                    group_entries,
                    path=path,
                    relationship="development" if is_dev else "transitive",
                    development=is_dev,
                    optional=False,
                    group_name=group_name,
                    records=records,
                    seen=seen_normalized,
                    collector=collector,
                )

        # [tool.poetry.dependencies] and [tool.poetry.group.*.dependencies].
        tool = data.get("tool")
        if isinstance(tool, dict):
            poetry = tool.get("poetry")
            if isinstance(poetry, dict):
                self._emit_section(
                    poetry.get("dependencies"),
                    path=path,
                    relationship="direct",
                    development=False,
                    optional=False,
                    records=records,
                    seen=seen_normalized,
                    collector=collector,
                    poetry_python_marker=poetry.get("dependencies", {}).get("python")
                    if isinstance(poetry.get("dependencies"), dict)
                    else None,
                )
                groups = poetry.get("group")
                if isinstance(groups, dict):
                    for group_name, group_def in groups.items():
                        if not isinstance(group_name, str) or not isinstance(group_def, dict):
                            continue
                        group_deps = group_def.get("dependencies")
                        if not isinstance(group_deps, dict):
                            continue
                        is_dev = bool(group_def.get("optional", False)) is False and group_name in {
                            "dev",
                            "test",
                            "lint",
                            "docs",
                        }
                        self._emit_section(
                            group_deps,
                            path=path,
                            relationship="development" if is_dev else "transitive",
                            development=is_dev,
                            optional=False,
                            group_name=group_name,
                            records=records,
                            seen=seen_normalized,
                            collector=collector,
                        )

        return finalize_parse(collector, records)

    def _emit_section(
        self,
        section: Any,
        *,
        path: str,
        relationship: str,
        development: bool,
        optional: bool,
        records: list[dict[str, Any]],
        seen: set[str],
        collector: _Collector,
        extras: list[str] | None = None,
        group_name: str | None = None,
        poetry_python_marker: str | None = None,
    ) -> None:
        if isinstance(section, list):
            for entry in section:
                if isinstance(entry, str):
                    self._emit_one_string(
                        entry,
                        path=path,
                        relationship=relationship,
                        development=development,
                        optional=optional,
                        records=records,
                        seen=seen,
                        collector=collector,
                        extras=extras,
                        group_name=group_name,
                    )
                elif isinstance(entry, dict):
                    self._emit_one_dict(
                        entry,
                        path=path,
                        relationship=relationship,
                        development=development,
                        optional=optional,
                        records=records,
                        seen=seen,
                        collector=collector,
                        extras=extras,
                        group_name=group_name,
                    )
            return
        if isinstance(section, dict):
            for name, value in section.items():
                if not isinstance(name, str):
                    continue
                if name.lower() == "python":
                    continue
                self._emit_one_mapping(
                    name,
                    value,
                    path=path,
                    relationship=relationship,
                    development=development,
                    optional=optional,
                    records=records,
                    seen=seen,
                    collector=collector,
                    extras=extras,
                    group_name=group_name,
                    python_marker=poetry_python_marker,
                )

    def _emit_one_string(
        self,
        entry: str,
        *,
        path: str,
        relationship: str,
        development: bool,
        optional: bool,
        records: list[dict[str, Any]],
        seen: set[str],
        collector: _Collector,
        extras: list[str] | None,
        group_name: str | None,
    ) -> None:
        is_unsupported, kind, detail = _classify_unsupported(entry)
        if is_unsupported:
            name = self._name_from_ref(entry)
            if name is None:
                collector.warn(
                    "pyproject_unknown_ref",
                    f"Could not derive a name from {entry!r}.",
                    location=path,
                )
                return
            normalized = _name_to_pypi_normalized(name)
            if normalized in seen:
                return
            seen.add(normalized)
            records.append(
                {
                    "kind": "package",
                    "ecosystem": self.ecosystem,
                    "package_name": name,
                    "scope": None,
                    "version": None,
                    "version_source": "UNRESOLVED",
                    "package_url": build_package_url(self.ecosystem, name, None),
                    "relationship": relationship,
                    "direct": not development,
                    "development": development,
                    "optional": optional,
                    "integrity": None,
                    "extras": extras,
                    "marker": None,
                    "specifier": entry,
                    "is_unsupported": True,
                    "unsupported_kind": kind,
                    "unsupported_detail": detail,
                    "source_path": path,
                    "edges": None,
                }
            )
            return
        name, rest = self._split_name_rest(entry)
        if not _NAME_RE.match(name):
            collector.warn(
                "pyproject_invalid_name",
                f"Invalid package name {name!r}.",
                location=path,
            )
            return
        normalized = _name_to_pypi_normalized(name)
        if normalized in seen:
            return
        seen.add(normalized)
        version, version_source = _version_from_value(rest or entry)
        records.append(
            {
                "kind": "package",
                "ecosystem": self.ecosystem,
                "package_name": name,
                "scope": None,
                "version": version,
                "version_source": version_source,
                "package_url": (
                    build_package_url(self.ecosystem, name, version)
                    if version
                    else build_package_url(self.ecosystem, name, None)
                ),
                "relationship": relationship,
                "direct": not development,
                "development": development,
                "optional": optional,
                "integrity": None,
                "extras": extras,
                "marker": None,
                "specifier": entry,
                "is_unsupported": False,
                "unsupported_kind": None,
                "unsupported_detail": None,
                "source_path": path,
                "edges": None,
            }
        )

    def _emit_one_dict(
        self,
        entry: dict[str, Any],
        *,
        path: str,
        relationship: str,
        development: bool,
        optional: bool,
        records: list[dict[str, Any]],
        seen: set[str],
        collector: _Collector,
        extras: list[str] | None,
        group_name: str | None,
    ) -> None:
        include = entry.get("include")
        if not isinstance(include, str):
            collector.warn(
                "pyproject_group_entry_missing_include",
                f"Group entry {entry!r} missing 'include' field.",
                location=path,
            )
            return
        if entry.get("optional") is True:
            optional = True
        in_group = entry.get("in-group") if isinstance(entry.get("in-group"), str) else group_name
        self._emit_one_string(
            include,
            path=path,
            relationship=relationship,
            development=development,
            optional=optional,
            records=records,
            seen=seen,
            collector=collector,
            extras=extras,
            group_name=in_group,
        )

    def _emit_one_mapping(
        self,
        name: str,
        value: Any,
        *,
        path: str,
        relationship: str,
        development: bool,
        optional: bool,
        records: list[dict[str, Any]],
        seen: set[str],
        collector: _Collector,
        extras: list[str] | None,
        group_name: str | None,
        python_marker: str | None,
    ) -> None:
        if isinstance(value, dict):
            if value.get("optional") is True:
                optional = True
            if value.get("python"):
                python_marker = value.get("python")
            if "git" in value or "url" in value or "path" in value or "file" in value:
                ref = value.get("git") or value.get("url") or value.get("path") or value.get("file")
                is_unsupported, kind, detail = _classify_unsupported(ref)
                if is_unsupported:
                    normalized = _name_to_pypi_normalized(name)
                    if normalized in seen:
                        return
                    seen.add(normalized)
                    records.append(
                        {
                            "kind": "package",
                            "ecosystem": self.ecosystem,
                            "package_name": name,
                            "scope": None,
                            "version": None,
                            "version_source": "UNRESOLVED",
                            "package_url": build_package_url(self.ecosystem, name, None),
                            "relationship": relationship,
                            "direct": not development,
                            "development": development,
                            "optional": optional,
                            "integrity": None,
                            "extras": extras,
                            "marker": python_marker,
                            "specifier": ref if isinstance(ref, str) else None,
                            "is_unsupported": True,
                            "unsupported_kind": kind,
                            "unsupported_detail": detail,
                            "source_path": path,
                            "edges": None,
                        }
                    )
                    return
            version, version_source = _version_from_value(value)
        else:
            version, version_source = _version_from_value(value)
        if not _NAME_RE.match(name):
            collector.warn(
                "pyproject_invalid_name",
                f"Invalid package name {name!r}.",
                location=path,
            )
            return
        normalized = _name_to_pypi_normalized(name)
        if normalized in seen:
            return
        seen.add(normalized)
        records.append(
            {
                "kind": "package",
                "ecosystem": self.ecosystem,
                "package_name": name,
                "scope": None,
                "version": version,
                "version_source": version_source,
                "package_url": (
                    build_package_url(self.ecosystem, name, version)
                    if version
                    else build_package_url(self.ecosystem, name, None)
                ),
                "relationship": relationship,
                "direct": not development,
                "development": development,
                "optional": optional,
                "integrity": None,
                "extras": extras,
                "marker": python_marker,
                "specifier": value if isinstance(value, str) else None,
                "is_unsupported": False,
                "unsupported_kind": None,
                "unsupported_detail": None,
                "source_path": path,
                "edges": None,
            }
        )

    @staticmethod
    def _split_name_rest(entry: str) -> tuple[str, str]:
        """Return ``(name, rest)`` for a PEP 508 name token.

        The name is the leading identifier (alphanumeric plus
        ``-``, ``_``, and ``.``). The remainder of the line
        (which may include version specifiers, extras, and a
        ``;`` marker) is returned as ``rest``.
        """
        match = _NAME_RE.match(entry.strip())
        if match is None:
            raise ValueError(f"could not extract a name from {entry!r}")
        return match.group(1), match.group(2)

    @staticmethod
    def _name_from_ref(ref: str) -> str | None:
        s = ref.strip()
        for prefix in ("git+", "https://", "http://", "file://"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        if "@" in s and not s.startswith("git@"):
            s = s.split("@", 1)[0]
        last = s.rsplit("/", 1)[-1]
        if last.endswith(".git"):
            last = last[: -len(".git")]
        return last or None
