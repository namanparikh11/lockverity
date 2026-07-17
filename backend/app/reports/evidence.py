"""v1.0 human-readable evidence report (implementation).

The module is the single source of truth for:

- the v1.0 JSON preview response shape
  (``build_evidence_report``);
- the v1.0 Markdown download output
  (``render_evidence_report_markdown``).

The two functions share the same backing data: the preview
response is the structured form, and the Markdown download
is the same data rendered as Markdown. The report never
calls a provider, never downloads a repository, never
executes analyzed code, and never writes to the database.

Evidence-honesty rules (the same ones v0.6 - v0.9 honour):

- Missing evidence is rendered as
  &ldquo;not persisted&rdquo; / &ldquo;none observed&rdquo; /
  &ldquo;no persisted edges&rdquo;; the report never
  converts absence into a clean verdict.
- PURL state is one of ``persisted`` /
  ``constructible`` / ``omitted``.
- Dependency graph coverage is rendered as
  ``partial`` / ``empty`` / ``not_applicable``;
  the report never claims the graph is
  &ldquo;complete&rdquo;.
- Provider coverage is rendered as
  ``ok`` / ``degraded`` / ``not_applicable``.
- The report carries an explicit
  ``omissions`` block of evidence-honesty markers so
  the consumer can render the &ldquo;what this report
  does not claim&rdquo; list verbatim.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app._version import __version__
from app.evidence import _is_purl_constructible, _is_purl_well_formed
from app.exporters.cyclonedx_v17 import (
    _dependency_graph_coverage,
    _inventory_coverage,
    _provider_coverage,
    evaluate_export_eligibility,
)
from app.models.component import Component
from app.models.dependency_edge import DependencyEdge
from app.models.finding import Finding, FindingCategory
from app.models.manifest import Manifest
from app.models.provider_observation import ProviderObservation
from app.models.repository import Repository
from app.models.scan_run import ScanRun

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Limits / contract
# ---------------------------------------------------------------------

# The report surfaces a bounded, deterministic shape. The
# component table is capped at ``COMPONENT_TABLE_LIMIT`` rows;
# when truncated, the report carries an explicit
# ``truncated`` block with the shown / total counts and the
# truncation reason. The Markdown output mirrors the same
# cap.
COMPONENT_TABLE_LIMIT = 100

# The documented v1.0 omissions list. Exposed as a module
# constant so the test suite can assert against it. Renaming
# any marker is a contract change.
EVIDENCE_REPORT_OMISSIONS: tuple[str, ...] = (
    "no_clean_verdict",
    "no_security_verdict",
    "no_certification",
    "no_compliance_pass_or_fail",
    "no_complete_dependency_graph_claim",
    "no_remediation_claim",
    "no_repository_code_execution",
    "missing_provider_confidence_kept_missing",
    "missing_licence_evidence_explicit",
    "no_fabricated_evidence_absence",
)


# Public constants the API layer uses to set the
# Content-Type and the Content-Disposition filename. The
# Markdown media type is the standard
# ``text/markdown`` with the ``charset=utf-8`` parameter
# (the v0.6/v0.7 pattern).
REPORT_FORMAT_KEY = "evidence_report"
REPORT_MEDIA_TYPE = "text/markdown; charset=utf-8"


# ---------------------------------------------------------------------
# Free function — structured preview
# ---------------------------------------------------------------------


def build_evidence_report(
    *,
    scan: ScanRun,
    repository: Repository | None,
    components: list[Component],
    manifests: list[Manifest],
    outgoing_edge_count_by_component: dict[int, int],
    incoming_edge_count_by_component: dict[int, int],
    licence_observed_by_component: dict[int, bool],
    provider_observed_by_component: dict[int, bool],
) -> dict[str, Any]:
    """Return the v1.0 evidence report preview for ``scan``.

    The function is a pure projection over already-fetched
    persisted state. It never mutates the database, never
    calls a provider, never downloads a repository, and
    never executes analyzed code. The function is
    deterministic for the same persisted evidence: every
    value derives from the database rows plus stable
    labels, never from the wall clock or any
    non-deterministic source.

    The shape is the documented v1.0 contract:

    - ``metadata`` — generator / version / format / scan
      identity;
    - ``scan`` — repository identity, source kind, scan
      status, evidence coverage;
    - ``summary`` — component / manifest / ecosystem
      counts, direct / transitive split, evidence
      per-row counts;
    - ``evidence_coverage`` — inventory / dependency
      graph / provider coverage;
    - ``evidence_gaps`` — missing version / licence /
      provider / dependency-edge counts;
    - ``components`` — bounded, deterministic component
      table;
    - ``export_relationship`` — CycloneDX 1.7 export
      availability and per-component export implications;
    - ``omissions`` — the documented evidence-honesty
      markers;
    - ``disclaimer`` — the bounded &ldquo;this is an
      evidence report, not a verdict&rdquo; note.
    """
    eligibility = evaluate_export_eligibility(
        scan=scan,
        component_count=len(components),
        manifest_count=len(manifests),
    )
    inventory_coverage = _inventory_coverage(
        component_count=len(components),
        scan_status=scan.status,
    )
    dependency_coverage = _dependency_graph_coverage(
        manifests=list(manifests),
        edges=[],
    )
    provider_coverage = _provider_coverage(eligibility)

    per_component = _project_components(
        components=components,
        outgoing_edge_count_by_component=outgoing_edge_count_by_component,
        incoming_edge_count_by_component=incoming_edge_count_by_component,
        licence_observed_by_component=licence_observed_by_component,
        provider_observed_by_component=provider_observed_by_component,
    )

    summary = _build_summary(
        per_component=per_component,
        manifests=manifests,
    )
    evidence_gaps = _build_evidence_gaps(per_component=per_component)
    component_table, truncated = _build_component_table(
        per_component=per_component,
    )
    export_relationship = _build_export_relationship(
        eligibility=eligibility,
        per_component=per_component,
        inventory_coverage=inventory_coverage,
        dependency_coverage=dependency_coverage,
        provider_coverage=provider_coverage,
    )

    return {
        "metadata": {
            "report_name": "Lockverity Evidence Report",
            "generator": "lockverity",
            "generator_version": __version__,
            "report_format": "markdown",
            "report_format_version": "1.0",
            "generated_at_utc": _stable_now_utc(scan),
            "scan_id": scan.id,
            "repository_id": scan.repository_id,
        },
        "scan": {
            "scan_id": scan.id,
            "repository_id": scan.repository_id,
            "repository_canonical_url": getattr(repository, "canonical_url", None)
            if repository is not None
            else None,
            "repository_source_type": _enum_value(getattr(repository, "source_type", None))
            if repository is not None
            else None,
            "repository_visibility": _enum_value(getattr(repository, "visibility", None))
            if repository is not None
            else None,
            "scan_status": scan.status.value,
            "scan_trigger_type": scan.trigger_type.value if scan.trigger_type is not None else None,
            "resolved_commit_sha": scan.resolved_commit_sha,
            "analyzer_version": scan.analyzer_version,
        },
        "summary": summary,
        "evidence_coverage": {
            "inventory_coverage": inventory_coverage,
            "dependency_graph_coverage": dependency_coverage,
            "provider_coverage": provider_coverage,
        },
        "evidence_gaps": evidence_gaps,
        "components": component_table,
        "truncated": truncated,
        "export_relationship": export_relationship,
        "omissions": list(EVIDENCE_REPORT_OMISSIONS),
        "disclaimer": (
            "This is an evidence report, not a security verdict, "
            "not a certification, and not a compliance pass-or-fail. "
            "Missing evidence is rendered as missing, not as 'no "
            "issues found'. Partial coverage is rendered as partial, "
            "not as 'complete'."
        ),
    }


# ---------------------------------------------------------------------
# Free function — Markdown rendering
# ---------------------------------------------------------------------


def render_evidence_report_markdown(preview: dict[str, Any]) -> str:
    """Render the v1.0 evidence report as Markdown.

    The function is pure: the same ``preview`` dict always
    produces the same Markdown string. The Markdown output
    is the only download surface in v1.0; the structured
    ``preview`` is the lazy summary the frontend shows
    before the user clicks &ldquo;Download Markdown&rdquo;.

    The Markdown is GitHub-flavoured (GFM): tables, code
    spans, and fenced code blocks. The output never uses
    HTML, never inlines images, and never includes any
    binary data.
    """
    meta = preview["metadata"]
    scan = preview["scan"]
    summary = preview["summary"]
    coverage = preview["evidence_coverage"]
    gaps = preview["evidence_gaps"]
    components = preview["components"]
    truncated = preview["truncated"]
    export_rel = preview["export_relationship"]
    omissions = preview["omissions"]
    disclaimer = preview["disclaimer"]

    lines: list[str] = []
    lines.append(f"# {meta['report_name']}")
    lines.append("")
    lines.append("> " + disclaimer)
    lines.append("")
    lines.append("## Report metadata")
    lines.append("")
    lines.append(f"- Generator: `{meta['generator']}`")
    lines.append(f"- Generator version: `{meta['generator_version']}`")
    lines.append(f"- Report format: `{meta['report_format']}`")
    lines.append(f"- Report format version: `{meta['report_format_version']}`")
    lines.append(f"- Generated at (UTC): `{meta['generated_at_utc']}`")
    lines.append(f"- Scan id: `{meta['scan_id']}`")
    lines.append(f"- Repository id: `{meta['repository_id']}`")
    lines.append("")

    lines.append("## Scan identity")
    lines.append("")
    lines.append(f"- Repository canonical URL: `{scan['repository_canonical_url'] or '—'}`")
    lines.append(f"- Repository source type: `{scan['repository_source_type'] or '—'}`")
    lines.append(f"- Repository visibility: `{scan['repository_visibility'] or '—'}`")
    lines.append(f"- Scan status: `{scan['scan_status']}`")
    lines.append(f"- Scan trigger type: `{scan['scan_trigger_type'] or '—'}`")
    lines.append(f"- Resolved commit SHA: `{scan['resolved_commit_sha'] or '—'}`")
    lines.append(f"- Analyzer version: `{scan['analyzer_version'] or '—'}`")
    lines.append("")

    lines.append("## Scan summary")
    lines.append("")
    lines.append(f"- Component count: **{summary['component_count']}**")
    lines.append(f"- Manifest count: **{summary['manifest_count']}**")
    lines.append(f"- Direct components: **{summary['direct_count']}**")
    lines.append(f"- Transitive components: **{summary['transitive_count']}**")
    lines.append(f"- Components with version present: **{summary['version_present_count']}**")
    lines.append(f"- Components with version missing: **{summary['version_missing_count']}**")
    lines.append(
        f"- Components with licence evidence observed: **{summary['licence_observed_count']}**"
    )
    lines.append(
        f"- Components with licence evidence missing: **{summary['licence_missing_count']}**"
    )
    lines.append(
        f"- Components with provider evidence observed: **{summary['provider_observed_count']}**"
    )
    lines.append(
        f"- Components with provider evidence missing: **{summary['provider_missing_count']}**"
    )
    lines.append(
        f"- Components with persisted dependency edges: **{summary['edges_observed_count']}**"
    )
    lines.append(
        f"- Components with no persisted edges: **{summary['edges_none_observed_count']}**"
    )
    lines.append(f"- PURL persisted: **{summary['purl_persisted_count']}**")
    lines.append(f"- PURL constructible: **{summary['purl_constructible_count']}**")
    lines.append(f"- PURL omitted: **{summary['purl_omitted_count']}**")
    lines.append(f"- Appear in CycloneDX 1.7: **{summary['appears_in_cyclonedx_17_count']}**")
    lines.append(
        f"- Version omitted from CycloneDX 1.7: **{summary['cyclonedx_version_omitted_count']}**"
    )
    lines.append(
        f"- Dependency relationships emitted in CycloneDX 1.7: **{summary['cyclonedx_relationships_emitted_count']}**"
    )
    lines.append("")
    if summary["ecosystems"]:
        lines.append("### Ecosystems")
        lines.append("")
        for ecosystem, count in summary["ecosystems"].items():
            lines.append(f"- `{ecosystem}`: {count}")
        lines.append("")

    lines.append("## Evidence coverage")
    lines.append("")
    lines.append(f"- Inventory coverage: **{coverage['inventory_coverage']}**")
    lines.append(f"- Dependency graph coverage: **{coverage['dependency_graph_coverage']}**")
    lines.append(f"- Provider coverage: **{coverage['provider_coverage']}**")
    lines.append("")
    lines.append(
        "> A partial or unknown dependency graph coverage is not "
        "the same as a complete absence of dependencies. Coverage "
        "is rendered verbatim from the persisted evidence."
    )
    lines.append("")

    lines.append("## Evidence gaps")
    lines.append("")
    lines.append(f"- Components with version missing: **{gaps['missing_version_count']}**")
    lines.append(
        f"- Components with licence evidence missing: **{gaps['missing_licence_evidence_count']}**"
    )
    lines.append(
        f"- Components with provider evidence missing: **{gaps['missing_provider_evidence_count']}**"
    )
    lines.append(
        f"- Components with no persisted dependency edges: **{gaps['no_persisted_edges_count']}**"
    )
    lines.append(
        f"- PURL omitted (not persisted, not constructible): **{gaps['purl_omitted_count']}**"
    )
    lines.append("")

    lines.append("## Component table")
    lines.append("")
    if not components:
        lines.append("_No components recorded for this scan._")
    else:
        lines.append(
            "| Ecosystem | Package | Version | Direct | Licence | Provider | PURL | Edges | CycloneDX version omitted |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in components:
            lines.append(
                f"| `{row['ecosystem'] or '—'}` "
                f"| `{row['package_name']}` "
                f"| `{row['version'] or '—'}` "
                f"| `{_yes_no(row['direct'])}` "
                f"| `{row['licence_evidence']}` "
                f"| `{row['provider_evidence']}` "
                f"| `{row['purl_state']}` "
                f"| `{row['edges_evidence']}` "
                f"| `{_yes_no(row['cyclonedx_version_omitted'])}` |"
            )
    lines.append("")
    if truncated["truncated"]:
        lines.append(
            f"_Component table truncated: shown {truncated['shown']} of "
            f"{truncated['total']}. Reason: {truncated['reason']}._"
        )
        lines.append("")

    lines.append("## Export relationship")
    lines.append("")
    lines.append(
        f"- CycloneDX 1.7 export eligible: **{_yes_no(export_rel['cyclonedx_eligible'])}**"
    )
    lines.append(f"- CycloneDX 1.7 eligibility code: `{export_rel['cyclonedx_eligibility_code']}`")
    lines.append(
        f"- CycloneDX 1.7 eligibility reason: `{export_rel['cyclonedx_eligibility_reason']}`"
    )
    lines.append(
        f"- Components that appear in the CycloneDX 1.7 BOM: **{export_rel['appears_in_cyclonedx_17_count']}**"
    )
    lines.append(
        f"- Components with version omitted from the BOM: **{export_rel['cyclonedx_version_omitted_count']}**"
    )
    lines.append(
        f"- Components with dependency relationships emitted: **{export_rel['cyclonedx_relationships_emitted_count']}**"
    )
    lines.append(
        f"- Components with dependency relationships omitted (no persisted edges): **{export_rel['cyclonedx_relationships_omitted_count']}**"
    )
    lines.append("")
    lines.append(
        "> The CycloneDX 1.7 export never invents dependency "
        "relationships. Components with no persisted edges "
        "have no dependency entries in the BOM; this is "
        "reported as &ldquo;no persisted edges&rdquo;, not "
        "as a complete absence of dependencies."
    )
    lines.append("")

    lines.append("## Evidence-honesty markers")
    lines.append("")
    for marker in omissions:
        lines.append(f"- `{marker}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by Lockverity. This is an evidence report, "
        "not a security verdict, not a certification, and not a "
        "compliance pass-or-fail._"
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Internal builders
# ---------------------------------------------------------------------


def _stable_now_utc(scan: ScanRun) -> str:
    """Return a deterministic UTC timestamp for the report.

    The wall clock is intentionally **not** used here so the
    report is byte-stable for the same persisted evidence
    (the test suite asserts determinism). The value is
    derived from the scan's ``updated_at`` when present, or
    the scan id, or the empty string. The consumer can still
    know the report was generated; the precise generation
    moment is not part of the evidence contract.
    """
    if scan.updated_at is not None:
        return scan.updated_at.isoformat()
    return ""


def _enum_value(value: Any) -> Any:
    """Return the enum ``.value`` when ``value`` is an enum,
    otherwise return the value unchanged. The helper
    preserves ``None`` so the report can render
    &ldquo;unknown&rdquo; for missing enum fields.
    """
    if value is None:
        return None
    if hasattr(value, "value"):
        return value.value
    return value


def _project_components(
    *,
    components: list[Component],
    outgoing_edge_count_by_component: dict[int, int],
    incoming_edge_count_by_component: dict[int, int],
    licence_observed_by_component: dict[int, bool],
    provider_observed_by_component: dict[int, bool],
) -> list[dict[str, Any]]:
    """Project every component into the per-row evidence shape.

    The function is a pure function over the input maps.
    No I/O, no network, no database calls. The shape is
    stable: every row has the same keys, in the same order.
    """
    rows: list[dict[str, Any]] = []
    for component in components:
        version_present = component.version is not None
        outgoing = int(outgoing_edge_count_by_component.get(component.id, 0))
        # The v0.9 evidence-summary rule: a component has
        # ``edges_observed`` when at least one persisted
        # outgoing edge exists. The incoming count is
        # carried for the export-relationship block but
        # does not flip the per-component ``edges_evidence``
        # label, so the report cannot disagree with the
        # v0.9 summary facets.
        edges_observed = outgoing > 0
        licence_observed = bool(licence_observed_by_component.get(component.id, False))
        provider_observed = bool(provider_observed_by_component.get(component.id, False))
        persisted_purl = component.package_url
        if persisted_purl is not None and _is_purl_well_formed(persisted_purl):
            purl_state = "persisted"
        elif _is_purl_constructible(component):
            purl_state = "constructible"
        else:
            purl_state = "omitted"
        appears_in_cyclonedx_17 = True
        version_omitted = not version_present
        dependency_relationships_emitted = outgoing > 0
        rows.append(
            {
                "id": component.id,
                "ecosystem": component.ecosystem,
                "package_name": component.package_name,
                "version": component.version,
                "version_source": (
                    component.version_source.value if component.version_source is not None else None
                ),
                "direct": component.direct,
                "purl_state": purl_state,
                "edges_evidence": ("edges_observed" if edges_observed else "no_persisted_edges"),
                "licence_evidence": (
                    "licence_observed" if licence_observed else "licence_not_persisted"
                ),
                "provider_evidence": (
                    "provider_observed" if provider_observed else "provider_not_persisted"
                ),
                "appears_in_cyclonedx_17": appears_in_cyclonedx_17,
                "cyclonedx_version_omitted": version_omitted,
                "cyclonedx_relationships_emitted": dependency_relationships_emitted,
            }
        )
    return rows


def _build_summary(
    *,
    per_component: list[dict[str, Any]],
    manifests: list[Manifest],
) -> dict[str, Any]:
    """Aggregate the per-row evidence into summary counts.

    The ecosystem list is a small dict ``{ecosystem: count}``
    so the consumer can render the per-ecosystem breakdown
    directly. The sort order is the natural insertion
    order of the per-row scan, which is already
    deterministic.
    """
    ecosystems: dict[str, int] = {}
    direct_count = 0
    transitive_count = 0
    version_present_count = 0
    version_missing_count = 0
    licence_observed_count = 0
    licence_missing_count = 0
    provider_observed_count = 0
    provider_missing_count = 0
    edges_observed_count = 0
    edges_none_observed_count = 0
    purl_persisted_count = 0
    purl_constructible_count = 0
    purl_omitted_count = 0
    appears_in_cyclonedx_17_count = 0
    cyclonedx_version_omitted_count = 0
    cyclonedx_relationships_emitted_count = 0
    for row in per_component:
        if row["ecosystem"]:
            ecosystems[row["ecosystem"]] = ecosystems.get(row["ecosystem"], 0) + 1
        if row["direct"]:
            direct_count += 1
        else:
            transitive_count += 1
        if row["version"] is not None:
            version_present_count += 1
        else:
            version_missing_count += 1
        if row["licence_evidence"] == "licence_observed":
            licence_observed_count += 1
        else:
            licence_missing_count += 1
        if row["provider_evidence"] == "provider_observed":
            provider_observed_count += 1
        else:
            provider_missing_count += 1
        if row["edges_evidence"] == "edges_observed":
            edges_observed_count += 1
        else:
            edges_none_observed_count += 1
        if row["purl_state"] == "persisted":
            purl_persisted_count += 1
        elif row["purl_state"] == "constructible":
            purl_constructible_count += 1
        else:
            purl_omitted_count += 1
        if row["appears_in_cyclonedx_17"]:
            appears_in_cyclonedx_17_count += 1
        if row["cyclonedx_version_omitted"]:
            cyclonedx_version_omitted_count += 1
        if row["cyclonedx_relationships_emitted"]:
            cyclonedx_relationships_emitted_count += 1
    return {
        "component_count": len(per_component),
        "manifest_count": len(manifests),
        "ecosystems": dict(sorted(ecosystems.items())),
        "direct_count": direct_count,
        "transitive_count": transitive_count,
        "version_present_count": version_present_count,
        "version_missing_count": version_missing_count,
        "licence_observed_count": licence_observed_count,
        "licence_missing_count": licence_missing_count,
        "provider_observed_count": provider_observed_count,
        "provider_missing_count": provider_missing_count,
        "edges_observed_count": edges_observed_count,
        "edges_none_observed_count": edges_none_observed_count,
        "purl_persisted_count": purl_persisted_count,
        "purl_constructible_count": purl_constructible_count,
        "purl_omitted_count": purl_omitted_count,
        "appears_in_cyclonedx_17_count": appears_in_cyclonedx_17_count,
        "cyclonedx_version_omitted_count": cyclonedx_version_omitted_count,
        "cyclonedx_relationships_emitted_count": cyclonedx_relationships_emitted_count,
    }


def _build_evidence_gaps(
    *,
    per_component: list[dict[str, Any]],
) -> dict[str, int]:
    """Return the evidence-gap counts the consumer renders.

    The gaps vocabulary mirrors the v0.9 evidence summary
    facets and uses the same evidence-honest wording
    (&ldquo;no persisted edges&rdquo; rather than
    &ldquo;no dependencies&rdquo;).
    """
    missing_version = 0
    missing_licence_evidence = 0
    missing_provider_evidence = 0
    no_persisted_edges = 0
    purl_omitted = 0
    for row in per_component:
        if row["version"] is None:
            missing_version += 1
        if row["licence_evidence"] == "licence_not_persisted":
            missing_licence_evidence += 1
        if row["provider_evidence"] == "provider_not_persisted":
            missing_provider_evidence += 1
        if row["edges_evidence"] == "no_persisted_edges":
            no_persisted_edges += 1
        if row["purl_state"] == "omitted":
            purl_omitted += 1
    return {
        "missing_version_count": missing_version,
        "missing_licence_evidence_count": missing_licence_evidence,
        "missing_provider_evidence_count": missing_provider_evidence,
        "no_persisted_edges_count": no_persisted_edges,
        "purl_omitted_count": purl_omitted,
    }


def _build_component_table(
    *,
    per_component: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the bounded, deterministic component table.

    The table is sorted by ``(package_name, id)`` so the
    output is byte-stable. The table is capped at
    ``COMPONENT_TABLE_LIMIT`` rows; the truncation block
    is always present (even when not truncated) so the
    consumer does not have to branch.
    """
    sorted_rows = sorted(
        per_component,
        key=lambda r: ((r["package_name"] or "").lower(), r["id"]),
    )
    total = len(sorted_rows)
    shown = min(total, COMPONENT_TABLE_LIMIT)
    truncated_block = {
        "truncated": total > COMPONENT_TABLE_LIMIT,
        "shown": shown,
        "total": total,
        "reason": (
            f"Component table capped at {COMPONENT_TABLE_LIMIT} rows."
            if total > COMPONENT_TABLE_LIMIT
            else "No truncation."
        ),
    }
    return sorted_rows[:shown], truncated_block


