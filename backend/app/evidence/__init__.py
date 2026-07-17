"""v0.8 component evidence service.

The evidence service is the single authoritative backend rule
for ``GET /api/v1/scans/{scan_id}/components/{component_id}/evidence``.
It is read-only, deterministic, and never calls a provider, never
downloads a repository, never executes analyzed code, and never
writes to the database.

The service reuses the v0.6 CycloneDX helpers for:

- PURL construction (``_bom_ref_for`` / ``PackageURL.from_string``);
- SPDX licence classification
  (``_classify_licence_value`` / ``_build_licence_objects``);
- licence evidence envelope parsing
  (``_parse_licence_evidence_json``).

These helpers are the single source of truth for the
Lockverity-wide PURL / licence / bom-ref behaviour; the
component evidence endpoint must not invent a parallel
implementation.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from app.exporters.cyclonedx_v17 import (
    _bom_ref_for,
    _classify_licence_value,
    _dependency_graph_coverage,
    _parse_licence_evidence_json,
)
from app.models.advisory import Advisory
from app.models.component import Component
from app.models.component_advisory import ComponentAdvisory
from app.models.dependency_edge import DependencyEdge
from app.models.finding import Finding, FindingCategory
from app.models.manifest import Manifest, ManifestParseStatus
from app.models.provider_observation import (
    ProviderObservation,
    ProviderStatus,
)
from app.models.scan_run import ScanRun

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Limits / contract
# ---------------------------------------------------------------------

# The evidence endpoint surfaces a bounded, deterministic shape.
# A handful of values are computed from the persisted schema; the
# rest are stable labels so the consumer can render the response
# without guessing.
ADVISORY_LIMIT = 100
PROVIDER_OBSERVATION_LIMIT = 100
DEPENDENCY_EDGE_LIMIT = 1_000

# The documented v0.8 omissions list. Exposed as a module
# constant so the test suite can assert against it. Renaming
# any marker is a contract change.
COMPONENT_EVIDENCE_OMISSIONS: tuple[str, ...] = (
    "no_clean_verdict",
    "no_security_verdict",
    "no_complete_dependency_graph_claim",
    "no_remediation_claim",
    "no_repository_code_execution",
    "missing_provider_confidence_kept_missing",
    "missing_licence_evidence_explicit",
)


# ---------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------


def build_component_evidence(
    *,
    scan: ScanRun,
    component: Component,
    manifest: Manifest | None,
    licence_records: Iterable[Finding],
    provider_observations: Iterable[ProviderObservation],
    advisory_links: Iterable[ComponentAdvisory],
    advisories: dict[int, Advisory],
    incoming_edges: Iterable[DependencyEdge],
    outgoing_edges: Iterable[DependencyEdge],
) -> dict[str, Any]:
    """Return the v0.8 component-evidence summary for ``component``.

    The function is a pure projection over already-fetched
    persisted state. It never mutates the database, never
    calls a provider, never downloads a repository, and never
    executes analyzed code. The function is deterministic for
    the same persisted evidence: every value derives from the
    database rows plus stable labels, never from the wall
    clock or any non-deterministic source.

    The shape is the documented v0.8 contract. The
    ``omissions`` block is the explicit list of evidence-
    honesty rules the consumer can rely on; renaming any
    marker is a contract change.
    """
    scan_identity = {
        "scan_id": scan.id,
        "repository_id": scan.repository_id,
        "scan_status": scan.status.value,
    }
    component_identity = _build_component_identity(component)
    manifest_block = _build_manifest_block(manifest)
    licence_block = _build_licence_block(licence_records)
    provider_block = _build_provider_block(
        provider_observations=provider_observations,
        advisory_links=advisory_links,
        advisories=advisories,
    )
    dependency_block = _build_dependency_block(
        component=component,
        manifests=([manifest] if manifest is not None else []),
        incoming_edges=incoming_edges,
        outgoing_edges=outgoing_edges,
    )
    export_implications = _build_export_implications(
        component=component,
        outgoing_edges=outgoing_edges,
        dependency_block=dependency_block,
    )
    return {
        "scan": scan_identity,
        "component": component_identity,
        "manifest": manifest_block,
        "licence_evidence": licence_block,
        "provider_evidence": provider_block,
        "dependency_evidence": dependency_block,
        "export_implications": export_implications,
        "omissions": list(COMPONENT_EVIDENCE_OMISSIONS),
    }


# ---------------------------------------------------------------------
# Internal builders
# ---------------------------------------------------------------------


def _build_component_identity(component: Component) -> dict[str, Any]:
    """Project the persisted component into the documented
    component-identity block. The block never invents a value
    the schema does not support:

    - ``version`` is emitted verbatim or ``null``.
    - ``version_source`` is the persisted enum.
    - ``package_url`` is the persisted PURL when present and
      well-formed; the standards-aware ``PackageURL`` from
      v0.6 is used as the validity check. The exported
      ``bom_ref`` is the v0.6 exporter's strategy
      (``_bom_ref_for``); the consumer sees the same
      identifier the CycloneDX 1.7 export would emit.
    - ``purl_constructible`` is the small boolean that tells
      the consumer whether the standards-aware constructor
      would have built a PURL from ecosystem + name + version
      had the persisted PURL been missing.
    """
    version_source = (
        component.version_source.value if component.version_source is not None else None
    )
    persisted_purl = component.package_url
    persisted_purl_well_formed: bool | None = None
    if persisted_purl is not None:
        persisted_purl_well_formed = _is_purl_well_formed(persisted_purl)
    # Mirror the v0.6 export fallback: when the persisted PURL
    # is null / malformed, the v0.6 exporter reconstructs a
    # PURL from ecosystem + name + version for npm / pypi.
    purl_constructible = _is_purl_constructible(component)
    # The v0.6 bom_ref strategy: PURL when present and
    # well-formed, else the deterministic
    # ``lockverity:component:{id}`` fallback. The evidence
    # block surfaces the same identifier the CycloneDX 1.7
    # export will emit, so the consumer can match them.
    bom_ref = _bom_ref_for(component)
    return {
        "id": component.id,
        "ecosystem": component.ecosystem,
        "package_name": component.package_name,
        "version": component.version,
        "version_source": version_source,
        "direct": component.direct,
        "development": component.development,
        "optional": component.optional,
        "scope": component.scope,
        "relationship": component.relationship,
        "integrity": component.integrity,
        "package_url": persisted_purl,
        "package_url_well_formed": persisted_purl_well_formed,
        "purl_constructible": purl_constructible,
        "bom_ref": bom_ref,
    }


def _is_purl_well_formed(purl: str) -> bool:
    """Return True when the standards-aware ``PackageURL``
    constructor accepts the persisted PURL. The check is the
    same round-trip the v0.6 exporter uses; the evidence
    endpoint never invents a PURL on top of a malformed one.
    """
    try:
        from packageurl import PackageURL
    except ImportError:  # pragma: no cover - defensive
        return False
    try:
        PackageURL.from_string(purl)
        return True
    except Exception:
        return False


def _is_purl_constructible(component: Component) -> bool:
    """Mirror the v0.6 exporter's reconstruction rule: the
    PURL is constructible from ecosystem + name + version
    for ``npm`` and ``pypi`` when the package name is
    non-empty. Other ecosystems are not constructible by the
    v0.6 exporter; the evidence endpoint must agree.
    """
    if not component.package_name:
        return False
    return component.ecosystem in {"npm", "pypi"}


def _build_manifest_block(manifest: Manifest | None) -> dict[str, Any]:
    """Project the manifest into a bounded evidence block.

    When no manifest is associated (which is unusual; the
    database enforces a non-null ``manifest_id`` foreign key),
    the block reports ``available: false`` so the consumer
    never reads the absent path as "empty path".
    """
    if manifest is None:
        return {
            "available": False,
            "id": None,
            "path": None,
            "manifest_type": None,
            "ecosystem": None,
            "parse_status": None,
            "parse_warning_count": None,
        }
    return {
        "available": True,
        "id": manifest.id,
        "path": manifest.path,
        "manifest_type": manifest.manifest_type,
        "ecosystem": manifest.ecosystem,
        "parse_status": manifest.parse_status.value
        if isinstance(manifest.parse_status, ManifestParseStatus)
        else str(manifest.parse_status),
        "parse_warning_count": int(manifest.parse_warning_count or 0),
    }


def _build_licence_block(licence_records: Iterable[Finding]) -> dict[str, Any]:
    """Project every licence-category finding into the
    documented evidence block.

    The contract:

    - ``available`` is True only when at least one licence
      finding with at least one observed value is present.
    - Each ``observations`` row carries the observed value
      verbatim, the SPDX classification (the v0.6 library
      call), the local / provider provenance, and the
      redacted source label.
    - A missing observation block is rendered as
      ``available: false`` with an explicit ``reason``;
      ``no_licence_assertion`` is never rendered as ``"none"``
      or empty string.
    """
    observations: list[dict[str, Any]] = []
    sources: set[str] = set()
    for record in licence_records:
        values, source = _parse_licence_evidence_json(record.evidence_json)
        if source:
            sources.add(source)
        for value in values:
            observations.append(
                {
                    "value": value,
                    "classification": _classify_licence_value(value),
                    "provenance": _licence_provenance(source),
                    "source": source,
                    "finding_id": record.id,
                    "rule_id": record.rule_id,
                }
            )
    if not observations:
        return {
            "available": False,
            "reason": "no_persisted_licence_evidence",
            "observations": [],
            "sources": [],
            # The library-driven SPDX classification is
            # always available; the consumer can still ask
            # "what is in the SPDX list?" through the
            # library, but the evidence response does not
            # fabricate a "no licence" verdict. The
            # omission is the answer.
        }
    return {
        "available": True,
        "reason": None,
        "observations": observations,
        "sources": sorted(sources),
    }


def _licence_provenance(source: str | None) -> str:
    """Map a licence observation source string to the
    evidence block's provenance label.

    The mapping is the smallest vocabulary that distinguishes
    ``local`` (rule-engine evidence) from
    ``provider`` (anything else). Unknown / missing sources
    are reported as ``unknown`` so the consumer can render
    the honest "we cannot say" state."""
    if source is None:
        return "unknown"
    if source == "rule_engine":
        return "local"
    return "provider"


def _build_provider_block(
    *,
    provider_observations: Iterable[ProviderObservation],
    advisory_links: Iterable[ComponentAdvisory],
    advisories: dict[int, Advisory],
) -> dict[str, Any]:
    """Project every per-component provider observation and
    every component-advisory row into the evidence block.

    The contract:

    - ``available`` is True only when at least one
      observation or one advisory link is present.
    - Each ``observations`` row carries the provider name,
      status, operation, cache status, http status, fetched
      timestamp, error summary (redacted), and a small
      evidence summary. The endpoint never reveals internal
      paths or the full evidence JSON; only bounded
      top-level keys.
    - Each ``advisories`` row carries the linked advisory
      id, the canonical / source ids, the severity label
      and score (both verbatim from the provider), the
      fixed versions list, the aliases, and the
      provider_provenance. The OSV confidence field is
      always ``None`` because the upstream provider does
      not supply a confidence value; the v0.4 honesty rule
      is preserved here.
    """
    observations: list[dict[str, Any]] = []
    any_provider_queried = False
    for obs in provider_observations:
        any_provider_queried = any_provider_queried or (obs.status != ProviderStatus.NOT_REQUESTED)
        observations.append(_project_provider_observation(obs))
    advisory_rows: list[dict[str, Any]] = []
    for link in advisory_links:
        advisory = advisories.get(link.advisory_id)
        if advisory is None:
            # The link points at an advisory that is no
            # longer in the database. The bounded
            # representation still carries the link id and
            # severity source; the missing advisory is
            # surfaced explicitly.
            advisory_rows.append(
                {
                    "advisory_id": link.advisory_id,
                    "available": False,
                    "reason": "advisory_row_missing",
                    "canonical_id": None,
                    "source_advisory_id": None,
                    "source": None,
                    "severity_label": link.severity_label,
                    "severity_score": link.severity_score,
                    "severity_source": link.severity_source,
                    "fixed_versions": _parse_fixed_versions(link.fixed_versions_json),
                    "aliases": _parse_evidence_aliases(link.evidence_json),
                    "confidence": None,
                    "provider_provenance": link.severity_source,
                    "affected": bool(link.affected),
                }
            )
            continue
        advisory_rows.append(
            {
                "advisory_id": advisory.id,
                "available": True,
                "reason": None,
                "canonical_id": advisory.canonical_id,
                "source_advisory_id": advisory.source_advisory_id,
                "source": advisory.source,
                "severity_label": link.severity_label,
                "severity_score": link.severity_score,
                "severity_source": link.severity_source,
                "fixed_versions": _parse_fixed_versions(link.fixed_versions_json),
                "aliases": _parse_evidence_aliases(link.evidence_json),
                # OSV does not supply a confidence value;
                # the response keeps the honest null.
                "confidence": None,
                "provider_provenance": advisory.source,
                "affected": bool(link.affected),
            }
        )
    available = bool(observations) or bool(advisory_rows)
    return {
        "available": available,
        "any_provider_queried": any_provider_queried,
        "observations": observations,
        "advisories": advisory_rows,
    }


def _project_provider_observation(obs: ProviderObservation) -> dict[str, Any]:
    """Project one ``ProviderObservation`` row into the
    bounded evidence representation. The redacted
    ``error_summary`` is included when present; the structured
    ``evidence_json`` is summarised to a small list of keys
    (no full payload, no internal paths)."""
    evidence_keys: list[str] = []
    if obs.evidence_json:
        try:
            envelope = json.loads(obs.evidence_json)
        except (ValueError, TypeError):
            envelope = None
        if isinstance(envelope, dict):
            evidence_keys = sorted(str(key) for key in envelope if isinstance(key, str))
    return {
        "id": obs.id,
        "provider": obs.provider,
        "operation": obs.operation,
        "status": obs.status.value if hasattr(obs.status, "value") else str(obs.status),
        "cache_status": obs.cache_status,
        "http_status": obs.http_status,
        "records_returned": int(obs.records_returned or 0),
        "requested_at": obs.requested_at.isoformat() if obs.requested_at else None,
        "completed_at": obs.completed_at.isoformat() if obs.completed_at else None,
        "error_code": obs.error_code,
        "error_summary": obs.error_summary,
        "evidence_keys": evidence_keys,
    }


def _parse_fixed_versions(raw: str | None) -> list[str]:
    """Parse the bounded ``fixed_versions_json`` column into
    a list of strings. The column is either empty, a single
    version string, or a JSON array; the evidence endpoint
    normalises all three."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return [raw]
    if isinstance(parsed, list):
        return [str(item) for item in parsed if item is not None]
    return [str(parsed)]


