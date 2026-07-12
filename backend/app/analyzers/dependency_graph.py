"""Dependency graph builder.

The orchestrator calls :func:`build_dependency_components`
with the parser outputs of a single scan and gets back a
deterministic list of component records and edges suitable for
persistence into the ``components`` and ``dependency_edges``
tables. Cross-references between the manifest declarations and
the lockfile resolutions are applied here:

- A package declared in ``package.json`` / ``pyproject.toml`` /
  ``requirements.txt`` is marked ``direct=True``.
- A package present only in a lockfile is marked ``direct=False``.
- Workspace packages and unsupported references are preserved
  with their parser-annotated ``is_unsupported`` flag.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.models.component import ComponentVersionSource
from app.providers.results import FindingEvidence
from app.utils.finding_keys import stable_finding_key

# Mapping from parser-internal ``version_source`` to ORM enum.
_VERSION_SOURCE_MAP: dict[str, str] = {
    "MANIFEST": ComponentVersionSource.MANIFEST.value,
    "LOCKFILE": ComponentVersionSource.LOCKFILE.value,
    "OVERRIDE": ComponentVersionSource.OVERRIDE.value,
    "UNRESOLVED": ComponentVersionSource.UNRESOLVED.value,
    "UNKNOWN": ComponentVersionSource.UNKNOWN.value,
}


def _orm_version_source(value: str) -> str:
    return _VERSION_SOURCE_MAP.get(value, ComponentVersionSource.UNKNOWN.value)


def build_dependency_components(
    parser_results: Iterable[dict[str, Any]],
    *,
    manifests_by_path: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[FindingEvidence]]:
    """Return ``(components, edges, findings)`` for a scan.

    ``parser_results`` is an iterable of *envelope* dicts, one per
    parsed manifest, of the shape ``{"manifest": <manifest_record>,
    "records": <list of component records from the parser> }``.

    ``manifests_by_path`` is an optional mapping of manifest path to
    a small envelope of metadata (``manifest_type``,
    ``content_sha256``); when provided, it is used to populate
    ``manifest_id`` placeholders and to emit ``LOCK-VULN-010``
    (missing lockfile) findings.
    """
    components: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    findings: list[FindingEvidence] = []

    by_ecosystem_direct: dict[str, set[str]] = {}
    manifests_by_path = manifests_by_path or {}
    ecosystem_lockfile_seen: dict[str, bool] = {}

    # First pass: collect direct dependencies and the resolved
    # packages from each manifest.
    for envelope in parser_results:
        manifest = envelope.get("manifest") or {}
        records = envelope.get("records") or []
        if not isinstance(manifest, dict):
            manifest = {}
        if not isinstance(records, list):
            continue
        manifest_path = manifest.get("path")
        manifest_type = manifest.get("manifest_type")
        ecosystem = manifest.get("ecosystem")
        is_lockfile = isinstance(manifest_type, str) and manifest_type.endswith("_lock")
        if isinstance(ecosystem, str) and is_lockfile:
            ecosystem_lockfile_seen[ecosystem] = True
        for record in records:
            if not isinstance(record, dict):
                continue
            if record.get("kind") not in (None, "package"):
                # Skip workspace globs and other non-package records.
                continue
            name = record.get("package_name")
            if not isinstance(name, str) or not name:
                continue
            relationship = record.get("relationship")
            direct = bool(record.get("direct"))
            if ecosystem and relationship in {"direct", "development", "optional", "peer"}:
                by_ecosystem_direct.setdefault(ecosystem, set()).add(name)
            component = {
                "package_name": name,
                "scope": record.get("scope"),
                "version": record.get("version"),
                "version_source": _orm_version_source(str(record.get("version_source") or "UNKNOWN")),
                "package_url": record.get("package_url"),
                "relationship": relationship,
                "direct": direct,
                "development": bool(record.get("development")),
                "optional": bool(record.get("optional")),
                "integrity": record.get("integrity"),
                "ecosystem": ecosystem,
                "manifest_path": manifest_path,
                "manifest_type": manifest_type,
                "extras": record.get("extras"),
                "marker": record.get("marker"),
                "is_unsupported": bool(record.get("is_unsupported")),
                "unsupported_kind": record.get("unsupported_kind"),
                "unsupported_detail": record.get("unsupported_detail"),
                "specifier": record.get("specifier"),
            }
            components.append(component)
            edges_for_package = record.get("edges")
            if isinstance(edges_for_package, list):
                for edge in edges_for_package:
                    if not isinstance(edge, dict):
                        continue
                    edge_record = {
                        "parent_name": name,
                        "parent_version": record.get("version"),
                        "child_name": edge.get("child_name"),
                        "child_version": edge.get("child_version"),
                        "child_version_source": edge.get("child_version_source"),
                        "child_is_unsupported": bool(edge.get("child_is_unsupported")),
                        "child_unsupported_kind": edge.get("child_unsupported_kind"),
                        "child_unsupported_detail": edge.get("child_unsupported_detail"),
                        "relationship": edge.get("relationship", "runtime"),
                        "depth": int(edge.get("depth") or 1),
                    }
                    edges.append(edge_record)

    # Second pass: mark transitive packages that are also
    # direct dependencies of the project as direct. This
    # corresponds to the npm "dev dependency also pulled in
    # transitively" case.
    for component in components:
        ecosystem = component.get("ecosystem")
        if not ecosystem:
            continue
        direct_set = by_ecosystem_direct.get(ecosystem)
        if not direct_set:
            continue
        name = component.get("package_name")
        if not isinstance(name, str):
            continue
        if name in direct_set:
            component["direct"] = True

    # Missing-lockfile observations.
    for manifest_path, meta in manifests_by_path.items():
        ecosystem = meta.get("ecosystem")
        manifest_type = meta.get("manifest_type")
        if not isinstance(manifest_type, str):
            continue
        is_decl_manifest = manifest_type in {
            "package_json",
            "pyproject_toml",
            "requirements_txt",
        }
        if not is_decl_manifest or not ecosystem:
            continue
        if ecosystem_lockfile_seen.get(ecosystem):
            continue
        # We only emit the missing-lockfile finding for
        # declaration manifests where the ecosystem has at
        # least one direct dependency.
        direct_count = sum(
            1
            for c in components
            if c.get("manifest_path") == manifest_path
            and c.get("relationship") in {"direct", "development", "optional"}
        )
        if direct_count == 0:
            continue
        evidence = {
            "ecosystem": ecosystem,
            "manifest_path": manifest_path,
            "manifest_type": manifest_type,
            "direct_count": direct_count,
        }
        stable_key = stable_finding_key(
            "LOCK-VULN-010",
            {"ecosystem": ecosystem, "manifest_path": manifest_path},
        )
        evidence["stable_key"] = stable_key
        findings.append(
            FindingEvidence(
                rule_id="LOCK-VULN-010",
                location_path=manifest_path,
                location_start_line=None,
                location_end_line=None,
                raw=evidence,
            )
        )

    return components, edges, findings


def build_dependency_graph(edges: Iterable[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    """Return a parent -> {child -> [versions]} map suitable for path finding."""
    out: dict[str, dict[str, list[str]]] = {}
    for edge in edges:
        parent = edge.get("parent_name")
        child = edge.get("child_name")
        if not isinstance(parent, str) or not isinstance(child, str):
            continue
        children = out.setdefault(parent, {})
        versions = children.setdefault(child, [])
        version = edge.get("child_version")
        if isinstance(version, str) and version not in versions:
            versions.append(version)
    return out
