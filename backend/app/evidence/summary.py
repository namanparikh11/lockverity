"""v0.9 evidence-aware search and filtering.

The summary module is the single authoritative backend rule
for ``GET /api/v1/scans/{scan_id}/components/evidence-summary``.
It is read-only, deterministic, and never calls a provider,
never downloads a repository, never executes analyzed code,
and never writes to the database.

The module reuses the v0.8 evidence builders for:

- PURL well-formedness (``_is_purl_well_formed``);
- PURL constructibility (``_is_purl_constructible``);
- licence observation presence (existing
  ``licence_by_component_id`` projection);
- provider observation presence (existing
  ``provider_observations`` per-component filter);
- dependency edges presence (existing
  ``incoming_edges`` / ``outgoing_edges`` projections);
- CycloneDX 1.7 export implications (the same rules the
  v0.6 exporter implements).

The summary endpoint therefore cannot disagree with the
v0.8 detail endpoint or the v0.6 / v0.7 CycloneDX export
endpoint. The filter labels are evidence-honest:

- ``missing_evidence`` for absence is rendered as
  ``not_persisted`` / ``none_observed``; the consumer
  never reads absence as a clean verdict.
- The dependency-edge filter is ``present`` /
  ``none_observed``; the wording "no dependencies" is
  not used.
- The PURL filter is ``persisted`` / ``constructible`` /
  ``omitted``; the consumer can distinguish a deliberately
  omitted PURL from a reconstructed PURL from a missing
  persisted PURL.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.evidence import _is_purl_constructible, _is_purl_well_formed
from app.models.component import Component
from app.models.dependency_edge import DependencyEdge
from app.models.finding import Finding, FindingCategory
from app.models.manifest import Manifest
from app.models.provider_observation import ProviderObservation
from app.models.scan_run import ScanRun

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Limits / contract
# ---------------------------------------------------------------------

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


# ---------------------------------------------------------------------
# Filter value vocabulary
# ---------------------------------------------------------------------

DIRECT_VALUES = ("all", "yes", "no")
PRESENT_VALUES = ("all", "present", "missing")
PURL_VALUES = ("all", "persisted", "constructible", "omitted")
EDGE_VALUES = ("all", "present", "none_observed")
BOOL_VALUES = ("all", "yes", "no")
SORT_VALUES = (
    "package_name",
    "ecosystem",
    "version_missing_first",
    "licence_missing_first",
    "provider_missing_first",
    "dependency_edges_missing_first",
)


# ---------------------------------------------------------------------
# Filter parsing helpers
# ---------------------------------------------------------------------


def _normalise_filter(value: str | None, allowed: tuple[str, ...], default: str = "all") -> str:
    """Return ``value`` when it is in ``allowed``; otherwise ``default``.

    A ``None`` value is also mapped to ``default``. The
    function never raises; an invalid filter value is the
    consumer's choice and is treated as "no filter".
    """
    if value is None:
        return default
    if value in allowed:
        return value
    return default


def _build_evidence_flags(
    component: Component,
    licence_observed: bool,
    provider_observed: bool,
    outgoing_edge_count: int,
) -> dict[str, Any]:
    """Return the per-component evidence flags the summary exposes.

    The flags are derived from the same rules the v0.6
    CycloneDX 1.7 exporter implements, so the summary
    cannot disagree with the actual export. The PURL state
    vocabulary is ``persisted`` (the persisted PURL is
    well-formed), ``constructible`` (the persisted PURL is
    missing or malformed but the v0.6 reconstruction rule
    would build one), or ``omitted`` (no persisted PURL and
    the reconstruction rule does not apply).
    """
    persisted_purl = component.package_url
    if persisted_purl is not None and _is_purl_well_formed(persisted_purl):
        purl_state = "persisted"
    elif _is_purl_constructible(component):
        purl_state = "constructible"
    else:
        purl_state = "omitted"
    version_present = component.version is not None
    edges_observed = outgoing_edge_count > 0
    # The CycloneDX 1.7 export implications follow the
    # same rules the v0.6 exporter and the v0.8 evidence
    # module use.
    appears_in_cyclonedx_17 = True
    version_omitted_from_cyclonedx_17 = not version_present
    dependency_relationships_emitted = edges_observed
    return {
        "version_present": version_present,
        "licence_observed": licence_observed,
        "provider_observed": provider_observed,
        "purl_state": purl_state,
        "edges_observed": edges_observed,
        "appears_in_cyclonedx_17": appears_in_cyclonedx_17,
        "version_omitted_from_cyclonedx_17": version_omitted_from_cyclonedx_17,
        "dependency_relationships_emitted_in_cyclonedx_17": (dependency_relationships_emitted),
    }


# ---------------------------------------------------------------------
# Sort keys
# ---------------------------------------------------------------------


def _sort_key(sort: str) -> tuple[Any, ...]:
    """Return a stable key for the supported sort values.

    The function returns a tuple so secondary ordering
    (component id) keeps the result deterministic when the
    primary key ties.
    """
    return (sort, "id")


# ---------------------------------------------------------------------
# Free function
# ---------------------------------------------------------------------


def build_component_evidence_summary(
    *,
    scan: ScanRun,
    components: list[Component],
    manifests: list[Manifest],
    outgoing_edges: dict[int, int],
    licence_observed_by_component: dict[int, bool],
    provider_observed_by_component: dict[int, bool],
    search: str | None = None,
    ecosystem: str | None = None,
    direct: str = "all",
    version: str = "all",
    licence_evidence: str = "all",
    provider_evidence: str = "all",
    purl: str = "all",
    dependency_edges: str = "all",
    cyclonedx_appears: str = "all",
    cyclonedx_version_omitted: str = "all",
    cyclonedx_relationships_emitted: str = "all",
    sort: str = "package_name",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """Return the v0.9 evidence-aware component summary for ``scan``.

    The function is a pure projection over already-fetched
    persisted state. It never mutates state, never calls a
    provider, never writes to the database, and never infers
    missing evidence. The function is deterministic for the
    same persisted evidence: the response depends only on
    the database rows, the filter values, and the page
    indices.

    The shape is the documented v0.9 contract:

    - ``items`` — the filtered + sorted + paginated rows;
    - ``pagination`` — page metadata;
    - ``facets`` — aggregate counts the consumer renders
      as a side panel (the totals are over the full
      filtered set, not the paginated subset);
    - ``omissions`` — the bounded evidence-honesty rules.
    """
    direct = _normalise_filter(direct, DIRECT_VALUES)
    version = _normalise_filter(version, PRESENT_VALUES)
    licence_evidence = _normalise_filter(licence_evidence, PRESENT_VALUES)
    provider_evidence = _normalise_filter(provider_evidence, PRESENT_VALUES)
    purl = _normalise_filter(purl, PURL_VALUES)
    dependency_edges = _normalise_filter(dependency_edges, EDGE_VALUES)
    cyclonedx_appears = _normalise_filter(cyclonedx_appears, BOOL_VALUES)
    cyclonedx_version_omitted = _normalise_filter(cyclonedx_version_omitted, BOOL_VALUES)
    cyclonedx_relationships_emitted = _normalise_filter(
        cyclonedx_relationships_emitted, BOOL_VALUES
    )
    sort = _normalise_filter(sort, SORT_VALUES, default="package_name")
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))

    search_pattern = f"%{search.lower()}%" if search else None
    ecosystem_filter = ecosystem if ecosystem else None

    # Pre-compute evidence flags for every component once.
    # The map is the single source of truth the filter,
    # sort, and facet pipelines all consume.
    rows: list[dict[str, Any]] = []
    for component in components:
        flags = _build_evidence_flags(
            component=component,
            licence_observed=bool(licence_observed_by_component.get(component.id, False)),
            provider_observed=bool(provider_observed_by_component.get(component.id, False)),
            outgoing_edge_count=int(outgoing_edges.get(component.id, 0)),
        )
        rows.append(
            {
                "component": component,
                "flags": flags,
            }
        )

    # Apply filters.
    def _keep(row: dict[str, Any]) -> bool:
        c = row["component"]
        f = row["flags"]
        if (
            search_pattern is not None
            and search_pattern.replace("%", "").lower() not in (c.package_name or "").lower()
        ):
            # Search matches on the lower-cased package
            # name. The persisted column is preserved
            # verbatim in the response.
            return False
        if ecosystem_filter is not None and c.ecosystem != ecosystem_filter:
            return False
        if direct == "yes" and not c.direct:
            return False
        if direct == "no" and c.direct:
            return False
        if version == "present" and not f["version_present"]:
            return False
        if version == "missing" and f["version_present"]:
            return False
        if licence_evidence == "present" and not f["licence_observed"]:
            return False
        if licence_evidence == "missing" and f["licence_observed"]:
            return False
        if provider_evidence == "present" and not f["provider_observed"]:
            return False
        if provider_evidence == "missing" and f["provider_observed"]:
            return False
        if purl != "all" and f["purl_state"] != purl:
            return False
        if dependency_edges == "present" and not f["edges_observed"]:
            return False
        if dependency_edges == "none_observed" and f["edges_observed"]:
            return False
        if cyclonedx_appears == "yes" and not f["appears_in_cyclonedx_17"]:
            return False
        if cyclonedx_appears == "no" and f["appears_in_cyclonedx_17"]:
            return False
        if cyclonedx_version_omitted == "yes" and not f["version_omitted_from_cyclonedx_17"]:
            return False
        if cyclonedx_version_omitted == "no" and f["version_omitted_from_cyclonedx_17"]:
            return False
        if (
            cyclonedx_relationships_emitted == "yes"
            and not f["dependency_relationships_emitted_in_cyclonedx_17"]
        ):
            return False
        return not (
            cyclonedx_relationships_emitted == "no"
            and f["dependency_relationships_emitted_in_cyclonedx_17"]
        )

    filtered = [r for r in rows if _keep(r)]

    # Compute facet counts over the full filtered set, not
    # the paginated subset. The consumer renders the facets
    # alongside the filter row so the user knows how many
    # rows each filter value would surface.
    facets = _compute_facets(filtered)

    # Apply sort.
    _apply_sort(filtered, sort)

    # Paginate.
    total = len(filtered)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = filtered[start:end]

    items = [_project_item(r, scan) for r in page_rows]
    return {
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
        "facets": facets,
        "omissions": _summary_omissions(),
    }


def _project_item(row: dict[str, Any], scan: ScanRun) -> dict[str, Any]:
    """Project a single filtered + sorted row into the item shape."""
    c = row["component"]
    f = row["flags"]
    return {
        "id": c.id,
        "scan_id": scan.id,
        "manifest_id": c.manifest_id,
        "package_name": c.package_name,
        "ecosystem": c.ecosystem,
        "version": c.version,
        "version_source": c.version_source.value if c.version_source is not None else None,
        "direct": c.direct,
        "package_url": c.package_url,
        "evidence": f,
    }


def _apply_sort(rows: list[dict[str, Any]], sort: str) -> None:
    """Sort the rows in place using the documented sort key.

    Every sort uses the persisted values verbatim; the
    function never invents a sort key. The secondary
    key (component id) keeps the result deterministic when
    the primary key ties.
    """
    if sort == "package_name":
        rows.sort(key=lambda r: ((r["component"].package_name or "").lower(), r["component"].id))
        return
    if sort == "ecosystem":
        rows.sort(
            key=lambda r: (
                (r["component"].ecosystem or ""),
                (r["component"].package_name or "").lower(),
                r["component"].id,
            )
        )
        return
    if sort == "version_missing_first":
        rows.sort(
            key=lambda r: (
                0 if not r["flags"]["version_present"] else 1,
                (r["component"].package_name or "").lower(),
                r["component"].id,
            )
        )
        return
    if sort == "licence_missing_first":
        rows.sort(
            key=lambda r: (
                0 if not r["flags"]["licence_observed"] else 1,
                (r["component"].package_name or "").lower(),
                r["component"].id,
            )
        )
        return
    if sort == "provider_missing_first":
        rows.sort(
            key=lambda r: (
                0 if not r["flags"]["provider_observed"] else 1,
                (r["component"].package_name or "").lower(),
                r["component"].id,
            )
        )
        return
    if sort == "dependency_edges_missing_first":
        rows.sort(
            key=lambda r: (
                0 if not r["flags"]["edges_observed"] else 1,
                (r["component"].package_name or "").lower(),
                r["component"].id,
            )
        )
        return
    # Fallback: deterministic package name order.
    rows.sort(key=lambda r: ((r["component"].package_name or "").lower(), r["component"].id))


def _compute_facets(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the aggregate counts the consumer renders.

    The facet vocabulary is the same as the per-row
    evidence flag vocabulary. The ``ecosystems`` facet
    is a small dict that the consumer renders as
    ``{ecosystem: count}`` pairs; the other facets are
    flat counts the consumer can render as a single
    number.
    """
    ecosystem_counter: Counter[str] = Counter()
    purl_persisted = 0
    purl_constructible = 0
    purl_omitted = 0
    missing_version = 0
    missing_licence = 0
    missing_provider = 0
    edges_observed = 0
    edges_none_observed = 0
    direct_yes = 0
    direct_no = 0
    cyclonedx_version_omitted = 0
    for row in rows:
        c = row["component"]
        f = row["flags"]
        if c.ecosystem:
            ecosystem_counter[c.ecosystem] += 1
        if f["purl_state"] == "persisted":
            purl_persisted += 1
        elif f["purl_state"] == "constructible":
            purl_constructible += 1
        else:
            purl_omitted += 1
        if not f["version_present"]:
            missing_version += 1
        if not f["licence_observed"]:
            missing_licence += 1
        if not f["provider_observed"]:
            missing_provider += 1
        if f["edges_observed"]:
            edges_observed += 1
        else:
            edges_none_observed += 1
        if c.direct:
            direct_yes += 1
        else:
            direct_no += 1
        if f["version_omitted_from_cyclonedx_17"]:
            cyclonedx_version_omitted += 1
    return {
        "ecosystems": dict(sorted(ecosystem_counter.items())),
        "missing_version": missing_version,
        "missing_licence_evidence": missing_licence,
        "missing_provider_evidence": missing_provider,
        "purl_persisted": purl_persisted,
        "purl_constructible": purl_constructible,
        "purl_omitted": purl_omitted,
        "edges_observed": edges_observed,
        "edges_none_observed": edges_none_observed,
        "direct_yes": direct_yes,
        "direct_no": direct_no,
        "cyclonedx_version_omitted": cyclonedx_version_omitted,
    }


