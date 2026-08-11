"""CycloneDX 1.7 SBOM exporter (v0.6).

This exporter is the v0.6 standards-compliant successor of
:mod:`app.exporters.cyclonedx` (v0.5 / CycloneDX 1.5). It generates
a JSON SBOM against the official CycloneDX 1.7 schema using the
``cyclonedx-python-lib`` library, and it validates the generated
BOM with the library's offline strict validator before returning
it. The exporter is read-only; it never mutates the database,
never calls an external provider, and never executes repository
content.

The exporter follows the v0.6 evidence-honesty rules:

- It only reads persisted evidence. No data is fabricated.
- A missing component version is preserved as a missing
  field; the library's JSON output omits ``version`` entirely.
  The exporter never substitutes a placeholder string.
- Components, package URLs, licences, hashes, and dependency
  edges are taken verbatim from the v0.3-v0.5 schema; a field is
  emitted only when the persisted evidence supports it.
- The BOM serial number is a UUID5 derived from the scan id and
  a stable hash of the persisted evidence, so repeated exports of
  the unchanged scan are byte-for-byte deterministic.
- The metadata timestamp is the scan's ``completed_at`` (or, for
  partial scans with no completion yet, the persisted
  ``updated_at``). The current wall-clock time is never used.
- The eligible-scan rule rejects failed, cancelled, queued, and
  running scans, and rejects partial scans without sufficient
  local-analysis evidence. The single authoritative helper lives
  in :mod:`app.exporters._common`.
- Dependency edges are emitted only from persisted
  ``DependencyEdge`` rows; no edge is invented from manifest
  co-occurrence, component presence, or library validation
  convenience. The dependency-graph coverage property is
  computed from the manifest parse statuses, not from heuristics
  about edge counts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
import warnings
from collections.abc import Callable
from datetime import UTC
from typing import Any

from packageurl import PackageURL
from sqlalchemy.orm import Session, sessionmaker

from app._version import __version__
from app.exporters._common import (
    ExportEligibility,
    ScanNotFoundError,
    evaluate_export_eligibility,
    fetch_components,
    fetch_dependency_edges,
    fetch_manifests,
    fetch_observations,
    get_scan_or_raise,
)
from app.models.component import Component
from app.models.finding import Finding, FindingCategory
from app.models.manifest import Manifest
from app.models.provider_observation import ProviderObservation
from app.models.repository import Repository
from app.models.scan_run import ScanRun, ScanStatus
from app.providers.results import (
    ProviderOutcome,
    ProviderSuccess,
    ProviderUnavailable,
)
from app.utils.datetime import utcnow

# CycloneDX 1.7 constants. The exporter targets exactly the 1.7
# JSON schema. It does not emit XML, SPDX, VEX, or any other
# companion document.
CYCLONEDX_SPEC_VERSION = "1.7"
CYCLONEDX_SCHEMA_URI = "http://cyclonedx.org/schema/bom-1.7.schema.json"
CYCLONEDX_MEDIA_TYPE = "application/vnd.cyclonedx+json; version=1.7"
CYCLONEDX_FORMAT_KEY = "cyclonedx_1_7"

# Stable namespace used to derive the deterministic BOM serial
# number. The namespace URL is Lockverity-specific and never
# collides with the CycloneDX default namespace.
_CYCLONEDX_NAMESPACE = uuid.UUID("9c5d9e88-1c4f-4f4d-9f4a-7e2a5d8a3b91")

# SPDX expression operators. The library's ``is_expression``
# helper returns ``True`` for both single identifiers and
# expressions; we only treat a value as an expression when it
# also contains one of these operators.
_SPDX_EXPRESSION_OPERATORS = re.compile(r"\b(AND|OR|WITH)\b")

# Lockverity property namespace used to surface evidence-coverage
# and provenance metadata. Following the existing project
# convention set in v0.5 (the comparison service and the
# existing 1.5 exporter), the prefix is ``lockverity:``.
_LOCKVERITY_PROP_PREFIX = "lockverity:"

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# SPDX classification
# ---------------------------------------------------------------------


def _classify_licence_value(value: str) -> str:
    """Classify a single observed licence string.

    The classifier returns one of three labels:

    - ``"spdx-id"`` — the value is a recognised SPDX
      identifier (the library's :func:`is_supported_id` returns
      ``True``).
    - ``"spdx-expression"`` — the value contains SPDX
      expression operators (``AND``/``OR``/``WITH``) and the
      library's :func:`is_expression` accepts it. A single
      identifier that also passes ``is_expression`` is **not**
      treated as an expression (the expression operators are
      the discriminator).
    - ``"observed-name"`` — the value is not recognised by the
      library. It is preserved verbatim as the CycloneDX
      ``name`` field so the consumer can see the observed
      value without the exporter fabricating an SPDX id.
    """
    from cyclonedx.spdx import is_expression, is_supported_id

    if not isinstance(value, str) or not value:
        return "observed-name"
    if is_supported_id(value):
        return "spdx-id"
    if _SPDX_EXPRESSION_OPERATORS.search(value) and is_expression(value):
        return "spdx-expression"
    return "observed-name"


def _build_licence_objects(values: list[str]) -> list[Any]:
    """Translate a list of observed licence strings into library objects.

    The exporter uses the official :class:`LicenseFactory` from
    ``cyclonedx.contrib.license.factories`` so the library's SPDX
    list and SPDX expression parser are the single source of
    truth. The factory is imported lazily so this module remains
    importable in environments where the optional ``cyclonedx``
    extras are not installed.
    """
    from cyclonedx.contrib.license.factories import LicenseFactory

    factory = LicenseFactory()
    objects: list[Any] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        kind = _classify_licence_value(value)
        if kind == "spdx-id":
            try:
                objects.append(factory.make_with_id(value))
            except Exception:  # pragma: no cover - defensive
                # The library's SPDX list and our local helper
                # agreed; the factory must accept the value. If
                # it does not for any reason, fall back to
                # ``name`` so the licence is still emitted.
                objects.append(factory.make_with_name(value))
        elif kind == "spdx-expression":
            try:
                objects.append(factory.make_with_expression(value))
            except Exception:  # pragma: no cover - defensive
                objects.append(factory.make_with_name(value))
        else:
            # Observed-name path: the consumer sees the
            # exact observed string as a non-SPDX ``name``.
            objects.append(factory.make_with_name(value))
    return objects


# ---------------------------------------------------------------------
# Manifest-derived evidence helpers
# ---------------------------------------------------------------------


def _evidence_content_hash(
    components: list[Component],
    manifests: list[Manifest],
    dependency_edges: list[Any],
    licences: dict[int, str],
) -> str:
    """Return a stable SHA-256 hex digest of the persisted evidence.

    The hash depends only on the persisted rows that affect the
    BOM. Re-exporting the unchanged scan yields the same hash,
    which keeps the BOM serial number byte-for-byte stable.
    """
    h = hashlib.sha256()
    for c in components:
        h.update(f"c{c.id}|{c.package_name}|{c.version}|{c.ecosystem}|".encode())
        h.update(f"{c.direct}|{c.development}|{c.optional}|{c.integrity}".encode())
    for m in manifests:
        h.update(f"m{m.id}|{m.path}|{m.manifest_type}|{m.content_sha256}|".encode())
    for e in dependency_edges:
        h.update(
            f"e{e.id}|{e.parent_component_id}|{e.child_component_id}|{e.relationship}|".encode()
        )
    for component_id in sorted(licences):
        h.update(f"l{component_id}|{licences[component_id]}|".encode())
    return h.hexdigest()


def _build_serial_number(scan: ScanRun, content_hash: str) -> str:
    """Return the deterministic BOM serial number for ``scan``."""
    return str(uuid.uuid5(_CYCLONEDX_NAMESPACE, f"lockverity-scan-{scan.id}-{content_hash}"))


def _bom_ref_for(component: Component) -> str:
    """Return a unique, deterministic bom-ref for a persisted component.

    When the persisted component carries a valid PURL, the PURL
    is the natural bom-ref because the package-url spec already
    guarantees uniqueness within a CycloneDX BOM and most
    consumers dereference PURLs. When the persisted PURL is
    missing, malformed, or duplicates another component's PURL,
    we fall back to a deterministic
    ``lockverity:component:{id}`` identifier. The exporter
    guarantees uniqueness across the whole BOM by replacing
    duplicates with a per-component-id fallback.
    """
    purl = component.package_url
    if purl:
        try:
            # Round-tripping the PURL through ``packageurl`` is
            # the standards-aware validity check; the library
            # will raise on any malformed value.
            PackageURL.from_string(purl)
            return purl
        except Exception:  # pragma: no cover - defensive
            _LOGGER.debug(
                "packageurl_roundtrip_failed",
                extra={"purl": purl},
            )
    return f"lockverity:component:{component.id}"


def _bom_ref_is_duplicate(ref: str, seen: set[str], component: Component) -> str:
    """Return a unique bom-ref, replacing duplicates with the fallback id."""
    if ref not in seen:
        return ref
    return f"lockverity:component:{component.id}"


def _parse_licence_evidence_json(evidence_json: str | None) -> tuple[list[str], str | None]:
    """Return the list of licence strings and a single source label.

    The exporter only emits a licence when at least one string is
    present. Returns ``([], None)`` when the evidence is empty or
    malformed. The evidence envelope used by the Lockverity
    finding model wraps the observation under ``evidence``, so
    this helper looks there.
    """
    if not evidence_json:
        return [], None
    try:
        envelope = json.loads(evidence_json)
    except (ValueError, TypeError):
        return [], None
    if not isinstance(envelope, dict):
        return [], None
    payload = envelope.get("evidence") or {}
    if not isinstance(payload, dict):
        payload = {}
    raw = payload.get("licences")
    if not isinstance(raw, list):
        # Fallback: a top-level ``licences`` field. The exporter
        # accepts both shapes so the evidence envelope can
        # evolve without breaking older findings.
        raw = envelope.get("licences")
    if not isinstance(raw, list):
        return [], None
    licences = [str(item) for item in raw if isinstance(item, (str, int, float))]
    licences = [item for item in licences if item]
    source_raw = (
        payload.get("source")
        or payload.get("provider")
        or envelope.get("source")
        or envelope.get("provider")
    )
    source = str(source_raw) if isinstance(source_raw, str) and source_raw else None
    return licences, source


def _parse_extras(evidence_json: str | None) -> dict[str, Any]:
    if not evidence_json:
        return {}
    try:
        value = json.loads(evidence_json)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _dependency_graph_coverage(manifests: list[Manifest], edges: list[Any]) -> str:
    """Compute the dependency-graph coverage from manifests and edges.

    The v0.3-v0.5 schema has **no authoritative persisted signal**
    that positively proves the full transitive closure of every
    applicable manifest was captured. The
    :class:`Manifest.parse_status` field reports whether the
    parser ran without raising; it does **not** report whether
    every transitive relationship was extracted. A
    ``package.json`` manifest is a real example: the parser
    returns successfully, ``parse_status`` becomes
    ``PARSED``, but the manifest only declares direct
    dependencies. The model cannot distinguish a "lockfile
    that captured the full transitive closure" from a
    "manifest that only declared direct dependencies" without
    a new persisted field, and the v0.6 milestone explicitly
    forbids fabricating one.

    The v0.6 evidence-honesty rule is therefore:

    - ``"unknown"`` when no manifests were persisted. The
      applicability of the graph cannot even be established;
      no parser ran, no inventory was extracted, no edges
      were observed. This is the most honest answer.
    - ``"partial"`` when at least one manifest was persisted
      (regardless of its ``parse_status``). Some relationship
      evidence exists or at least one manifest was analysed,
      but completeness is not provable from the persisted
      schema. This includes the "every manifest PARSED + at
      least one edge" case: the schema does not positively
      prove the transitive closure was captured, so the
      graph is reported as partial, not complete.
    - ``"complete"`` is **intentionally never emitted in
      v0.6**. The schema has no completeness signal, and the
      v0.6 milestone does not introduce one. A future
      milestone may add a persisted field (for example,
      ``Manifest.transitive_closure_captured`` set by the
      parser when the format guarantees the full transitive
      closure); until that field exists, claiming
      completeness would be a fabrication.

    The "edges" argument is retained for API symmetry and for
    the v0.6 documentation comments; the rule does not use it
    to flip to "complete". A non-empty edge list is consistent
    with a partial graph (a transitive closure can have
    observed edges without the closure being complete).
    """
    if not manifests:
        return "unknown"
    # Some evidence exists (or at least one manifest was
    # analysed). The v0.6 schema has no positive proof of
    # full closure, so the answer is "partial" by default.
    return "partial"


# ---------------------------------------------------------------------
# v0.7 Preview / readiness summary
# ---------------------------------------------------------------------


# SBOM output facts that the v0.7 preview returns to the
# frontend. The constants are module-level so the API
# layer, the exporter, and the test suite all reference the
# same authoritative values. Changing a value here changes
# the documented contract.
_PREVIEW_BOM_FORMAT = "CycloneDX"
_PREVIEW_SPEC_VERSION = "1.7"
_PREVIEW_MEDIA_TYPE = CYCLONEDX_MEDIA_TYPE
_PREVIEW_FILENAME_TEMPLATE = "lockverity-scan-{scan_id}.cdx.json"
_PREVIEW_SCHEMA_URI = CYCLONEDX_SCHEMA_URI


def _inventory_coverage(component_count: int, scan_status: ScanStatus) -> str:
    """Return the inventory coverage label for the preview.

    The v0.7 evidence-honesty contract uses the smallest
    vocabulary that fits the existing frontend / backend
    types:

    - ``"complete"`` — the scan is eligible (COMPLETED with
      persisted evidence, or a PARTIAL scan whose local
      inventory is sufficient) **and** at least one
      component was observed. This matches the v0.6 export
      contract for the same scan state.
    - ``"empty"`` — the scan is eligible but no component
      was observed (e.g. a COMPLETED scan against a
      repository that genuinely has no manifest-pinned
      dependencies), OR a PARTIAL_INCOMPLETE scan whose
      local analysis ran but produced no inventory.
    - ``"not_applicable"`` — the scan is ineligible and the
      inventory assessment never ran (FAILED, CANCELLED,
      QUEUED, RUNNING). The label is **not** ``"empty"``
      because the scan did not reach the inventory phase;
      reporting ``"empty"`` would imply the scan ran and
      found nothing, which is misleading for a scan that
      crashed or was cancelled mid-flight.

    The function never returns ``"complete"`` for a
    non-terminal scan state, even if rows were persisted
    before the failure; the v0.6 export rule never accepts
    those scans, and the preview must not contradict it.
    """
    if scan_status in {
        ScanStatus.FAILED,
        ScanStatus.CANCELLED,
        ScanStatus.QUEUED,
        ScanStatus.RUNNING,
    }:
        # The scan never reached the inventory phase. The
        # preview does not report "empty" because that
        # would imply a deliberate result; the honest
        # answer is that the assessment is not applicable.
        return "not_applicable"
    if component_count <= 0:
        return "empty"
    return "complete"


def _provider_coverage(eligibility: ExportEligibility) -> str:
    """Return the provider coverage label for the preview.

    The v0.7 evidence-honesty contract uses the smallest
    vocabulary that fits the existing frontend / backend
    types:

    - ``"ok"`` — the scan is eligible and no provider
      limitation was reported. This matches the v0.6 BOM
      contract for the same scan state.
    - ``"degraded"`` — the scan is eligible but the
      eligibility verdict reports a provider-degradation
      limitation (the local analysis ran to completion, the
      provider phase did not). This matches the v0.6 BOM
      contract for the same scan state.
    - ``"not_applicable"`` — the scan is ineligible. The
      provider was never queried (FAILED / CANCELLED /
      QUEUED / RUNNING) or the scan did not produce enough
      local evidence to know whether a provider call would
      have applied (PARTIAL_INCOMPLETE). The preview does
      **not** report ``"ok"`` for an ineligible scan: that
      would invent a positive provider result the
      persisted schema does not support.

    No provider call is made here; the label is derived
    from the existing eligibility verdict. The vocabulary
    is the smallest that distinguishes "we know the
    provider phase is fine", "we know it is degraded",
    and "we cannot say because the scan did not reach that
    phase"."""
    return eligibility.provider_coverage