def _parse_evidence_aliases(raw: str | None) -> list[str]:
    """Read the bounded ``aliases`` list from the
    ``evidence_json`` column when present. The endpoint
    never assumes aliases are present; the list is
    empty when the column is missing or malformed."""
    if not raw:
        return []
    try:
        envelope = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(envelope, dict):
        return []
    aliases = envelope.get("aliases")
    if not isinstance(aliases, list):
        return []
    return [str(item) for item in aliases if item is not None]


def _build_dependency_block(
    *,
    component: Component,
    manifests: list[Manifest],
    incoming_edges: Iterable[DependencyEdge],
    outgoing_edges: Iterable[DependencyEdge],
) -> dict[str, Any]:
    """Project the persisted ``DependencyEdge`` rows for the
    component into a bounded evidence block.

    The v0.6 evidence-honesty contract never infers edges
    from manifest co-occurrence; only persisted edges
    count. The block also reports the v0.6 graph coverage
    label so the consumer can render the honest "partial"
    state for a scan that has manifests but no positive
    proof of full transitive closure.
    """
    incoming = [
        _project_dependency_edge(edge, component, direction="incoming") for edge in incoming_edges
    ]
    outgoing = [
        _project_dependency_edge(edge, component, direction="outgoing") for edge in outgoing_edges
    ]
    coverage = _dependency_graph_coverage(manifests, list(incoming_edges) + list(outgoing_edges))
    return {
        "graph_coverage": coverage,
        "incoming": incoming,
        "outgoing": outgoing,
        # The block is explicit when the graph is empty:
        # "no edges observed" is **not** the same as "no
        # dependencies". The evidence-honesty rule says
        # unknown is unknown.
        "no_edges_observed": (not incoming) and (not outgoing),
    }


