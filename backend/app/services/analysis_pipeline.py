"""The per-scan analysis pipeline.

The :class:`AnalysisPipeline` does the real analysis work that
the orchestrator used to record as ``not_requested`` in v0.2. It
is invoked from :class:`app.services.orchestrator_service.ScanOrchestrator`
once the local stages (intake, archive validation, manifest
discovery) are complete.

The pipeline is intentionally split from the orchestrator:

- The orchestrator owns the *state machine* (queued -> running ->
  completed / partial / failed / cancelled) and the cross-cutting
  concerns (provider observations, cancellation, failure
  recording).
- This module owns the *work*: parsing manifests, building
  components and edges, running analyzers, evaluating rules,
  persisting findings. It is the only place that turns raw
  evidence into the :class:`Finding` rows the API serves.

The pipeline degrades gracefully: any network-dependent stage
(OSV, deps.dev, Scorecard) records its failure as a
:class:`ProviderObservation` with status ``unavailable``. Local
work (parsers, manifest discovery, GitHub Actions rules, finding
reconciliation) always runs to completion; it never makes
network calls.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.analyzers.dependency_graph import build_dependency_components
from app.analyzers.github_actions import GitHubActionsAnalyzer
from app.models.component import Component
from app.models.dependency_edge import DependencyEdge
from app.models.finding import FindingCategory
from app.models.manifest import Manifest, ManifestParseStatus
from app.models.provider_observation import ProviderObservation, ProviderStatus
from app.models.scan_run import ScanRun
from app.parsers import get_registry
from app.providers.results import (
    AnalyzerResult,
    FindingEvidence,
    ParserResult,
    ParserWarning,
)
from app.rules import default_rules
from app.services import write_service
from app.services.workspace_service import WorkspaceService
from app.utils.errors import ApiError, ApiErrorCode
from app.utils.redaction import redact_provider_summary

logger = logging.getLogger("lockverity.analysis")

# Stages implemented in this module. Kept in module scope so a
# test can stub a single method without touching the orchestrator.
MAX_COMPONENT_BYTES = 5_000_000  # 5 MiB cap per file (defensive)
MAX_TOTAL_BYTES = 50_000_000  # 50 MiB cap per scan (defensive)


@dataclass(frozen=True, slots=True)
class StageOutcome:
    """The summary a pipeline stage returns to the orchestrator."""

    stage: str
    status: str  # "completed" | "partial" | "failed" | "skipped"
    records_processed: int
    failure_code: str | None = None
    failure_summary: str | None = None


@dataclass(frozen=True, slots=True)
class PipelineSummary:
    """The full result of running the analysis pipeline."""

    stages: tuple[StageOutcome, ...]
    components_persisted: int
    edges_persisted: int
    findings_persisted: int
    findings_skipped: int
    component_advisories_persisted: int


class AnalysisPipeline:
    """Drives one scan through dependency parsing, analysis, and rules."""

    def __init__(
        self,
        *,
        session_factory,
        settings,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    def run(self, scan_id: int) -> PipelineSummary:
        """Run the full analysis pipeline against an already-queued scan.

        The pipeline is robust against missing artefacts: if a
        workspace is not ``ready`` or has no manifests, the
        corresponding stages are recorded as ``skipped`` and the
        pipeline still finalizes the scan.
        """
        stages: list[StageOutcome] = []
        components_persisted = 0
        edges_persisted = 0
        findings_persisted = 0
        findings_skipped = 0
        component_advisories_persisted = 0

        # --- dependency_parsing -----------------------------------------
        (
            outcome,
            components_persisted,
            edges_persisted,
        ) = self._stage_dependency_parsing(scan_id)
        stages.append(outcome)

        # --- vulnerability_query (local, no network in v0.3) ------------
        # The v0.3 pipeline never makes a network call. The stage
        # produces a ProviderObservation so the UI can render the
        # honest "not requested" / "unavailable" baseline. When a
        # later milestone wires up a real provider, the stage body
        # becomes the only place that needs to change.
        outcome = self._stage_vulnerability_query(scan_id)
        stages.append(outcome)

        # --- workflow_analysis ------------------------------------------
        outcome, findings_persisted, findings_skipped = self._stage_workflow_analysis(scan_id)
        stages.append(outcome)

        # --- repository_posture (placeholder) ----------------------------
        outcome = self._stage_repository_posture(scan_id)
        stages.append(outcome)

        # --- finding_reconciliation -------------------------------------
        outcome, more_persisted, more_skipped, more_advisories = self._stage_finding_reconciliation(
            scan_id
        )
        stages.append(outcome)
        findings_persisted += more_persisted
        findings_skipped += more_skipped
        component_advisories_persisted += more_advisories

        return PipelineSummary(
            stages=tuple(stages),
            components_persisted=components_persisted,
            edges_persisted=edges_persisted,
            findings_persisted=findings_persisted,
            findings_skipped=findings_skipped,
            component_advisories_persisted=component_advisories_persisted,
        )

    # ------------------------------------------------------------------
    # Stages
    # ------------------------------------------------------------------
    def _stage_dependency_parsing(self, scan_id: int) -> tuple[StageOutcome, int, int]:
        """Parse every discovered manifest, build components and edges.

        This stage is purely local. It does not call any provider.
        A failure here is recorded as ``failed`` and the
        orchestrator short-circuits the rest of the pipeline.
        """
        files = self._collect_workspace_files(scan_id)
        if not files:
            return (
                StageOutcome(
                    stage="dependency_parsing",
                    status="skipped",
                    records_processed=0,
                    failure_summary="No files were available in the workspace.",
                ),
                0,
                0,
            )
        registry = get_registry()
        envelopes: list[dict[str, Any]] = []
        manifests_by_path: dict[str, dict[str, Any]] = {}
        total_warnings = 0
        with self._session_factory() as session:
            scan = _get_scan_or_404(session, scan_id)
            manifests = session.query(Manifest).filter(Manifest.scan_run_id == scan.id).all()
            for manifest in manifests:
                if manifest.parse_status == ManifestParseStatus.PARSED:
                    continue
                content = self._read_manifest_bytes(scan_id, manifest.path)
                if content is None:
                    continue
                registration = registry.get(manifest.manifest_type)
                if registration is None:
                    # No parser registered for this manifest
                    # type. Mark as ``partial`` so the UI can
                    # show the manifest as acknowledged but not
                    # parsed; a per-manifest ``SKIPPED`` status
                    # does not exist in the enum.
                    write_service.update_manifest_parse_status(
                        session,
                        manifest_id=manifest.id,
                        status=ManifestParseStatus.PARTIAL,
                    )
                    continue
                try:
                    result: ParserResult[list[dict[str, Any]]] = registration.parser.parse(
                        content=content, path=manifest.path
                    )
                except Exception as exc:
                    logger.warning(
                        "manifest parse failed scan=%s path=%s: %s",
                        scan_id,
                        manifest.path,
                        exc,
                    )
                    write_service.update_manifest_parse_status(
                        session,
                        manifest_id=manifest.id,
                        status=ManifestParseStatus.FAILED,
                    )
                    session.add(
                        ProviderObservation(
                            scan_run_id=scan_id,
                            provider=manifest.manifest_type,
                            operation="parse_manifest",
                            status=ProviderStatus.UNAVAILABLE,
                            records_returned=0,
                            cache_status="miss",
                            error_code="manifest_parse_failed",
                            error_summary=redact_provider_summary(str(exc)),
                        )
                    )
                    total_warnings += 1
                    continue
                sha = hashlib.sha256(content).hexdigest()
                write_service.update_manifest_parse_status(
                    session,
                    manifest_id=manifest.id,
                    status=ManifestParseStatus.PARSED,
                    content_sha256=sha,
                    parse_warning_count=len(result.warnings),
                )
                envelopes.append(
                    {
                        "manifest": {
                            "id": manifest.id,
                            "path": manifest.path,
                            "manifest_type": manifest.manifest_type,
                            "ecosystem": manifest.ecosystem,
                        },
                        "records": list(result.data),
                    }
                )
                manifests_by_path[manifest.path] = {
                    "manifest_id": manifest.id,
                    "manifest_type": manifest.manifest_type,
                    "ecosystem": manifest.ecosystem,
                }
                total_warnings += len(result.warnings)
                for warning in result.warnings:
                    if not isinstance(warning, ParserWarning):
                        continue
                    session.add(
                        ProviderObservation(
                            scan_run_id=scan_id,
                            provider=manifest.manifest_type,
                            operation="parse_manifest",
                            status=ProviderStatus.PARTIAL,
                            records_returned=0,
                            cache_status="miss",
                            error_code=warning.code,
                            error_summary=redact_provider_summary(warning.message),
                        )
                    )
            try:
                components, edges, graph_findings = build_dependency_components(
                    envelopes,
                    manifests_by_path=manifests_by_path,
                )
            except Exception as exc:
                session.commit()
                logger.exception("dependency graph build failed for scan %s", scan_id)
                return (
                    StageOutcome(
                        stage="dependency_parsing",
                        status="failed",
                        records_processed=0,
                        failure_code="dependency_graph_failed",
                        failure_summary=str(exc)[:512],
                    ),
                    0,
                    0,
                )
            # Stitch the manifest_id onto each component record
            # using the envelope. The dependency-graph analyzer
            # returns components keyed by package_name without
            # the foreign-key reference, so we back-fill it here
            # rather than mutating the analyzer.
            envelope_by_path = {e["manifest"]["path"]: e["manifest"] for e in envelopes}
            for component in components:
                path = component.get("manifest_path")
                envelope = envelope_by_path.get(path) if path else None
                if envelope is not None:
                    component["manifest_id"] = envelope["id"]
            # Persist components.
            component_ids: list[int] = []
            if components:
                component_ids = write_service.upsert_components(
                    session, scan_run_id=scan_id, records=components
                )
            # Persist edges.
            edges_persisted = 0
            if edges:
                edges_persisted = write_service.upsert_dependency_edges(
                    session, scan_run_id=scan_id, edges=edges
                )
            # The graph analyzer also emits its own LOCK-VULN-*
            # findings (e.g. missing lockfile). Persist them too.
            _more_persisted, _more_skipped = 0, 0
            if graph_findings:
                _more_persisted, _more_skipped = write_service.upsert_findings(
                    session,
                    scan_run_id=scan_id,
                    repository_id=scan.repository_id,
                    records=graph_findings,
                    default_category="vulnerability",
                )
            session.add(
                ProviderObservation(
                    scan_run_id=scan_id,
                    provider="dependency_parsing",
                    operation="build_graph",
                    status=ProviderStatus.AVAILABLE,
                    records_returned=len(component_ids),
                    cache_status="miss",
                    error_code=None,
                    error_summary=None,
                )
            )
            session.commit()
            # ``components`` is unused in the return value but
            # reading it once forces evaluation in case we want
            # to log it later. Keep the explicit name binding.
            _ = components
            return (
                StageOutcome(
                    stage="dependency_parsing",
                    status="completed",
                    records_processed=len(component_ids),
                    failure_summary=(
                        f"{total_warnings} parser warnings" if total_warnings else None
                    ),
                ),
                len(component_ids),
                edges_persisted,
            )

    def _stage_vulnerability_query(self, scan_id: int) -> StageOutcome:
        """Record the per-scan vulnerability provider observation.

        v0.3 does not call OSV. We persist an honest
        ``not_requested`` observation so the dashboard can render
        the truthful baseline. A later milestone wires OSV in
        behind the same observation contract.
        """
        with self._session_factory() as session:
            scan = _get_scan_or_404(session, scan_id)
            components = session.query(Component).filter(Component.scan_run_id == scan.id).count()
            session.add(
                ProviderObservation(
                    scan_run_id=scan_id,
                    provider="osv",
                    operation="vulnerability_query",
                    status=ProviderStatus.NOT_REQUESTED,
                    records_returned=0,
                    cache_status="miss",
                    error_code="provider_not_requested",
                    error_summary="OSV integration is not enabled in v0.3.",
                )
            )
            session.commit()
            return StageOutcome(
                stage="vulnerability_query",
                status="skipped",
                records_processed=components,
                failure_summary="OSV provider is not enabled in v0.3.",
            )

    def _stage_workflow_analysis(self, scan_id: int) -> tuple[StageOutcome, int, int]:
        """Run the GitHub Actions analyzer and persist its findings."""
        with self._session_factory() as session:
            scan = _get_scan_or_404(session, scan_id)
            files = self._collect_workspace_files(scan_id)
            workflow_files = [
                (path, content) for path, content in files if path.startswith(".github/workflows/")
            ]
            logger.info(
                "workflow analysis: %d files, %d workflow files",
                len(files),
                len(workflow_files),
            )
            if not workflow_files:
                session.add(
                    ProviderObservation(
                        scan_run_id=scan_id,
                        provider="github_actions",
                        operation="analyze_workflows",
                        status=ProviderStatus.NOT_REQUESTED,
                        records_returned=0,
                        cache_status="miss",
                        error_code="no_workflow_files",
                        error_summary="No workflow files were discovered.",
                    )
                )
                session.commit()
                return (
                    StageOutcome(
                        stage="workflow_analysis",
                        status="skipped",
                        records_processed=0,
                        failure_summary="No workflow files were discovered.",
                    ),
                    0,
                    0,
                )
            analyzer = GitHubActionsAnalyzer()
            try:
                result: AnalyzerResult = analyzer.analyze(files=workflow_files, scan_run_id=scan_id)
            except Exception as exc:
                logger.exception("workflow analyzer failed for scan %s", scan_id)
                session.add(
                    ProviderObservation(
                        scan_run_id=scan_id,
                        provider="github_actions",
                        operation="analyze_workflows",
                        status=ProviderStatus.UNAVAILABLE,
                        records_returned=0,
                        cache_status="miss",
                        error_code="workflow_analyzer_internal_error",
                        error_summary=redact_provider_summary(str(exc)),
                    )
                )
                session.commit()
                return (
                    StageOutcome(
                        stage="workflow_analysis",
                        status="failed",
                        records_processed=0,
                        failure_code="workflow_analyzer_internal_error",
                        failure_summary=str(exc)[:512],
                    ),
                    0,
                    0,
                )
            logger.info(
                "workflow analysis: analyzer produced %d findings",
                len(result.findings),
            )
            persisted, skipped = write_service.upsert_findings(
                session,
                scan_run_id=scan_id,
                repository_id=scan.repository_id,
                records=result.findings,
                default_category="workflow",
            )
            logger.info(
                "workflow analysis: persisted=%d skipped=%d",
                persisted,
                skipped,
            )
            for warning in result.warnings:
                session.add(
                    ProviderObservation(
                        scan_run_id=scan_id,
                        provider="github_actions",
                        operation="analyze_workflows",
                        status=ProviderStatus.PARTIAL,
                        records_returned=0,
                        cache_status="miss",
                        error_code=warning.code,
                        error_summary=redact_provider_summary(warning.message),
                    )
                )
            session.add(
                ProviderObservation(
                    scan_run_id=scan_id,
                    provider="github_actions",
                    operation="analyze_workflows",
                    status=ProviderStatus.AVAILABLE,
                    records_returned=len(workflow_files),
                    cache_status="miss",
                    error_code=None,
                    error_summary=None,
                )
            )
            session.commit()
            return (
                StageOutcome(
                    stage="workflow_analysis",
                    status="completed",
                    records_processed=len(workflow_files),
                ),
                persisted,
                skipped,
            )

    def _stage_repository_posture(self, scan_id: int) -> StageOutcome:
        """Record the OpenSSF Scorecard baseline observation.

        v0.3 records an honest ``not_requested`` observation; the
        data shape is reserved so a later milestone can swap in
        a real Scorecard client without changing the contract.
        """
        with self._session_factory() as session:
            session.add(
                ProviderObservation(
                    scan_run_id=scan_id,
                    provider="openssf",
                    operation="scorecard",
                    status=ProviderStatus.NOT_REQUESTED,
                    records_returned=0,
                    cache_status="miss",
                    error_code="provider_not_requested",
                    error_summary="OpenSSF Scorecard integration is not enabled in v0.3.",
                )
            )
            session.commit()
            return StageOutcome(
                stage="repository_posture",
                status="skipped",
                records_processed=0,
                failure_summary="OpenSSF Scorecard is not enabled in v0.3.",
            )

    def _stage_finding_reconciliation(self, scan_id: int) -> tuple[StageOutcome, int, int, int]:
        """Run the rule engine over the per-component evidence and persist findings."""
        with self._session_factory() as session:
            scan = _get_scan_or_404(session, scan_id)
            components = session.query(Component).filter(Component.scan_run_id == scan.id).all()
            edges = (
                session.query(DependencyEdge).filter(DependencyEdge.scan_run_id == scan.id).all()
            )
            child_to_parents: dict[int, list[DependencyEdge]] = {}
            for edge in edges:
                child_to_parents.setdefault(edge.child_component_id, []).append(edge)

            observations = (
                session.query(ProviderObservation)
                .filter(ProviderObservation.scan_run_id == scan.id)
                .all()
            )
            rules = default_rules()
            all_evidence: list[FindingEvidence] = []
            for component in components:
                evidence = _build_evidence_envelope(
                    component=component,
                    edges=child_to_parents.get(component.id, []),
                    observations=observations,
                )
                for rule in rules:
                    if rule.category == FindingCategory.WORKFLOW.value:
                        # Workflow findings are produced by the
                        # GitHub Actions analyzer, not the
                        # dependency rule engine.
                        continue
                    try:
                        produced = rule.evaluate(
                            evidence=evidence,
                            scan_run_id=scan_id,
                            repository_id=scan.repository_id,
                        )
                    except Exception as exc:
                        logger.warning(
                            "rule %s raised on scan %s: %s",
                            rule.rule_id,
                            scan_id,
                            exc,
                        )
                        continue
                    all_evidence.extend(produced)
            persisted, skipped = write_service.upsert_findings(
                session,
                scan_run_id=scan_id,
                repository_id=scan.repository_id,
                records=all_evidence,
                default_category="vulnerability",
            )
            session.add(
                ProviderObservation(
                    scan_run_id=scan_id,
                    provider="rule_engine",
                    operation="finding_reconciliation",
                    status=ProviderStatus.AVAILABLE,
                    records_returned=len(components),
                    cache_status="miss",
                    error_code=None,
                    error_summary=None,
                )
            )
            session.commit()
            return (
                StageOutcome(
                    stage="finding_reconciliation",
                    status="completed",
                    records_processed=len(components),
                ),
                persisted,
                skipped,
                0,  # component_advisories_persisted (v0.3 keeps it 0)
            )

    # ------------------------------------------------------------------
    # Workspace helpers
    # ------------------------------------------------------------------
    def _collect_workspace_files(self, scan_id: int) -> list[tuple[str, bytes]]:
        """Read every small file under the workspace contents dir.

        Files are bounded defensively. The orchestrator never
        executes any of these files; it only reads their bytes.
        """
        with self._session_factory() as session:
            scan = _get_scan_or_404(session, scan_id)
            workspaces = WorkspaceService(session, settings=self._settings)
            try:
                workspace = workspaces.get_for_scan(scan.id)
            except ApiError:
                return []
            paths = workspaces.paths_for(workspace.workspace_key)
            contents_dir = paths.contents_dir
            if not contents_dir.exists() or not contents_dir.is_dir():
                return []
            files: list[tuple[str, bytes]] = []
            total = 0
            for child in sorted(contents_dir.rglob("*")):
                if not child.is_file():
                    continue
                size = child.stat().st_size
                if size > MAX_COMPONENT_BYTES:
                    continue
                if total + size > MAX_TOTAL_BYTES:
                    break
                rel = child.relative_to(contents_dir).as_posix()
                try:
                    content = child.read_bytes()
                except OSError:
                    continue
                total += size
                files.append((rel, content))
            return files

    def _read_manifest_bytes(self, scan_id: int, rel_path: str) -> bytes | None:
        for path, content in self._collect_workspace_files(scan_id):
            if path == rel_path:
                return content
        return None


def _build_evidence_envelope(
    *,
    component: Component,
    edges: Iterable[DependencyEdge],
    observations: Iterable[ProviderObservation],
) -> dict[str, Any]:
    """Assemble the per-component evidence envelope the rules consume."""
    edge_payloads = [
        {
            "parent_component_id": edge.parent_component_id,
            "child_component_id": edge.child_component_id,
            "relationship": edge.relationship,
            "depth": edge.depth,
        }
        for edge in edges
    ]
    observation_payloads = [
        {
            "provider": obs.provider,
            "operation": obs.operation,
            "status": obs.status.value if hasattr(obs.status, "value") else obs.status,
            "error_code": obs.error_code,
            "records_returned": obs.records_returned,
        }
        for obs in observations
    ]
    return {
        "component": {
            "id": component.id,
            "package_name": component.package_name,
            "version": component.version,
            "version_source": (
                component.version_source.value
                if hasattr(component.version_source, "value")
                else component.version_source
            ),
            "ecosystem": component.ecosystem,
            "scope": component.scope,
            "direct": component.direct,
            "development": component.development,
            "manifest_path": None,
        },
        "advisories": [],
        "dependency_paths": edge_payloads,
        "provider_observations": observation_payloads,
        "licence_assertions": [],
    }


def _get_scan_or_404(session: Session, scan_id: int) -> ScanRun:
    scan = session.get(ScanRun, scan_id)
    if scan is None:
        raise ApiError(
            ApiErrorCode.NOT_FOUND,
            "Scan not found.",
            details={"scan_id": scan_id},
        )
    return scan


__all__ = [
    "MAX_COMPONENT_BYTES",
    "MAX_TOTAL_BYTES",
    "AnalysisPipeline",
    "PipelineSummary",
    "StageOutcome",
]