def _duplicate_package_version_count(components: list[Component]) -> int:
    """Return the count of duplicate package/version observations.

    A duplicate is counted as ``(components - unique_keys)``
    where ``unique_keys`` is the number of distinct
    ``(package_name, version)`` pairs across the inventory.
    The count is honest: a single duplicate observation
    adds 1 to the count, two duplicates add 2, and so on.
    Components with a missing version are keyed on
    ``(package_name, None)`` so a package observed once with
    a version and once without is correctly counted as
    two distinct observations."""
    if not components:
        return 0
    seen: set[tuple[str, str | None]] = set()
    duplicates = 0
    for component in components:
        key = (component.package_name, component.version)
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
    return duplicates


def build_cyclonedx_v17_preview(
    *,
    scan: ScanRun,
    components: list[Component],
    manifests: list[Manifest],
    edges: list[Any],
    provider_observations: list[ProviderObservation] | None = None,
) -> dict[str, Any]:
    """Return the v0.7 CycloneDX 1.7 preview / readiness summary.

    The function is the single authoritative backend entry
    point for the v0.7 preview endpoint. It is read-only,
    never generates a full BOM, never calls a provider,
    never executes repository content, and never writes
    to the database.

    The response shape is the documented v0.7 contract:

    1. **scan identity** — id, repository id, status,
       source kind if known.
    2. **eligibility** — the v0.6 authoritative verdict
       plus a ``download_expected_to_succeed`` boolean the
       frontend can render alongside the actual download
       button.
    3. **inventory summary** — counts the persisted
       components and manifests, the observed ecosystems,
       direct vs transitive counts when persisted, the
       missing-version count, and the duplicate
       package/version observation count.
    4. **evidence coverage** — inventory coverage,
       dependency-graph coverage, provider coverage.
    5. **SBOM output facts** — format, spec version, media
       type, deterministic filename template, the schema
       validation contract, and the persisted-evidence
       generator contract.
    6. **omissions and limitations** — the v0.6
       evidence-honesty rules the consumer should be able
       to read before download.
    7. **legacy export relationship** — the bounded note
       that older exports may still be empty-but-valid for
       failed / cancelled scans, while CycloneDX 1.7
       requires sufficient persisted inventory.

    The function is deterministic for a given scan state:
    the same persisted evidence always produces the same
    bytes (modulo JSON formatting, which is sorted-keys
    compact). The eligibility verdict, the counts, and
    the coverage labels all derive from the persisted
    schema and the v0.6 helper, never from the wall clock
    or any non-deterministic source.
    """
    # 1. scan identity
    source_kind = "scan"
    if scan.trigger_type is not None:
        # The persisted trigger_type is informational; it
        # tells the consumer whether the scan was an
        # explicit operator action, an upload, an
        # scheduled run, or an API call. The v0.7 preview
        # surfaces the trigger value so the consumer can
        # distinguish a manually triggered scan from an
        # API-driven run.
        source_kind = f"scan:{scan.trigger_type.value}"
    scan_identity = {
        "scan_id": scan.id,
        "repository_id": scan.repository_id,
        "scan_status": scan.status.value,
        "source_kind": source_kind,
    }

    # 2. eligibility — single authoritative backend rule.
    eligibility = evaluate_export_eligibility(
        scan,
        component_count=len(components),
        manifest_count=len(manifests),
        provider_observations=provider_observations,
    )
    eligibility_block = {
        "eligible": eligibility.eligible,
        "code": eligibility.code,
        "reason": eligibility.reason,
        "limitations": list(eligibility.limitations),
        "download_expected_to_succeed": eligibility.eligible,
    }

    # 3. inventory summary
    ecosystems = sorted({c.ecosystem for c in components if c.ecosystem})
    direct_count = sum(1 for c in components if c.direct)
    transitive_count = sum(1 for c in components if not c.direct)
    missing_version_count = sum(1 for c in components if c.version is None)
    duplicate_count = _duplicate_package_version_count(components)
    inventory_summary = {
        "component_count": len(components),
        "manifest_count": len(manifests),
        "ecosystems": ecosystems,
        "direct_count": direct_count,
        "transitive_count": transitive_count,
        "missing_version_count": missing_version_count,
        "duplicate_observations_count": duplicate_count,
    }

    # 4. evidence coverage
    inventory_coverage = _inventory_coverage(len(components), scan.status)
    graph_coverage = _dependency_graph_coverage(manifests, edges)
    provider_coverage = _provider_coverage(eligibility)
    evidence_coverage = {
        "inventory_coverage": inventory_coverage,
        "dependency_graph_coverage": graph_coverage,
        "provider_coverage": provider_coverage,
    }

    # 5. SBOM output facts
    sbom_output = {
        "format": _PREVIEW_BOM_FORMAT,
        "spec_version": _PREVIEW_SPEC_VERSION,
        "media_type": _PREVIEW_MEDIA_TYPE,
        "filename_template": _PREVIEW_FILENAME_TEMPLATE,
        "schema_uri": _PREVIEW_SCHEMA_URI,
        "schema_validation": "official_offline_JsonStrictValidator_v1_7",
        "generation_source": "persisted_scan_evidence",
    }

    # 6. omissions and limitations
    omissions = [
        "no_invented_versions",
        "no_inferred_dependency_edges",
        "no_dependency_graph_completeness_claim_without_positive_proof",
        "no_clean_or_security_verdict",
        "no_repository_code_execution",
        "unavailable_provider_data_is_not_converted_to_none",
    ]
    if "provider_omitted_by_operator" in eligibility.limitations:
        omissions.append("external_provider_evidence_omitted_by_operator")

    # 7. legacy export relationship
    legacy_note = (
        "Older exports (CycloneDX 1.5 SBOM, findings JSON, "
        "findings CSV, SARIF) may still be empty-but-valid for "
        "failed or cancelled scans, while CycloneDX 1.7 "
        "requires sufficient persisted local inventory to "
        "honestly represent the analyzed evidence."
    )

    return {
        "scan": scan_identity,
        "eligibility": eligibility_block,
        "inventory": inventory_summary,
        "evidence_coverage": evidence_coverage,
        "sbom_output": sbom_output,
        "omissions": omissions,
        "legacy_export_relationship": legacy_note,
    }


