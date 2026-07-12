"""Licence inventory rules.

The licence rules consume per-component evidence assembled by
the orchestrator from deps.dev (or other providers). The shape
is the same envelope used by the vulnerability rules, plus a
``licence_assertions`` list and an optional ``policy`` field.

Lockverity never makes a *legal* conclusion. The rules surface
observations the user can act on; the legal interpretation is
out of scope.
"""

from __future__ import annotations

from typing import Any

from app.models.finding import FindingConfidence, FindingSeverity
from app.rules.base import BaseRule
from app.rules.vulnerability import REVIEW_REQUIRED_LICENCES


def _licence_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise ValueError("evidence must be a dict")
    return evidence


class LicenceUnknownRule(BaseRule):
    """A component has no licence assertion from any provider."""

    rule_id = "LOCK-LIC-001"
    category = "licence"
    severity = FindingSeverity.MEDIUM
    confidence = FindingConfidence.MEDIUM

    def evaluate(
        self,
        *,
        evidence: dict[str, Any],
        scan_run_id: int,
        repository_id: int,
    ) -> tuple:
        env = _licence_evidence(evidence)
        component = env.get("component")
        if not isinstance(component, dict):
            return ()
        licences = env.get("licence_assertions") or []
        if licences:
            return ()
        payload = {
            "package_name": component.get("package_name"),
            "version": component.get("version"),
            "ecosystem": component.get("ecosystem"),
        }
        yield self.build_finding(
            evidence_payload=payload,
            location_path=component.get("manifest_path"),
            title="Component has no licence assertion",
            summary=(
                f"Component {component.get('package_name')} has no licence assertion from "
                "any source consulted by this scan. The actual licence may be unknown, "
                "ambiguous, or simply not indexed by deps.dev."
            ),
            remediation=(
                "Inspect the upstream repository or distribution tarball for the licence "
                "and document it in the project's NOTICE / THIRD_PARTY_LICENSES file."
            ),
            limitations=(
                "Lockverity does not download the package's source; absence of an "
                "assertion is not the same as absence of a licence."
            ),
        )


class LicenceMultipleAssertionsRule(BaseRule):
    """Multiple providers disagree on the licence of the same component."""

    rule_id = "LOCK-LIC-002"
    category = "licence"
    severity = FindingSeverity.LOW
    confidence = FindingConfidence.MEDIUM

    def evaluate(
        self,
        *,
        evidence: dict[str, Any],
        scan_run_id: int,
        repository_id: int,
    ) -> tuple:
        env = _licence_evidence(evidence)
        component = env.get("component")
        if not isinstance(component, dict):
            return ()
        assertions = env.get("licence_assertions") or []
        if not isinstance(assertions, list):
            return ()
        unique = sorted({a for a in assertions if isinstance(a, str)})
        if len(unique) <= 1:
            return ()
        payload = {
            "package_name": component.get("package_name"),
            "version": component.get("version"),
            "assertions": unique,
        }
        yield self.build_finding(
            evidence_payload=payload,
            location_path=component.get("manifest_path"),
            title="Multiple licence assertions disagree",
            summary=(
                f"Component {component.get('package_name')} has multiple licence "
                f"assertions: {', '.join(unique)}."
            ),
            remediation=(
                "Inspect the upstream package metadata and pick the licence that the "
                "package author actually intends. Document the choice in the project's "
                "NOTICE file."
            ),
            limitations=(
                "Different providers may report the same licence under different SPDX "
                "identifiers (e.g. ``Apache-2.0`` vs ``Apache-2.0-only``); the rule "
                "does not normalise identifiers."
            ),
        )


class LicenceReviewRequiredRule(BaseRule):
    """A component's licence is on the review-required list."""

    rule_id = "LOCK-LIC-003"
    category = "licence"
    severity = FindingSeverity.MEDIUM
    confidence = FindingConfidence.MEDIUM

    def evaluate(
        self,
        *,
        evidence: dict[str, Any],
        scan_run_id: int,
        repository_id: int,
    ) -> tuple:
        env = _licence_evidence(evidence)
        component = env.get("component")
        if not isinstance(component, dict):
            return ()
        assertions = env.get("licence_assertions") or []
        if not isinstance(assertions, list):
            return ()
        matches = [a for a in assertions if isinstance(a, str) and a in REVIEW_REQUIRED_LICENCES]
        if not matches:
            return ()
        payload = {
            "package_name": component.get("package_name"),
            "version": component.get("version"),
            "licences": sorted(set(matches)),
        }
        yield self.build_finding(
            evidence_payload=payload,
            location_path=component.get("manifest_path"),
            title="Component has a review-required licence",
            summary=(
                f"Component {component.get('package_name')} is licensed under "
                f"{', '.join(sorted(set(matches)))}, which has distribution or commercial "
                "implications that warrant a human review."
            ),
            remediation=(
                "Route the dependency through the project's legal review. Replace it with "
                "an alternative licence if the project policy forbids review-required "
                "licences."
            ),
            limitations=(
                "Lockverity does not provide legal advice. The list of review-required "
                "licences is configurable in the rule; the default is conservative."
            ),
        )


class LicenceProviderUnavailableRule(BaseRule):
    """The licence provider was unavailable for at least one component."""

    rule_id = "LOCK-LIC-004"
    category = "licence"
    severity = FindingSeverity.LOW
    confidence = FindingConfidence.HIGH

    def evaluate(
        self,
        *,
        evidence: dict[str, Any],
        scan_run_id: int,
        repository_id: int,
    ) -> tuple:
        env = _licence_evidence(evidence)
        observations = env.get("provider_observations") or []
        if not isinstance(observations, list):
            return ()
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            if obs.get("status") != "unavailable":
                continue
            payload = {
                "provider": obs.get("provider"),
                "operation": obs.get("operation"),
                "error_summary": obs.get("error_summary"),
            }
            yield self.build_finding(
                evidence_payload=payload,
                location_path=None,
                title="Licence provider was unavailable",
                summary=(
                    f"Provider {obs.get('provider')} was unavailable; licence assertions "
                    "are incomplete for this scan."
                ),
                remediation=(
                    "Re-run the scan when the provider is available."
                ),
                limitations=(
                    "Lockverity does not report the licence inventory as 'clean' when the "
                    "licence provider was unavailable."
                ),
            )


class LicenceInventoryRule(BaseRule):
    """An informational record that a component's licence was inventoried.

    The rule fires once per component, with ``severity=informational``,
    to populate the licence inventory view in the UI. It is not a
    warning.
    """

    rule_id = "LOCK-LIC-INV"
    category = "licence"
    severity = FindingSeverity.INFORMATIONAL
    confidence = FindingConfidence.HIGH

    def evaluate(
        self,
        *,
        evidence: dict[str, Any],
        scan_run_id: int,
        repository_id: int,
    ) -> tuple:
        env = _licence_evidence(evidence)
        component = env.get("component")
        if not isinstance(component, dict):
            return ()
        payload = {
            "package_name": component.get("package_name"),
            "version": component.get("version"),
            "licences": sorted(set(env.get("licence_assertions") or [])),
        }
        yield self.build_finding(
            evidence_payload=payload,
            location_path=component.get("manifest_path"),
            title="Licence recorded",
            summary=(
                f"Component {component.get('package_name')} recorded licence "
                f"{', '.join(payload['licences']) or '<none>'}."
            ),
            limitations=(
                "The inventory is informational; the UI uses it to populate the licence "
                "list. No remediation is required."
            ),
        )