def _build_export_relationship(
    *,
    eligibility: Any,
    per_component: list[dict[str, Any]],
    inventory_coverage: str,
    dependency_coverage: str,
    provider_coverage: str,
) -> dict[str, Any]:
    """Return the CycloneDX 1.7 export-relationship block.

    The block carries the bounded eligibility verdict the
    v0.6 eligibility helper returns plus the per-row
    export-implication counts the report surfaces.
    """
    appears_in_cyclonedx_17_count = sum(1 for r in per_component if r["appears_in_cyclonedx_17"])
    cyclonedx_version_omitted_count = sum(
        1 for r in per_component if r["cyclonedx_version_omitted"]
    )
    cyclonedx_relationships_emitted_count = sum(
        1 for r in per_component if r["cyclonedx_relationships_emitted"]
    )
    cyclonedx_relationships_omitted_count = sum(
        1 for r in per_component if not r["cyclonedx_relationships_emitted"]
    )
    return {
        "cyclonedx_eligible": bool(getattr(eligibility, "eligible", False)),
        "cyclonedx_eligibility_code": getattr(eligibility, "code", ""),
        "cyclonedx_eligibility_reason": getattr(eligibility, "reason", ""),
        "appears_in_cyclonedx_17_count": appears_in_cyclonedx_17_count,
        "cyclonedx_version_omitted_count": cyclonedx_version_omitted_count,
        "cyclonedx_relationships_emitted_count": cyclonedx_relationships_emitted_count,
        "cyclonedx_relationships_omitted_count": cyclonedx_relationships_omitted_count,
        # Echo the inventory / dependency / provider coverage
        # for the consumer that wants the report's coverage
        # block to align with the evidence-summary facets.
        "inventory_coverage": inventory_coverage,
        "dependency_graph_coverage": dependency_coverage,
        "provider_coverage": provider_coverage,
    }


