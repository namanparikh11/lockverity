"""Write-side helpers for scan analysis.

The read services expose paginated queries against the database.
The write services persist the artefacts the orchestrator
produces: components, dependency edges, findings. The orchestrator
itself is the single entry point that produces them; this module
is the persistence layer below the orchestrator.

Splitting the write helpers out keeps the orchestrator service
small and focused on the pipeline order, and keeps the SQL
inside this module testable in isolation.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from app.models.component import Component, ComponentVersionSource
from app.models.component_advisory import ComponentAdvisory
from app.models.dependency_edge import DependencyEdge
from app.models.finding import (
    Finding,
    FindingCategory,
    FindingConfidence,
    FindingSeverity,
    FindingStatus,
)
from app.models.manifest import Manifest, ManifestParseStatus
from app.providers.results import FindingEvidence
from app.utils.errors import ApiError, ApiErrorCode

logger = logging.getLogger("lockverity.write")

# Maximum length of the ``evidence_json`` blob. Matches the
# database CHECK constraint in :class:`app.models.finding.Finding`.
_MAX_EVIDENCE_BYTES = 65_536

# Maximum number of findings persisted in a single batch. The
# orchestrator may produce many rules firing; we batch the inserts
# so the test SQLite and production PostgreSQL behave the same.
_MAX_FINDING_BATCH = 200


def upsert_components(
    session: Session,
    *,
    scan_run_id: int,
    records: Iterable[dict[str, Any]],
) -> list[int]:
    """Insert component records.

    Returns the list of new component ids in iteration order.
    The caller is expected to map these back to manifests using
    the envelopes it passed in.
    """
    ids: list[int] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        package_name = record.get("package_name")
        if not isinstance(package_name, str) or not package_name:
            continue
        manifest_id = record.get("manifest_id")
        if not isinstance(manifest_id, int):
            # A component without a manifest_id is a bug in the
            # orchestrator; we surface it loudly rather than
            # silently dropping the row.
            raise ApiError(
                ApiErrorCode.INTERNAL,
                "Component record is missing a manifest_id.",
                details={"package_name": package_name},
            )
        version = record.get("version")
        if not isinstance(version, str):
            version = None
        version_source_raw = record.get("version_source")
        try:
            version_source = ComponentVersionSource(version_source_raw)
        except ValueError:
            version_source = ComponentVersionSource.UNKNOWN
        component = Component(
            scan_run_id=scan_run_id,
            manifest_id=manifest_id,
            ecosystem=record.get("ecosystem"),
            package_name=package_name,
            version=version,
            version_source=version_source,
            package_url=record.get("package_url"),
            scope=record.get("scope"),
            relationship=record.get("relationship"),
            direct=bool(record.get("direct", False)),
            development=bool(record.get("development", False)),
            optional=bool(record.get("optional", False)),
            integrity=record.get("integrity"),
        )
        session.add(component)
        session.flush()
        ids.append(component.id)
    return ids


def upsert_dependency_edges(
    session: Session,
    *,
    scan_run_id: int,
    edges: Iterable[dict[str, Any]],
) -> int:
    """Insert dependency-edge rows. Returns the number inserted."""
    inserted = 0
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        parent = edge.get("parent_component_id")
        child = edge.get("child_component_id")
        if not isinstance(parent, int) or not isinstance(child, int):
            continue
        session.add(
            DependencyEdge(
                scan_run_id=scan_run_id,
                parent_component_id=parent,
                child_component_id=child,
                relationship=edge.get("relationship"),
                depth=int(edge.get("depth", 1) or 1),
            )
        )
        inserted += 1
    return inserted


def upsert_component_advisories(
    session: Session,
    *,
    scan_run_id: int,
    records: Iterable[dict[str, Any]],
) -> int:
    """Insert component_advisories rows from the vulnerability stage."""
    inserted = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        component_id = record.get("component_id")
        advisory_id = record.get("advisory_id")
        if not isinstance(component_id, int) or not isinstance(advisory_id, int):
            continue
        session.add(
            ComponentAdvisory(
                scan_run_id=scan_run_id,
                component_id=component_id,
                advisory_id=advisory_id,
                affected=bool(record.get("affected", True)),
                fixed_versions_json=record.get("fixed_versions_json"),
                severity_source=record.get("severity_source"),
                severity_label=record.get("severity_label"),
                severity_score=record.get("severity_score"),
                evidence_json=record.get("evidence_json"),
            )
        )
        inserted += 1
    return inserted


def update_manifest_parse_status(
    session: Session,
    *,
    manifest_id: int,
    status: ManifestParseStatus,
    content_sha256: str | None = None,
    parse_warning_count: int | None = None,
) -> None:
    """Mark a manifest as parsed, with bounded warning count."""
    manifest = session.get(Manifest, manifest_id)
    if manifest is None:
        return
    manifest.parse_status = status
    if content_sha256 is not None:
        manifest.content_sha256 = content_sha256
    if parse_warning_count is not None:
        manifest.parse_warning_count = parse_warning_count


def upsert_findings(
    session: Session,
    *,
    scan_run_id: int,
    repository_id: int,
    records: Iterable[FindingEvidence],
    default_category: str | None = None,
) -> tuple[int, int]:
    """Persist a batch of :class:`FindingEvidence` records.

    Returns ``(persisted, skipped)``. The ``stable_key`` is unique
    per scan, so re-runs of the same scan deduplicate correctly.
    Findings that would re-insert a duplicate are silently
    skipped, not raised as errors.

    If ``default_category`` is given, every persisted finding
    uses it unless the evidence record specifies one explicitly.
    This is the right path for analyzers whose findings do not
    embed the category in the raw envelope (e.g. the GitHub
    Actions analyzer; the category is implied by the rule_id
    prefix).
    """
    persisted = 0
    skipped = 0
    seen_keys: set[str] = set()
    for evidence in records:
        if not isinstance(evidence, FindingEvidence):
            continue
        raw = evidence.raw or {}
        stable_key = raw.get("stable_key")
        if not isinstance(stable_key, str) or not stable_key:
            # An evidence record without a stable key cannot be
            # deduped. We surface the gap loudly; the
            # orchestrator should not pass these through.
            logger.warning(
                "skipping finding without stable_key rule_id=%s",
                evidence.rule_id,
            )
            skipped += 1
            continue
        if stable_key in seen_keys:
            skipped += 1
            continue
        seen_keys.add(stable_key)
        # Map the raw envelope into the Finding model.
        category_str = raw.get("category")
        if not isinstance(category_str, str) or not category_str:
            category_str = default_category or _category_from_rule_id(evidence.rule_id)
        try:
            category = FindingCategory(category_str)
        except ValueError:
            category = FindingCategory.DATA_QUALITY
        try:
            severity = FindingSeverity(
                _coerce_str(raw.get("severity"), FindingSeverity.INFORMATIONAL.value)
            )
        except ValueError:
            severity = FindingSeverity.INFORMATIONAL
        try:
            confidence = FindingConfidence(
                _coerce_str(raw.get("confidence"), FindingConfidence.MEDIUM.value)
            )
        except ValueError:
            confidence = FindingConfidence.MEDIUM
        evidence_json = raw.get("evidence_json")
        if not isinstance(evidence_json, str):
            evidence_json = None
        elif len(evidence_json.encode("utf-8")) > _MAX_EVIDENCE_BYTES:
            evidence_json = evidence_json[:_MAX_EVIDENCE_BYTES]
        title = _truncate_str(_coerce_str(raw.get("title"), "Finding"), 512)
        summary = _truncate_str(_coerce_str(raw.get("summary"), ""), 2048)
        remediation = raw.get("remediation")
        if remediation is not None:
            remediation = _truncate_str(str(remediation), 4096)
        location_path = evidence.location_path
        if location_path is not None:
            location_path = _truncate_str(location_path, 1024)
        finding = Finding(
            scan_run_id=scan_run_id,
            repository_id=repository_id,
            rule_id=evidence.rule_id,
            category=category,
            severity=severity,
            confidence=confidence,
            title=title,
            summary=summary,
            remediation=remediation,
            evidence_json=evidence_json,
            location_path=location_path,
            location_start_line=evidence.location_start_line,
            location_end_line=evidence.location_end_line,
            stable_key=stable_key,
            status=FindingStatus.OPEN,
        )
        session.add(finding)
        persisted += 1
        if persisted % _MAX_FINDING_BATCH == 0:
            session.flush()
    if persisted:
        session.flush()
    return persisted, skipped


def _category_from_rule_id(rule_id: str) -> str:
    """Infer a finding category from the rule_id prefix.

    The rules in v0.3 are namespaced by category prefix:

    - ``LOCK-VULN-*`` -> vulnerability
    - ``LOCK-WF-*`` -> workflow
    - ``LOCK-LIC-*`` -> licence
    - ``LOCK-POST-*`` -> repository_posture
    - anything else -> data_quality
    """
    if not isinstance(rule_id, str):
        return FindingCategory.DATA_QUALITY.value
    upper = rule_id.upper()
    if upper.startswith("LOCK-VULN"):
        return FindingCategory.VULNERABILITY.value
    if upper.startswith("LOCK-WF"):
        return FindingCategory.WORKFLOW.value
    if upper.startswith("LOCK-LIC"):
        return FindingCategory.LICENCE.value
    if upper.startswith("LOCK-POST"):
        return FindingCategory.REPOSITORY_POSTURE.value
    return FindingCategory.DATA_QUALITY.value


def _coerce_str(value: Any, default: str) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


def _truncate_str(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."


__all__ = [
    "update_manifest_parse_status",
    "upsert_component_advisories",
    "upsert_components",
    "upsert_dependency_edges",
    "upsert_findings",
]
