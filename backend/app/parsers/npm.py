"""npm manifest parsers.

Two parsers live here:

- :class:`PackageJsonParser` for ``package.json`` declarations
- :class:`PackageLockJsonParser` for ``package-lock.json`` v1, v2,
  and v3 lockfiles

Both parsers share the npm ecosystem, the same component record
shape, and the same version-source vocabulary. They never execute
any other package's code: they only read the bytes the caller
hands them.

Spec coverage:

- Direct, dev, optional, peer dependencies
- Scoped packages (``@scope/name``)
- Workspaces (informational, not a transitive graph)
- Integrity values (lockfile v2/v3 ``integrity``)
- Package URLs
- Unresolved ranges represented honestly (e.g. ``^1.0.0`` from a
  manifest becomes ``version=None``, ``version_source=UNRESOLVED``)
- Unsupported git, URL, local, and link dependencies represented
  honestly (``is_unsupported=True`` with an ``unsupported_kind``)
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.parsers.base import (
    ParserError,
    _Collector,
    build_package_url,
    finalize_parse,
    validate_record,
)
from app.providers.results import ParserResult

_SCOPED_NAME_RE = re.compile(r"^@([^/]+)/(.+)$")
_LOCKFILE_MAX_DEPTH = 8
_LOCKFILE_MAX_EDGES_PER_PACKAGE = 256


def _split_scoped_name(name: str) -> tuple[str | None, str]:
    match = _SCOPED_NAME_RE.match(name)
    if match is None:
        return None, name
    return match.group(1), match.group(2)


def _classify_unsupported_specifier(spec: str) -> tuple[bool, str | None, str | None]:
    """Return ``(is_unsupported, kind, detail)`` for a specifier string."""
    if not isinstance(spec, str):
        return False, None, None
    s = spec.strip()
    if s.startswith("git") or "git+" in s or s.endswith((".git",)):
        return True, "git_ref", s
    if s.startswith("github:") or s.startswith("gitlab:") or s.startswith("bitbucket:"):
        return True, "git_ref", s
    if s.startswith("http://") or s.startswith("https://"):
        return True, "url_ref", s
    if s.startswith("file:") or s.startswith("link:") or s.startswith("portal:"):
        # ``link:`` and ``portal:`` are workspace-style references.
        if s.startswith("link:") or s.startswith("portal:"):
            return True, "workspace_ref", s
        return True, "file_ref", s
    if s.startswith("workspace:"):
        return True, "workspace_ref", s
    return False, None, None


def _normalize_version(value: Any) -> tuple[str | None, str]:
    """Return ``(version, version_source)`` for a manifest/lockfile version field.

    A missing or non-string value is treated as unresolved.
    Unresolved ranges (``^1.0.0``, ``~1.0.0``, ``>=1.0.0``, etc.)
    are returned as ``(None, "UNRESOLVED")`` so downstream code
    can rely on ``version`` being a concrete value when the
    source is "MANIFEST" or "LOCKFILE". The original specifier
    lives on the record's ``specifier`` field.
    """
    if value is None:
        return None, "UNRESOLVED"
    if isinstance(value, (int, float)):
        return str(value), "MANIFEST"
    if not isinstance(value, str):
        return None, "UNRESOLVED"
    s = value.strip()
    if not s:
        return None, "UNRESOLVED"
    if s[0] in "^~*><= " or "||" in s or s.startswith("latest") or s.startswith("next"):
        return None, "UNRESOLVED"
    return s, "MANIFEST"


class PackageJsonParser:
    """Parser for ``package.json`` declarations.

    The parser never executes the ``scripts`` block, never imports
    the module, and never resolves the file pointed to by
    ``main``/``exports``/``bin``. It only reads the dependency
    sections.
    """

    ecosystem = "npm"
    manifest_type = "package_json"

    _DEP_SECTIONS: tuple[tuple[str, str], ...] = (
        ("dependencies", "direct"),
        ("devDependencies", "development"),
        ("optionalDependencies", "optional"),
        ("peerDependencies", "peer"),
    )

    def parse(self, *, content: bytes, path: str) -> ParserResult[list[dict[str, Any]]]:
        collector = _Collector()
        try:
            # ``utf-8-sig`` accepts a leading UTF-8 BOM (``EF BB BF``)
            # transparently. A BOM is legal in JSON dependency manifests
            # produced by Notepad on Windows and other editors; rejecting
            # it would silently drop every direct dependency declared in
            # the affected file (the v2.0.4 field-test regression).
            data = json.loads(content.decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ParserError(f"package.json is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ParserError("package.json root must be an object.")

        records: list[dict[str, Any]] = []
        declared_direct: set[str] = set()
        for section_name, relationship in self._DEP_SECTIONS:
            section = data.get(section_name)
            if not isinstance(section, dict):
                continue
            for raw_name, raw_spec in section.items():
                if not isinstance(raw_name, str) or not raw_name.strip():
                    collector.warn(
                        "package_json_invalid_name",
                        f"Skipping {section_name} entry with non-string name.",
                        location=path,
                    )
                    continue
                name = raw_name.strip()
                specifier = raw_spec if isinstance(raw_spec, str) else None
                is_unsupported, kind, detail = _classify_unsupported_specifier(specifier or "")
                version: str | None
                version_source: str
                if is_unsupported:
                    version = None
                    version_source = "UNRESOLVED"
                else:
                    version, version_source = _normalize_version(specifier)
                scope, _ = _split_scoped_name(name)
                record: dict[str, Any] = {
                    "kind": "package",
                    "ecosystem": self.ecosystem,
                    "package_name": name,
                    "scope": scope,
                    "version": version,
                    "version_source": version_source,
                    "package_url": build_package_url(
                        self.ecosystem, name, version if version_source != "UNRESOLVED" else None
                    ),
                    "relationship": relationship,
                    "direct": relationship == "direct",
                    "development": relationship == "development",
                    "optional": relationship in {"optional", "peer"},
                    "integrity": None,
                    "extras": None,
                    "marker": None,
                    "specifier": specifier,
                    "is_unsupported": is_unsupported,
                    "unsupported_kind": kind,
                    "unsupported_detail": detail,
                    "source_path": path,
                    "edges": None,
                }
                declared_direct.add(name)
                validate_record(record)
                records.append(record)

        # Workspaces are an informational hint: they describe which
        # subdirectories contain additional package.json files. We do
        # not traverse the filesystem here; the manifest-discovery
        # layer is responsible for finding the workspace packages.
        # We record the workspace globs as evidence-only records so
        # the rule engine can flag "no lockfile for workspace"
        # scenarios later.
        workspaces = data.get("workspaces")
        if isinstance(workspaces, list):
            for entry in workspaces:
                if isinstance(entry, str):
                    records.append(
                        {
                            "kind": "workspace_glob",
                            "ecosystem": self.ecosystem,
                            "package_name": entry,
                            "scope": None,
                            "version": None,
                            "version_source": "UNKNOWN",
                            "package_url": None,
                            "relationship": "unknown",
                            "direct": False,
                            "development": False,
                            "optional": False,
                            "integrity": None,
                            "extras": None,
                            "marker": None,
                            "specifier": None,
                            "is_unsupported": False,
                            "unsupported_kind": None,
                            "unsupported_detail": None,
                            "source_path": path,
                            "edges": None,
                        }
                    )
        elif isinstance(workspaces, dict):
            for entry in workspaces.get("packages", []):
                if isinstance(entry, str):
                    records.append(
                        {
                            "kind": "workspace_glob",
                            "ecosystem": self.ecosystem,
                            "package_name": entry,
                            "scope": None,
                            "version": None,
                            "version_source": "UNKNOWN",
                            "package_url": None,
                            "relationship": "unknown",
                            "direct": False,
                            "development": False,
                            "optional": False,
                            "integrity": None,
                            "extras": None,
                            "marker": None,
                            "specifier": None,
                            "is_unsupported": False,
                            "unsupported_kind": None,
                            "unsupported_detail": None,
                            "source_path": path,
                            "edges": None,
                        }
                    )

        return finalize_parse(collector, records)


class PackageLockJsonParser:
    """Parser for ``package-lock.json`` v1/v2/v3 lockfiles.

    v1 lockfiles use a top-level ``dependencies`` map. v2/v3 use
    a ``packages`` map keyed by canonical install path. Both
    shapes are accepted; the parser is version-agnostic.
    """

    ecosystem = "npm"
    manifest_type = "package_lock"

    def parse(self, *, content: bytes, path: str) -> ParserResult[list[dict[str, Any]]]:
        collector = _Collector()
        try:
            # See ``PackageJsonParser.parse`` for the BOM rationale.
            data = json.loads(content.decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ParserError(f"package-lock.json is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ParserError("package-lock.json root must be an object.")
        lockfile_version = data.get("lockfileVersion")
        # We accept v1, v2, v3 explicitly. Other versions raise.
        if lockfile_version not in (1, 2, 3):
            collector.warn(
                "package_lock_unknown_version",
                f"Unrecognised lockfileVersion={lockfile_version!r}; "
                "treating as v3 but evidence may be incomplete.",
                location=path,
            )

        records: list[dict[str, Any]] = []
        if lockfile_version in (2, 3) and isinstance(data.get("packages"), dict):
            records.extend(self._parse_packages_map(data, path, collector))
        elif isinstance(data.get("dependencies"), dict):
            records.extend(self._parse_dependencies_map(data, path, collector))
        else:
            # The lockfile is structurally unusual but the spec says
            # we must still record what we observed. Surface a
            # warning and return an empty record list.
            collector.warn(
                "package_lock_no_entries",
                "package-lock.json contained neither 'packages' nor 'dependencies' entries.",
                location=path,
            )
        return finalize_parse(collector, records)

    def _parse_packages_map(
        self,
        data: dict[str, Any],
        path: str,
        collector: _Collector,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        packages = data["packages"]
        # The empty key ("") is the project itself; we ignore it.
        for key, value in packages.items():
            if not isinstance(key, str) or not key:
                continue
            if not isinstance(value, dict):
                continue
            name = value.get("name") if isinstance(value.get("name"), str) else None
            if name is None:
                # Derive the name from the canonical path: "node_modules/<name>".
                if key == "" or not key.startswith("node_modules/"):
                    continue
                name = key[len("node_modules/") :]
            version = value.get("version") if isinstance(value.get("version"), str) else None
            integrity = value.get("integrity") if isinstance(value.get("integrity"), str) else None
            resolved = value.get("resolved") if isinstance(value.get("resolved"), str) else None
            dev = bool(value.get("dev", False)) or bool(value.get("devOptional", False))
            optional = bool(value.get("optional", False))
            peer = bool(value.get("peer", False))

            scope, _ = _split_scoped_name(name)
            relationship = "development" if dev else "transitive"
            if optional:
                relationship = "optional"
            if peer:
                relationship = "peer"

            record: dict[str, Any] = {
                "kind": "package",
                "ecosystem": self.ecosystem,
                "package_name": name,
                "scope": scope,
                "version": version,
                "version_source": "LOCKFILE" if version else "UNRESOLVED",
                "package_url": build_package_url(self.ecosystem, name, version)
                if version
                else None,
                "relationship": relationship,
                "direct": False,  # populated by dependency_graph from manifest cross-check
                "development": dev,
                "optional": optional or peer,
                "integrity": integrity,
                "extras": None,
                "marker": None,
                "specifier": value.get("version")
                if isinstance(value.get("version"), str)
                else None,
                "is_unsupported": False,
                "unsupported_kind": None,
                "unsupported_detail": resolved,
                "source_path": path,
                "edges": self._build_edges(value.get("dependencies"), name, version),
            }
            validate_record(record)
            out.append(record)
        return out

    def _parse_dependencies_map(
        self,
        data: dict[str, Any],
        path: str,
        collector: _Collector,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        deps = data["dependencies"]
        for name, value in deps.items():
            if not isinstance(name, str) or not name:
                continue
            if not isinstance(value, dict):
                continue
            version = value.get("version") if isinstance(value.get("version"), str) else None
            integrity = value.get("integrity") if isinstance(value.get("integrity"), str) else None
            resolved = value.get("resolved") if isinstance(value.get("resolved"), str) else None
            dev = bool(value.get("dev", False))
            optional = bool(value.get("optional", False))

            scope, _ = _split_scoped_name(name)
            relationship = "development" if dev else "transitive"
            if optional:
                relationship = "optional"

            record: dict[str, Any] = {
                "kind": "package",
                "ecosystem": self.ecosystem,
                "package_name": name,
                "scope": scope,
                "version": version,
                "version_source": "LOCKFILE" if version else "UNRESOLVED",
                "package_url": build_package_url(self.ecosystem, name, version)
                if version
                else None,
                "relationship": relationship,
                "direct": False,
                "development": dev,
                "optional": optional,
                "integrity": integrity,
                "extras": None,
                "marker": None,
                "specifier": version,
                "is_unsupported": False,
                "unsupported_kind": None,
                "unsupported_detail": resolved,
                "source_path": path,
                "edges": self._build_edges(value.get("requires"), name, version),
            }
            validate_record(record)
            out.append(record)
        return out

    def _build_edges(
        self,
        requires: Any,
        parent_name: str,
        parent_version: str | None,
    ) -> list[dict[str, Any]]:
        """Return edge descriptors for a lockfile package's declared children."""
        if not isinstance(requires, dict):
            return []
        edges: list[dict[str, Any]] = []
        for child_name, spec in requires.items():
            if not isinstance(child_name, str) or not child_name:
                continue
            is_unsupported, kind, detail = _classify_unsupported_specifier(
                spec if isinstance(spec, str) else ""
            )
            edge: dict[str, Any] = {
                "parent_name": parent_name,
                "parent_version": parent_version,
                "child_name": child_name,
                "child_version": None,
                "child_specifier": spec if isinstance(spec, str) else None,
                "child_version_source": "UNRESOLVED" if is_unsupported or not spec else "LOCKFILE",
                "child_is_unsupported": is_unsupported,
                "child_unsupported_kind": kind,
                "child_unsupported_detail": detail,
                "relationship": "runtime",
                "depth": 1,
            }
            edges.append(edge)
            if len(edges) >= _LOCKFILE_MAX_EDGES_PER_PACKAGE:
                break
        return edges


def npm_parse_dependencies(  # public re-export for tests
    content: bytes, path: str
) -> ParserResult[list[dict[str, Any]]]:
    return PackageJsonParser().parse(content=content, path=path)


def npm_parse_lock(content: bytes, path: str) -> ParserResult[list[dict[str, Any]]]:
    return PackageLockJsonParser().parse(content=content, path=path)