def _yes_no(value: bool) -> str:
    """Render a boolean as the literal ``yes`` / ``no`` text.

    The report never uses &ldquo;available&rdquo; /
    &ldquo;missing&rdquo; / &ldquo;unknown&rdquo; for these
    booleans; the consumer already knows the column.
    """
    return "yes" if value else "no"


# ---------------------------------------------------------------------
# Service class (session lifecycle wrapper)
# ---------------------------------------------------------------------


class EvidenceReportService:
    """Session-lifecycle wrapper around the v1.0 report.

    The service is the read-only entry point the API
    layer calls. It opens a session, fetches the persisted
    evidence in deterministic order, calls the free
    function, and closes the session. The service never
    mutates state, never calls a provider, and never
    executes analyzed code.
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def fetch(self, *, scan_run_id: int) -> dict[str, Any] | None:
        """Return the v1.0 evidence report for ``scan_run_id``.

        Returns ``None`` only when the scan id does not
        exist (the API layer maps that to a 404). For every
        other scan state, the method returns the report
        dict with the documented shape. The report is
        honest about non-terminal scan states: failed,
        cancelled, queued, and running scans return a
        report with empty inventory and a
        ``not_applicable`` coverage verdict.
        """
        session = self._session_factory()
        try:
            return self._fetch_in_session(
                session,
                scan_run_id=scan_run_id,
            )
        finally:
            session.close()

    @staticmethod
    def _fetch_in_session(
        session: Session,
        *,
        scan_run_id: int,
    ) -> dict[str, Any] | None:
        scan = session.get(ScanRun, scan_run_id)
        if scan is None:
            return None
        repository = session.get(Repository, scan.repository_id)
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
        edge_rows = (
            session.query(DependencyEdge).filter(DependencyEdge.scan_run_id == scan_run_id).all()
        )
        outgoing_edge_count_by_component: dict[int, int] = {}
        incoming_edge_count_by_component: dict[int, int] = {}
        for edge in edge_rows:
            outgoing_edge_count_by_component[edge.parent_component_id] = (
                outgoing_edge_count_by_component.get(edge.parent_component_id, 0) + 1
            )
            incoming_edge_count_by_component[edge.child_component_id] = (
                incoming_edge_count_by_component.get(edge.child_component_id, 0) + 1
            )
        licence_observed_by_component: dict[int, bool] = _collect_licence_evidence(
            session=session,
            scan_run_id=scan_run_id,
        )
        provider_observed_by_component: dict[int, bool] = _collect_provider_evidence(
            session=session,
            scan_run_id=scan_run_id,
        )
        return build_evidence_report(
            scan=scan,
            repository=repository,
            components=list(components),
            manifests=list(manifests),
            outgoing_edge_count_by_component=outgoing_edge_count_by_component,
            incoming_edge_count_by_component=incoming_edge_count_by_component,
            licence_observed_by_component=licence_observed_by_component,
            provider_observed_by_component=provider_observed_by_component,
        )


def _collect_licence_evidence(
    *,
    session: Session,
    scan_run_id: int,
) -> dict[int, bool]:
    """Return ``{component_id: True}`` for every component
    that has at least one LICENCE-category finding with a
    non-empty ``licences`` list. Mirrors the v0.8 / v0.9
    evidence-summary rule.
    """
    import json as _json

    licence_rows = (
        session.query(Finding)
        .filter(
            Finding.scan_run_id == scan_run_id,
            Finding.category == FindingCategory.LICENCE,
        )
        .all()
    )
    observed: dict[int, bool] = {}
    for finding in licence_rows:
        try:
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
                observed[component_id] = True
    return observed


def _collect_provider_evidence(
    *,
    session: Session,
    scan_run_id: int,
) -> dict[int, bool]:
    """Return ``{component_id: True}`` for every component
    that has at least one ``ProviderObservation`` row. The
    v0.8 / v0.9 evidence-summary rule.
    """
    rows = (
        session.query(ProviderObservation)
        .filter(
            ProviderObservation.scan_run_id == scan_run_id,
            ProviderObservation.component_id.isnot(None),
        )
        .all()
    )
    observed: dict[int, bool] = {}
    for obs in rows:
        if obs.component_id is not None:
            observed[obs.component_id] = True
    return observed


__all__ = [
    "COMPONENT_TABLE_LIMIT",
    "EVIDENCE_REPORT_OMISSIONS",
    "REPORT_FORMAT_KEY",
    "REPORT_MEDIA_TYPE",
    "EvidenceReportService",
    "build_evidence_report",
    "render_evidence_report_markdown",
]