def _project_dependency_edge(
    edge: DependencyEdge,
    component: Component,
    *,
    direction: str,
) -> dict[str, Any]:
    """Project one persisted ``DependencyEdge`` row.

    The block carries the local-id, the foreign-id, the
    direction label, the relationship, and the depth. The
    endpoint never resolves the parent / child component
    to its package name; the consumer can resolve the
    id through the components endpoint when it needs the
    human label. The local-id is sufficient for the
    evidence surface.
    """
    other_id = edge.parent_component_id if direction == "incoming" else edge.child_component_id
    return {
        "edge_id": edge.id,
        "component_id": component.id,
        "other_component_id": other_id,
        "direction": direction,
        "relationship": edge.relationship,
        "depth": int(edge.depth),
    }


def _build_export_implications(
    *,
    component: Component,
    outgoing_edges: list[dict[str, Any]],
    dependency_block: dict[str, Any],
) -> dict[str, Any]:
    """Return the small block of CycloneDX 1.7 export
    implications the v0.8 consumer renders.

    The block is the **observed** implication, not a
    prediction: every boolean is the answer to a concrete
    ``if ... then ...`` rule that the v0.6 exporter
    implements. The same rule runs in the BOM builder;
    the evidence endpoint reports the result without
    generating the BOM.
    """
    version_omitted = component.version is None
    persisted_purl = component.package_url
    purl_emitted = False
    if persisted_purl is not None and _is_purl_well_formed(persisted_purl):
        # The persisted PURL is well-formed; the v0.6
        # exporter uses it as-is.
        purl_emitted = True
    elif _is_purl_constructible(component):
        # The persisted PURL is missing or malformed; the
        # v0.6 exporter reconstructs a PURL from
        # ecosystem + name + version for npm / pypi.
        # The evidence block must agree with the
        # exporter on this rule.
        purl_emitted = True
    # The v0.6 exporter emits ``Dependency`` entries only
    # for components that have at least one persisted
    # outgoing edge. The evidence block mirrors that rule.
    dependency_relationships_emitted = len(outgoing_edges) > 0
    appears_in_cyclonedx_17 = True  # the BOM always lists every observed component
    return {
        "appears_in_cyclonedx_17": appears_in_cyclonedx_17,
        "version_omitted": version_omitted,
        "purl_emitted": purl_emitted,
        "dependency_relationships_emitted": dependency_relationships_emitted,
        "graph_coverage": dependency_block["graph_coverage"],
    }