def _summary_omissions() -> list[str]:
    """Return the documented evidence-honesty markers for the summary."""
    return [
        "no_clean_verdict",
        "no_security_verdict",
        "no_complete_dependency_graph_claim",
        "no_remediation_claim",
        "no_repository_code_execution",
        "no_inferred_dependency_edges",
        "no_fabricated_evidence_absence",
    ]


# ---------------------------------------------------------------------
# Service class (session lifecycle wrapper)
# ---------------------------------------------------------------------


class ComponentEvidenceSummaryService:
    """Session-lifecycle wrapper around ``build_component_evidence_summary``.

    The service is the read-only entry point the API layer
    calls. It opens a session, fetches the persisted evidence
    in deterministic order, calls the free function, and
    closes the session. The service never mutates state,
    never calls a provider, and never executes analyzed
    code.
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def fetch(
        self,
        *,
        scan_run_id: int,
        search: str | None = None,
        ecosystem: str | None = None,
        direct: str = "all",
        version: str = "all",
        licence_evidence: str = "all",
        provider_evidence: str = "all",
        purl: str = "all",
        dependency_edges: str = "all",
        cyclonedx_appears: str = "all",
        cyclonedx_version_omitted: str = "all",
        cyclonedx_relationships_emitted: str = "all",
        sort: str = "package_name",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any] | None:
        """Return the v0.9 evidence summary for ``scan_run_id``.

        Returns ``None`` only when the scan id does not
        exist (the API layer maps that to a 404). For every
        other scan state, the method returns a summary dict
        with the documented shape.
        """
        session = self._session_factory()
        try:
            return self._fetch_in_session(
                session,
                scan_run_id=scan_run_id,
                search=search,
                ecosystem=ecosystem,
                direct=direct,
                version=version,
                licence_evidence=licence_evidence,
                provider_evidence=provider_evidence,
                purl=purl,
                dependency_edges=dependency_edges,
                cyclonedx_appears=cyclonedx_appears,
                cyclonedx_version_omitted=cyclonedx_version_omitted,
                cyclonedx_relationships_emitted=cyclonedx_relationships_emitted,
                sort=sort,
                page=page,
                page_size=page_size,
            )
        finally:
            session.close()

    @staticmethod
    def _fetch_in_session(
        session: Session,
        *,
        scan_run_id: int,
        search: str | None,
        ecosystem: str | None,
        direct: str,
        version: str,
        licence_evidence: str,
        provider_evidence: str,
        purl: str,
        dependency_edges: str,
        cyclonedx_appears: str,
        cyclonedx_version_omitted: str,
        cyclonedx_relationships_emitted: str,
        sort: str,
        page: int,
        page_size: int,
    ) -> dict[str, Any] | None:
        scan = session.get(ScanRun, scan_run_id)
        if scan is None:
            return None
        components = (
            session.query(Component)
            .filter(Component.scan_run_id == scan_run_id)
            .order_by(Component.id.asc())
            .all()
        )
        manifests = (
            session.query(Manifest)
            .filter(Manifest.scan_run_id == scan_run_id)
            .order_by(Manifest.id.asc())
            .all()
        )
        outgoing_rows = (
            session.query(DependencyEdge).filter(DependencyEdge.scan_run_id == scan_run_id).all()
        )
        outgoing_edge_count: dict[int, int] = {}
        for edge in outgoing_rows:
            outgoing_edge_count[edge.parent_component_id] = (
                outgoing_edge_count.get(edge.parent_component_id, 0) + 1
            )
        # A component has persisted licence evidence when
        # at least one LICENCE-category finding references
        # it through the evidence envelope's
        # ``component_id`` key. The check is the same one
        # the v0.8 detail endpoint uses.
        licence_rows = (
            session.query(Finding)
            .filter(
                Finding.scan_run_id == scan_run_id,
                Finding.category == FindingCategory.LICENCE,
            )
            .all()
        )
        licence_observed_by_component: dict[int, bool] = {}
        for finding in licence_rows:
            try:
                import json as _json

                envelope = _json.loads(finding.evidence_json or "{}")
            except (ValueError, TypeError):
                continue
            if not isinstance(envelope, dict):
                continue
            payload = envelope.get("evidence") or {}
            if not isinstance(payload, dict):
                continue
            component_id = payload.get("component_id")
            if isinstance(component_id, int):
                values = payload.get("licences")
                if isinstance(values, list) and any(isinstance(v, str) and v for v in values):
                    licence_observed_by_component[component_id] = True
        # A component has persisted provider evidence when
        # at least one ``ProviderObservation`` row is
        # bound to it for the scan.
        provider_rows = (
            session.query(ProviderObservation)
            .filter(
                ProviderObservation.scan_run_id == scan_run_id,
                ProviderObservation.component_id.isnot(None),
            )
            .all()
        )
        provider_observed_by_component: dict[int, bool] = {}
        for obs in provider_rows:
            if obs.component_id is not None:
                provider_observed_by_component[obs.component_id] = True
        return build_component_evidence_summary(
            scan=scan,
            components=list(components),
            manifests=list(manifests),
            outgoing_edges=outgoing_edge_count,
            licence_observed_by_component=licence_observed_by_component,
            provider_observed_by_component=provider_observed_by_component,
            search=search,
            ecosystem=ecosystem,
            direct=direct,
            version=version,
            licence_evidence=licence_evidence,
            provider_evidence=provider_evidence,
            purl=purl,
            dependency_edges=dependency_edges,
            cyclonedx_appears=cyclonedx_appears,
            cyclonedx_version_omitted=cyclonedx_version_omitted,
            cyclonedx_relationships_emitted=cyclonedx_relationships_emitted,
            sort=sort,
            page=page,
            page_size=page_size,
        )


__all__ = [
    "BOOL_VALUES",
    "DEFAULT_PAGE_SIZE",
    "DIRECT_VALUES",
    "EDGE_VALUES",
    "MAX_PAGE_SIZE",
    "PRESENT_VALUES",
    "PURL_VALUES",
    "SORT_VALUES",
    "ComponentEvidenceSummaryService",
    "build_component_evidence_summary",
]
