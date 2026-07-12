"""Manifest discovery analyzer.

This analyzer implements the :class:`StaticAnalyzer` protocol.
It walks the input file list, picks out manifests of known
ecosystems, and returns an :class:`AnalyzerResult` whose
``findings`` is empty (manifest discovery is a data-collection
stage, not a finding stage) and whose ``warnings`` enumerate
deliberately skipped files.

The analyzer is intentionally conservative:

- It does not parse manifest content; that is the orchestrator's
  job.
- It does not flag missing-lockfile observations; the rules in
  :mod:`app.rules.vulnerability` own that rule.
- It re-uses :func:`app.utils.manifest_scanner.discover_manifests`
  so the same limits and ordering apply here and in the
  orchestrator.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.providers.results import (
    AnalyzerResult,
    FindingEvidence,
    ParserWarning,
)
from app.utils.finding_keys import stable_finding_key
from app.utils.manifest_scanner import (
    DEFAULT_MAX_MANIFEST_BYTES,
    DEFAULT_MAX_MANIFEST_COUNT,
    DiscoveryResult,
    SkippedManifest,
    discover_manifests,
)


def _skipped_evidence(skipped: SkippedManifest) -> dict[str, Any]:
    return {
        "path": skipped.path,
        "reason": skipped.reason.value,
        "detail": skipped.detail,
    }


def _skipped_finding(skipped: SkippedManifest, *, scan_run_id: int) -> FindingEvidence:
    return FindingEvidence(
        rule_id="LOCK-DATA-001",
        location_path=skipped.path,
        location_start_line=None,
        location_end_line=None,
        raw=_skipped_evidence(skipped),
    )


class ManifestDiscoveryAnalyzer:
    """Static analyzer that discovers manifests in a file list."""

    name = "manifest_discovery"

    def __init__(
        self,
        *,
        max_manifest_bytes: int = DEFAULT_MAX_MANIFEST_BYTES,
        max_manifest_count: int = DEFAULT_MAX_MANIFEST_COUNT,
    ) -> None:
        self._max_manifest_bytes = max_manifest_bytes
        self._max_manifest_count = max_manifest_count

    def discover(
        self,
        files: Iterable[tuple[str, bytes]],
    ) -> DiscoveryResult:
        return discover_manifests(
            files,
            max_manifest_bytes=self._max_manifest_bytes,
            max_manifest_count=self._max_manifest_count,
        )

    def analyze(
        self,
        *,
        files: list[tuple[str, bytes]],
        scan_run_id: int,
    ) -> AnalyzerResult:
        result = self.discover(files)
        findings: list[FindingEvidence] = []
        for skipped in result.skipped:
            if skipped.reason.value in {"ignored_directory", "unknown_manifest"}:
                # We do not surface ignored directories or unknown
                # files as findings - they would just be noise.
                continue
            evidence = _skipped_evidence(skipped)
            stable_key = stable_finding_key(
                "LOCK-DATA-001",
                {"path": skipped.path, "reason": skipped.reason.value, "detail": skipped.detail},
            )
            evidence["stable_key"] = stable_key
            evidence["scan_run_id"] = scan_run_id
            findings.append(
                FindingEvidence(
                    rule_id="LOCK-DATA-001",
                    location_path=skipped.path,
                    location_start_line=None,
                    location_end_line=None,
                    raw=evidence,
                )
            )
        warnings: list[ParserWarning] = []
        for skipped in result.skipped:
            if skipped.detail is not None:
                warnings.append(
                    ParserWarning(
                        code=f"manifest_skipped_{skipped.reason.value}",
                        message=skipped.detail,
                        location=skipped.path,
                    )
                )
            else:
                warnings.append(
                    ParserWarning(
                        code=f"manifest_skipped_{skipped.reason.value}",
                        message=skipped.reason.value,
                        location=skipped.path,
                    )
                )
        return AnalyzerResult(
            findings=tuple(findings),
            warnings=tuple(warnings),
        )