# ---------------------------------------------------------------------
# Service class (session lifecycle wrapper)
# ---------------------------------------------------------------------


class ComponentEvidenceService:
    """Session-lifecycle wrapper around ``build_component_evidence``.

    The service is the read-only entry point the API layer
    calls. It opens a session, fetches the persisted evidence
    in deterministic order, calls the free function, and
    closes the session. The service never mutates state, never
    calls a provider, and never executes analyzed code.
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def fetch(self, *, scan_run_id: int, component_id: int) -> dict[str, Any] | None:
        """Return the v0.8 component evidence for ``component_id``.

        Returns ``None`` only when the component does not
        exist or does not belong to ``scan_run_id`` (the API
        layer maps that to a 404). The function is read-only.
        """
        session = self._session_factory()
        try:
            return self._fetch_in_session(
                session,
                scan_run_id=scan_run_id,
                component_id=component_id,
            )
        finally:
            session.close()

    @staticmethod
    def _fetch_in_session(
        session: Session,
        *,
        scan_run_id: int,
        component_id: int,
    ) -> dict[str, Any] | None:
        scan = session.get(ScanRun, scan_run_id)
        if scan is None:
            return None
        component = session.get(Component, component_id)
        if component is None or component.scan_run_id != scan_run_id:
            return None
        # The component → manifest association is a foreign
        # key, so ``manifest`` is non-null in the persisted
        # schema; the helper tolerates ``None`` for tests.
        manifest = (
            session.get(Manifest, component.manifest_id)
            if component.manifest_id is not None
            else None
        )
        licence_records = (
            session.query(Finding)
            .filter(
                Finding.scan_run_id == scan_run_id,
                Finding.category == FindingCategory.LICENCE,
            )
            .order_by(Finding.id.asc())
            .all()
        )
        provider_observations = (
            session.query(ProviderObservation)
            .filter(
                ProviderObservation.scan_run_id == scan_run_id,
                ProviderObservation.component_id == component_id,
            )
            .order_by(ProviderObservation.id.asc())
            .limit(PROVIDER_OBSERVATION_LIMIT)
            .all()
        )
        advisory_links = (
            session.query(ComponentAdvisory)
            .filter(
                ComponentAdvisory.scan_run_id == scan_run_id,
                ComponentAdvisory.component_id == component_id,
            )
            .order_by(ComponentAdvisory.id.asc())
            .limit(ADVISORY_LIMIT)
            .all()
        )
        advisory_ids = {link.advisory_id for link in advisory_links}
        advisories: dict[int, Advisory] = {}
        if advisory_ids:
            for row in session.query(Advisory).filter(Advisory.id.in_(advisory_ids)).all():
                advisories[row.id] = row
        incoming_edges = (
            session.query(DependencyEdge)
            .filter(
                DependencyEdge.scan_run_id == scan_run_id,
                DependencyEdge.child_component_id == component_id,
            )
            .order_by(DependencyEdge.id.asc())
            .limit(DEPENDENCY_EDGE_LIMIT)
            .all()
        )
        outgoing_edges = (
            session.query(DependencyEdge)
            .filter(
                DependencyEdge.scan_run_id == scan_run_id,
                DependencyEdge.parent_component_id == component_id,
            )
            .order_by(DependencyEdge.id.asc())
            .limit(DEPENDENCY_EDGE_LIMIT)
            .all()
        )
        # We snapshot the licence / observation / advisory /
        # edge rows into plain Python data so the
        # ``build_component_evidence`` call is a pure
        # function over detached state. The session can
        # close safely afterwards.
        licence_payload = [
            {
                "id": r.id,
                "rule_id": r.rule_id,
                "stable_key": r.stable_key,
                "evidence_json": r.evidence_json,
            }
            for r in licence_records
        ]
        provider_payload = [
            {
                "id": o.id,
                "provider": o.provider,
                "operation": o.operation,
                "status": o.status,
                "cache_status": o.cache_status,
                "http_status": o.http_status,
                "records_returned": o.records_returned,
                "requested_at": o.requested_at,
                "completed_at": o.completed_at,
                "error_code": o.error_code,
                "error_summary": o.error_summary,
                "evidence_json": o.evidence_json,
            }
            for o in provider_observations
        ]
        # Convert the snapshot dicts back into the SQLAlchemy
        # objects the free function expects. The free
        # function reads only a small set of attributes and
        # never triggers a session load, so detached
        # snapshots are safe.
        licence_snapshots = [_LicenceSnapshot(**row) for row in licence_payload]
        provider_snapshots = [_ProviderSnapshot(**row) for row in provider_payload]
        return build_component_evidence(
            scan=scan,
            component=component,
            manifest=manifest,
            licence_records=licence_snapshots,
            provider_observations=provider_snapshots,
            advisory_links=advisory_links,
            advisories=advisories,
            incoming_edges=incoming_edges,
            outgoing_edges=outgoing_edges,
        )


# ---------------------------------------------------------------------
# Lightweight detached snapshots for the free function
# ---------------------------------------------------------------------


class _LicenceSnapshot:
    __slots__ = ("evidence_json", "id", "rule_id", "stable_key")

    def __init__(
        self, *, id: int, rule_id: str, stable_key: str, evidence_json: str | None
    ) -> None:
        self.id = id
        self.rule_id = rule_id
        self.stable_key = stable_key
        self.evidence_json = evidence_json


class _ProviderSnapshot:
    __slots__ = (
        "cache_status",
        "completed_at",
        "error_code",
        "error_summary",
        "evidence_json",
        "http_status",
        "id",
        "operation",
        "provider",
        "records_returned",
        "requested_at",
        "status",
    )

    def __init__(
        self,
        *,
        id: int,
        provider: str,
        operation: str,
        status: ProviderStatus,
        cache_status: str | None,
        http_status: int | None,
        records_returned: int,
        requested_at,
        completed_at,
        error_code: str | None,
        error_summary: str | None,
        evidence_json: str | None,
    ) -> None:
        self.id = id
        self.provider = provider
        self.operation = operation
        self.status = status
        self.cache_status = cache_status
        self.http_status = http_status
        self.records_returned = records_returned
        self.requested_at = requested_at
        self.completed_at = completed_at
        self.error_code = error_code
        self.error_summary = error_summary
        self.evidence_json = evidence_json


__all__ = [
    "ADVISORY_LIMIT",
    "COMPONENT_EVIDENCE_OMISSIONS",
    "DEPENDENCY_EDGE_LIMIT",
    "PROVIDER_OBSERVATION_LIMIT",
    "ComponentEvidenceService",
    "build_component_evidence",
]
