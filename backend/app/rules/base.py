"""Rule base utilities.

Concrete rule classes implement the
:class:`app.providers.contracts.FindingRule` protocol. This
module provides a small base class and helpers that every rule
uses to build :class:`FindingEvidence` records with the right
``stable_key`` and consistent shape.
"""

from __future__ import annotations

from typing import Any

from app.models.finding import (
    FindingCategory,
    FindingConfidence,
    FindingSeverity,
)
from app.providers.contracts import FindingRule
from app.providers.results import FindingEvidence
from app.utils.finding_keys import stable_evidence_blob, stable_finding_key


class BaseRule:
    """Common base for finding-rule implementations.

    The protocol requires ``rule_id`` and ``category`` and an
    :meth:`evaluate` method. Subclasses set ``severity`` and
    ``confidence`` as class attributes and implement
    :meth:`evaluate`.
    """

    rule_id: str = ""
    category: str = ""
    severity: FindingSeverity = FindingSeverity.INFORMATIONAL
    confidence: FindingConfidence = FindingConfidence.MEDIUM

    def evaluate(
        self,
        *,
        evidence: dict[str, Any],
        scan_run_id: int,
        repository_id: int,
    ) -> tuple[FindingEvidence, ...]:
        raise NotImplementedError

    def build_finding(
        self,
        *,
        evidence_payload: dict[str, Any],
        location_path: str | None,
        location_start_line: int | None = None,
        location_end_line: int | None = None,
        title: str,
        summary: str,
        remediation: str | None = None,
        limitations: str | None = None,
        severity: FindingSeverity | None = None,
        confidence: FindingConfidence | None = None,
    ) -> FindingEvidence:
        raw: dict[str, Any] = {
            "title": title,
            "summary": summary,
            "remediation": remediation,
            "limitations": limitations,
            "evidence": evidence_payload,
        }
        if isinstance(severity, FindingSeverity):
            raw["severity"] = severity.value
        if isinstance(confidence, FindingConfidence):
            raw["confidence"] = confidence.value
        raw["stable_key"] = stable_finding_key(self.rule_id, evidence_payload)
        raw["evidence_json"] = stable_evidence_blob(evidence_payload)
        return FindingEvidence(
            rule_id=self.rule_id,
            location_path=location_path,
            location_start_line=location_start_line,
            location_end_line=location_end_line,
            raw=raw,
        )


__all__ = [
    "BaseRule",
    "FindingCategory",
    "FindingConfidence",
    "FindingRule",
    "FindingSeverity",
]