# ---------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------


class CycloneDxV17Exporter:
    """CycloneDX 1.7 SBOM exporter.

    The exporter is a pure function over the persisted scan
    state. The same scan, with the same persisted evidence,
    always produces the same byte sequence.
    """

    format = CYCLONEDX_FORMAT_KEY

    def __init__(
        self,
        session_factory: sessionmaker[Session] | Callable[[], Session],
    ) -> None:
        self._session_factory = session_factory
        self._app_version = __version__

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def preview(self, *, scan_run_id: int) -> dict[str, Any] | None:
        """Return the v0.7 preview / readiness summary for ``scan_run_id``.

        The method is the read-only, deterministic entry point
        for the ``GET /api/v1/scans/{scan_id}/exports/cyclonedx_1_7/preview``
        endpoint. It returns ``None`` only when the scan does
        not exist (the API layer maps that to a 404). For
        every other scan, the method returns a preview dict
        that mirrors the documented v0.7 contract; the
        verdict is always informative (the eligibility block
        carries the verdict, not the HTTP status).

        The method is read-only: it never generates a full
        BOM, never validates against the official JSON
        schema, never calls a provider, never executes
        repository content, and never writes to the
        database.
        """
        session = self._session_factory()
        try:
            try:
                scan = get_scan_or_raise(session, scan_run_id)
            except ScanNotFoundError:
                return None
            components = list(fetch_components(session, scan_run_id))
            manifests = list(fetch_manifests(session, scan_run_id))
            edges = list(fetch_dependency_edges(session, scan_run_id))
            provider_observations = list(fetch_observations(session, scan_run_id))
        finally:
            session.close()
        return build_cyclonedx_v17_preview(
            scan=scan,
            components=components,
            manifests=manifests,
            edges=edges,
            provider_observations=provider_observations,
        )

    def export(self, *, scan_run_id: int) -> ProviderSuccess[bytes] | ProviderUnavailable:
        """Return the CycloneDX 1.7 JSON document for ``scan_run_id``.

        The exporter never raises on eligibility problems. Ineligible
        scans are returned as :class:`ProviderUnavailable` with a
        bounded error code and a human-readable summary; the API
        layer maps that to a 409/422 response without leaking
        internal paths or validator internals.
        """
        session = self._session_factory()
        try:
            try:
                scan = get_scan_or_raise(session, scan_run_id)
            except ScanNotFoundError:
                return self._unavailable(
                    code="export_scan_not_found",
                    summary=f"Scan {scan_run_id} not found.",
                )
            components = list(fetch_components(session, scan_run_id))
            manifests = list(fetch_manifests(session, scan_run_id))
            edges = list(fetch_dependency_edges(session, scan_run_id))
            provider_observations = list(fetch_observations(session, scan_run_id))
            licence_findings = self._fetch_licence_findings(session, scan_run_id)
            # Materialise the fields we need before the session
            # closes. After ``session.close()`` the detached rows
            # cannot re-load their attributes, so we snapshot the
            # evidence envelopes into plain Python data here.
            licence_records: list[dict[str, Any]] = [
                {
                    "id": f.id,
                    "rule_id": f.rule_id,
                    "stable_key": f.stable_key,
                    "evidence_json": f.evidence_json,
                }
                for f in licence_findings
            ]
        finally:
            session.close()
        eligibility = evaluate_export_eligibility(
            scan,
            component_count=len(components),
            manifest_count=len(manifests),
            provider_observations=provider_observations,
        )
        if not eligibility.eligible:
            return self._unavailable(code=eligibility.code, summary=eligibility.reason)

        try:
            payload = self._build_payload(
                scan=scan,
                components=components,
                manifests=manifests,
                edges=edges,
                licence_records=licence_records,
                eligibility=eligibility,
            )
        except _ValidationFailedError:
            return self._unavailable(
                code="cyclonedx_validation_failed",
                summary=(
                    "Generated CycloneDX 1.7 BOM failed official schema "
                    "validation. The export is refused; the scan "
                    "evidence itself is unchanged."
                ),
            )
        except _ExporterError as exc:
            return self._unavailable(code=exc.code, summary=exc.summary)

        return ProviderSuccess(
            data=payload.encode("utf-8"),
            fetched_at=utcnow(),
            records_returned=len(components),
        )

    # ------------------------------------------------------------------
    # Payload construction
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        *,
        scan: ScanRun,
        components: list[Component],
        manifests: list[Manifest],
        edges: list[Any],
        licence_records: list[dict[str, Any]],
        eligibility: ExportEligibility,
    ) -> str:
        from cyclonedx.model.bom import Bom, BomMetaData
        from cyclonedx.model.component import Component as CdxComponent
        from cyclonedx.model.component import ComponentType
        from cyclonedx.model.tool import ToolRepository
        from cyclonedx.output.json import JsonV1Dot7
        from cyclonedx.schema.schema import SchemaVersion
        from cyclonedx.validation.json import JsonStrictValidator

        # 1. Map every component to a unique bom-ref. Two
        # persisted components may share the same persisted
        # PURL (e.g. one observed in package.json and one in
        # package-lock.json). CycloneDX requires unique
        # bom-refs; we keep the first PURL and fall back to a
        # per-id reference for the rest.
        component_id_to_ref: dict[int, str] = {}
        seen_refs: set[str] = set()
        manifest_by_id: dict[int, Manifest] = {m.id: m for m in manifests}
        licence_by_component_id: dict[int, list[dict[str, Any]]] = {}
        for record in licence_records:
            evidence_json = record.get("evidence_json") or ""
            extras = _parse_extras(evidence_json)
            payload = extras.get("evidence", {}) or {}
            component_id = payload.get("component_id")
            if isinstance(component_id, int):
                licence_by_component_id.setdefault(component_id, []).append(record)

        bom_components: list[CdxComponent] = []
        for component in components:
            base_ref = _bom_ref_for(component)
            unique_ref = _bom_ref_is_duplicate(base_ref, seen_refs, component)
            seen_refs.add(unique_ref)
            component_id_to_ref[component.id] = unique_ref

            properties = self._build_component_properties(component, manifest_by_id)
            cdx = CdxComponent(
                name=component.package_name,
                type=ComponentType.LIBRARY,
                bom_ref=unique_ref,
            )
            # A missing persisted version is preserved as a
            # missing field. The library omits the JSON
            # ``version`` property entirely when the attribute
            # is ``None``; the consumer therefore sees no
            # placeholder, no ``"unspecified"`` string, no
            # empty string. The component is annotated with
            # ``lockverity:version-source`` so the absence is
            # traceable.
            if component.version is not None:
                cdx.version = component.version
            else:
                properties["lockverity:version-source"] = (
                    component.version_source.value
                    if component.version_source is not None
                    else "unresolved"
                )
            if component.ecosystem:
                properties["lockverity:ecosystem"] = component.ecosystem
            if component.package_url:
                # The library requires a ``PackageURL`` object.
                # The standards-aware round-trip guarantees the
                # value is well-formed; an exception here means
                # the persisted value is malformed and we
                # silently drop it.
                try:
                    cdx.purl = PackageURL.from_string(component.package_url)
                except Exception:
                    properties["lockverity:invalid-purl"] = component.package_url
            elif component.ecosystem in ("npm", "pypi") and component.package_name:
                # The persisted PURL is null; reconstruct it
                # from the ecosystem + package name + version
                # using the standards-aware PackageURL
                # implementation. The standards-aware
                # constructor rejects invalid combinations.
                # Without a usable PURL the component still
                # appears in the BOM; the
                # ``lockverity:ecosystem`` property keeps the
                # observation traceable.
                try:
                    purl = PackageURL(
                        type=component.ecosystem,
                        name=component.package_name,
                        version=component.version or None,
                    )
                    cdx.purl = purl
                except Exception:  # pragma: no cover - defensive
                    _LOGGER.debug(
                        "packageurl_build_failed",
                        extra={
                            "ecosystem": component.ecosystem,
                            "name": component.package_name,
                        },
                    )
            if component.integrity:
                # Lockverity stores integrity strings verbatim;
                # the consumer decides which hash algorithm
                # applies. We surface the raw value via a
                # property because the schema is opaque to
                # CycloneDX without parsing it.
                properties["lockverity:integrity"] = component.integrity
            if component.direct:
                properties["lockverity:direct"] = "true"
            if component.development:
                properties["lockverity:development"] = "true"
            if component.optional:
                properties["lockverity:optional"] = "true"
            if component.scope:
                properties["lockverity:scope"] = component.scope

            # Licences: emit every observed value as a CycloneDX
            # licence object, classified by the library's SPDX
            # support. The classification decides whether the
            # value is emitted as an SPDX id, an SPDX
            # expression, or a non-SPDX observed name. We do
            # not add a ``lockverity:licence-spdx-verified``
            # property because the library's id-vs-name choice
            # already carries the SPDX provenance.
            licence_records_for_component = licence_by_component_id.get(component.id, [])
            observed_licence_values: list[str] = []
            licence_sources: set[str] = set()
            for record in licence_records_for_component:
                values, source = _parse_licence_evidence_json(record.get("evidence_json"))
                observed_licence_values.extend(values)
                if source:
                    licence_sources.add(source)
            licence_objects = _build_licence_objects(observed_licence_values)
            if licence_objects:
                cdx.licenses = licence_objects
                if licence_sources:
                    properties["lockverity:licence-sources"] = ",".join(sorted(licence_sources))

            self._attach_properties(cdx, properties)
            bom_components.append(cdx)

        # 2. Build the dependency graph. Only persisted
        # DependencyEdge rows are emitted. We never invent
        # edges from manifest co-occurrence, from the
        # "direct" / "transitive" label, or from the library's
        # validation convenience. An absent edge means
        # "unknown", not "no dependencies".
        bom_dependencies = self._build_dependencies(component_id_to_ref, edges)

        # 3. Build BOM metadata with a deterministic serial
        # number. The serial number is a UUID5 derived from
        # the scan id and a stable SHA-256 hash of every
        # persisted row that affects the BOM. Repeated exports
        # of the unchanged scan therefore produce the same
        # serial number, exactly as the v0.6 spec requires.
        licences_for_hash: dict[int, str] = {}
        for cid, records in licence_by_component_id.items():
            values, _ = _parse_licence_evidence_json(records[0].get("evidence_json"))
            if values:
                licences_for_hash[cid] = ",".join(sorted(values))
        content_hash = _evidence_content_hash(components, manifests, edges, licences_for_hash)
        serial_number = _build_serial_number(scan, content_hash)

        # 4. Build the BOM root component (the analyzed
        # subject). The root component has no declared
        # dependencies in the BOM; that is honest. The
        # library will still emit a ``Dependency`` entry for
        # the root when it runs ``Bom.validate()`` and will
        # print a UserWarning if the root is missing from
        # the graph. We do not invent edges to silence that
        # warning.
        root_bom_ref = f"lockverity:scan-{scan.id}"
        root_component = CdxComponent(
            name=root_bom_ref,
            type=ComponentType.APPLICATION,
            bom_ref=root_bom_ref,
        )
        if scan.resolved_commit_sha:
            # CycloneDX 1.7 supports ``externalReference`` for
            # the VCS reference; we surface the commit through
            # a property too because the consumer's tooling
            # may not all parse ``externalReferences``
            # consistently.
            root_component.description = f"resolved commit {scan.resolved_commit_sha}"
            root_props: dict[str, str] = {
                "lockverity:resolved-commit-sha": scan.resolved_commit_sha,
            }
        else:
            root_props = {}
        root_props["lockverity:scan-id"] = str(scan.id)
        root_props["lockverity:scan-status"] = scan.status.value
        root_props["lockverity:repository-id"] = str(scan.repository_id)
        self._attach_properties(root_component, root_props)

        # 5. Tool block. CycloneDX 1.5+ models tools as
        # ``Component`` entries in a ``ToolRepository``. The
        # legacy ``tools`` field is deprecated in 1.5+ and is
        # not emitted here; the canonical 1.7 representation
        # is the only one in the BOM. We declare exactly one
        # tool component: Lockverity at the running
        # application version. A test asserts there is no
        # duplicate.
        tool_component = CdxComponent(
            name="lockverity",
            type=ComponentType.APPLICATION,
            bom_ref=f"lockverity:tool:{self._app_version}",
        )
        tool_component.publisher = "Lockverity"
        tool_component.version = self._app_version
        tool_repo = ToolRepository(components=(tool_component,))

        metadata = BomMetaData()
        metadata.component = root_component
        # The library's ``tools`` setter detects the existing
        # ``ToolRepository`` instance and skips the deprecated
        # ``ToolRepository(tools=...)`` constructor that would
        # add a legacy ``tools`` field to the serialised BOM.
        metadata.tools = tool_repo

        # 6. The metadata timestamp is the scan's persisted
        # completion timestamp. For partial scans that never
        # completed, we fall back to the ``updated_at`` of
        # the scan row. The current wall-clock time is never
        # used; doing so would defeat determinism. The
        # library requires a timezone-aware ``datetime``
        # instance.
        from datetime import datetime as _dt

        def _as_aware_utc(value: Any) -> _dt | None:
            if value is None:
                return None
            if not isinstance(value, _dt):
                return None
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)

        metadata.timestamp = _as_aware_utc(scan.completed_at) or _as_aware_utc(
            getattr(scan, "updated_at", None)
        )

        bom = Bom(serial_number=uuid.UUID(serial_number))
        bom.metadata = metadata
        for cdx in bom_components:
            bom.components.add(cdx)
        for dep in bom_dependencies:
            bom.dependencies.add(dep)

        # 7. Top-level properties. These are the
        # ``lockverity:``-namespaced coverage markers the
        # consumer can use to surface evidence limitations.
        graph_coverage = _dependency_graph_coverage(manifests, edges)
        top_properties: list[tuple[str, str]] = [
            ("lockverity:scan-id", str(scan.id)),
            ("lockverity:scan-status", scan.status.value),
            ("lockverity:repository-id", str(scan.repository_id)),
            ("lockverity:source-kind", "scan"),
            ("lockverity:inventory-coverage", "complete" if components else "empty"),
            ("lockverity:dependency-graph-coverage", graph_coverage),
            (
                "lockverity:provider-coverage",
                eligibility.provider_coverage,
            ),
        ]
        if "provider_degraded" in eligibility.limitations:
            top_properties.append(("lockverity:partial-reason", "provider_degradation"))
        if "provider_omitted_by_operator" in eligibility.limitations:
            top_properties.append(("lockverity:provider-omission-reason", "disabled_by_operator"))

        # 8. Render and validate. The library is happy to
        # serialise the BOM before we have attached our
        # top-level properties, so we attach them via a
        # small post-process step on the JSON document. The
        # post-process is a single deterministic pass.
        #
        # The library emits a model-level ``UserWarning``
        # ("The Component this BOM is describing ... has no
        # defined dependencies ... Dependency Graph is
        # incomplete ...") during ``output_as_string()``
        # when the metadata root has no declared
        # dependencies. The v0.6 evidence-honesty contract
        # intentionally does not invent root dependencies,
        # so the warning is expected. The warning is
        # suppressed *only* for this specific call, in this
        # specific module, and for the exact message; the
        # filter is scoped (not global) and does not
        # suppress unrelated ``UserWarning`` instances.
        # The authoritative check is the official
        # ``JsonStrictValidator(SchemaVersion.V1_7)`` call
        # below, which runs without a warning filter and
        # uses the bundled JSON schema (no network access).
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                category=UserWarning,
                module=r"cyclonedx\.model\.bom",
                message=r".*Dependency Graph is incomplete.*",
            )
            json_text = JsonV1Dot7(bom=bom).output_as_string()
        json_text = self._inject_top_level_properties(json_text, top_properties)

        # 9. Strict validation against the official CycloneDX
        # 1.7 JSON schema. The library bundles the schema and
        # uses the pinned ``jsonschema`` dependency; no
        # network access occurs. ``JsonStrictValidator.validate_str``
        # returns ``None`` for "no errors" and an iterable
        # of validation issues otherwise.
        validator = JsonStrictValidator(SchemaVersion.V1_7)
        result = validator.validate_str(json_text)
        if result:
            issues = list(result)
            raise _ValidationFailedError(
                f"CycloneDX 1.7 schema validation reported {len(issues)} error(s)."
            )
        return json_text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_licence_findings(self, session: Session, scan_run_id: int) -> list[Finding]:
        stmt = (
            session.query(Finding)
            .filter(
                Finding.scan_run_id == scan_run_id,
                Finding.category == FindingCategory.LICENCE,
            )
            .order_by(Finding.id.asc())
        )
        return list(stmt.all())

    def _build_component_properties(
        self, component: Component, manifest_by_id: dict[int, Manifest]
    ) -> dict[str, str]:
        properties: dict[str, str] = {
            "lockverity:component-id": str(component.id),
        }
        if component.manifest_id and component.manifest_id in manifest_by_id:
            manifest = manifest_by_id[component.manifest_id]
            properties["lockverity:manifest-id"] = str(manifest.id)
            properties["lockverity:manifest-path"] = manifest.path
        if component.version_source is not None:
            properties["lockverity:version-source"] = component.version_source.value
        return properties

    def _attach_properties(self, cdx: Any, properties: dict[str, str]) -> None:
        if not properties:
            return
        from cyclonedx.model import Property as CdxProperty

        existing = {p.name for p in getattr(cdx, "properties", []) or []}
        for name, value in sorted(properties.items()):
            if name in existing:
                continue
            cdx.properties.add(CdxProperty(name=name, value=value))

    def _build_dependencies(
        self, component_id_to_ref: dict[int, str], edges: list[Any]
    ) -> list[Any]:
        """Return the dependency graph as a list of ``Dependency`` entries.

        Only components with at least one observed outgoing
        edge are emitted. A component that is the parent of a
        persisted ``DependencyEdge`` row gets a ``Dependency``
        entry whose ``dependsOn`` list is the sorted set of
        observed child bom-refs. Components without any
        observed outgoing edge are NOT emitted; the absence
        from the ``dependencies`` block is the honest
        "unknown" signal, not a fabricated "has no
        dependencies" claim.

        The library's ``Bom.validate()`` will auto-add empty
        ``Dependency`` entries for every component (including
        the metadata root) during JSON serialisation. Those
        empty entries are filtered out in the post-processing
        step so the final BOM only carries the observed
        relationships.
        """
        from cyclonedx.model.bom_ref import BomRef
        from cyclonedx.model.dependency import Dependency

        def _ref(value: str) -> BomRef:
            return BomRef(value=value)

        def _dep(ref: str) -> Dependency:
            # Children are emitted as Dependency objects with
            # no further sub-dependencies. The library only
            # exposes dependencies at one level deep via
            # ``dependsOn``; deeper recursion is emitted in
            # its own entry.
            return Dependency(ref=_ref(ref))

        children_by_parent: dict[str, set[str]] = {}
        for edge in edges:
            parent_ref = component_id_to_ref.get(edge.parent_component_id)
            child_ref = component_id_to_ref.get(edge.child_component_id)
            if parent_ref is None or child_ref is None:
                continue
            children_by_parent.setdefault(parent_ref, set()).add(child_ref)
        out: list[Any] = []
        # Only emit entries for components with at least one
        # observed edge. A component that is the child of an
        # edge but never the parent is also omitted: the
        # consumer cannot infer its outgoing edges from a
        # single observed incoming edge.
        for ref in sorted(children_by_parent):
            children = sorted(children_by_parent[ref])
            out.append(Dependency(ref=_ref(ref), dependencies=[_dep(c) for c in children]))
        return out

    def _inject_top_level_properties(
        self, json_text: str, properties: list[tuple[str, str]]
    ) -> str:
        """Insert the top-level Lockverity properties and filter empty dependencies.

        Two deterministic post-processing steps:

        1. **Filter empty dependency entries.** The
           ``cyclonedx-python-lib`` library calls
           ``Bom.validate()`` during serialisation, which
           auto-adds an empty ``Dependency`` entry for every
           component (root + inventory) and emits a
           ``UserWarning`` when the metadata root has no
           declared dependencies. Those empty entries are the
           library's convenience; the v0.6 evidence-honesty
           contract does not interpret absence as "has no
           dependencies" and does not fabricate edges to
           silence the warning. We filter the JSON to keep
           only entries that carry at least one observed
           ``dependsOn`` child. The result is a BOM whose
           ``dependencies`` block contains only relationships
           supported by persisted ``DependencyEdge`` rows.
        2. **Inject coverage properties.** The library
           serialises the BOM without our ``lockverity:``-
           namespaced coverage markers. We re-parse the JSON,
           insert the ``properties`` block under
           ``metadata.properties`` in deterministic order, and
           re-serialise. The combined post-processing is a
           single deterministic, schema-valid transformation.
        """
        document = json.loads(json_text)

        # Step 1: filter the dependencies block. The
        # library's auto-added entries have no ``dependsOn``
        # key (or an empty list); they are removed here so
        # the final BOM only carries observed relationships.
        deps = document.get("dependencies", [])
        if isinstance(deps, list):
            filtered: list[dict[str, Any]] = []
            for dep in deps:
                if not isinstance(dep, dict):
                    continue
                depends_on = dep.get("dependsOn")
                if isinstance(depends_on, list) and len(depends_on) > 0:
                    filtered.append(dep)
            # Sort for determinism. The library emits the
            # entries in a stable order; we re-sort to be
            # defensive against future library changes.
            filtered.sort(key=lambda item: item.get("ref", ""))
            document["dependencies"] = filtered

        # Step 2: inject the coverage properties.
        metadata = document.setdefault("metadata", {})
        existing = list(metadata.get("properties", []))
        existing_names = {item.get("name") for item in existing}
        for name, value in properties:
            if name in existing_names:
                continue
            existing.append({"name": name, "value": value})
            existing_names.add(name)
        existing.sort(key=lambda item: item.get("name", ""))
        metadata["properties"] = existing
        # Re-serialise with the library's preferred ordering:
        # the library sorts keys when ``output_as_string`` is
        # called with ``indent=False``, but we keep the JSON
        # document deterministic and compact.
        return json.dumps(document, sort_keys=True, separators=(",", ":"))

    def _unavailable(self, *, code: str, summary: str) -> ProviderUnavailable:
        # The internal message is for operator logs only. The
        # API layer never returns it to the consumer; it uses
        # the bounded summary instead.
        return ProviderUnavailable(
            error_code=code,
            error_summary=summary,
            attempted_at=utcnow(),
            outcome=ProviderOutcome.UNAVAILABLE,
        )


class _ExporterError(Exception):
    code: str = "export_failed"
    summary: str = "Export failed."

    def __init__(self, summary: str | None = None, code: str | None = None) -> None:
        if code:
            self.code = code
        if summary:
            self.summary = summary
        super().__init__(summary or self.summary)


class _ValidationFailedError(_ExporterError):
    code = "cyclonedx_validation_failed"
    summary = "CycloneDX 1.7 validation failed."


__all__ = [
    "CYCLONEDX_FORMAT_KEY",
    "CYCLONEDX_MEDIA_TYPE",
    "CYCLONEDX_SCHEMA_URI",
    "CYCLONEDX_SPEC_VERSION",
    "CycloneDxV17Exporter",
    "build_cyclonedx_v17_preview",
]


# Type hint to keep the optional ``Repository`` import (used in
# future enhancements) referenced. Suppress unused-import
# warnings because the import is referenced through a dummy
# assignment to keep static analysers happy without making the
# public API depend on it.
_ = Repository
