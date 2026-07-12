"""Tests for the licence finding rules."""

from __future__ import annotations

from app.rules.licence import (
    LicenceInventoryRule,
    LicenceMultipleAssertionsRule,
    LicenceProviderUnavailableRule,
    LicenceReviewRequiredRule,
    LicenceUnknownRule,
)


def _evidence(component=None, licence_assertions=None, observations=None):
    return {
        "component": component
        or {"package_name": "lodash", "version": "4.17.0", "manifest_path": "package.json"},
        "licence_assertions": licence_assertions or [],
        "provider_observations": observations or [],
    }


def test_unknown_licence_fires_when_no_assertions() -> None:
    rule = LicenceUnknownRule()
    findings = list(
        rule.evaluate(evidence=_evidence(licence_assertions=[]), scan_run_id=1, repository_id=1)
    )
    assert len(findings) == 1
    assert findings[0].rule_id == "LOCK-LIC-001"


def test_unknown_licence_skips_when_assertions_present() -> None:
    rule = LicenceUnknownRule()
    findings = list(
        rule.evaluate(
            evidence=_evidence(licence_assertions=["MIT"]), scan_run_id=1, repository_id=1
        )
    )
    assert not findings


def test_multiple_licence_assertions_fire() -> None:
    rule = LicenceMultipleAssertionsRule()
    findings = list(
        rule.evaluate(
            evidence=_evidence(licence_assertions=["MIT", "Apache-2.0"]),
            scan_run_id=1,
            repository_id=1,
        )
    )
    assert len(findings) == 1
    assert findings[0].rule_id == "LOCK-LIC-002"


def test_multiple_licence_assertions_skip_for_single() -> None:
    rule = LicenceMultipleAssertionsRule()
    findings = list(
        rule.evaluate(
            evidence=_evidence(licence_assertions=["MIT"]), scan_run_id=1, repository_id=1
        )
    )
    assert not findings


def test_review_required_licence_fires() -> None:
    rule = LicenceReviewRequiredRule()
    findings = list(
        rule.evaluate(
            evidence=_evidence(licence_assertions=["AGPL-3.0"]),
            scan_run_id=1,
            repository_id=1,
        )
    )
    assert len(findings) == 1
    assert findings[0].rule_id == "LOCK-LIC-003"


def test_review_required_licence_skips_for_mit() -> None:
    rule = LicenceReviewRequiredRule()
    findings = list(
        rule.evaluate(
            evidence=_evidence(licence_assertions=["MIT"]), scan_run_id=1, repository_id=1
        )
    )
    assert not findings


def test_licence_provider_unavailable_fires() -> None:
    rule = LicenceProviderUnavailableRule()
    findings = list(
        rule.evaluate(
            evidence=_evidence(observations=[{"provider": "deps_dev", "status": "unavailable"}]),
            scan_run_id=1,
            repository_id=1,
        )
    )
    assert len(findings) == 1
    assert findings[0].rule_id == "LOCK-LIC-004"


def test_licence_provider_unavailable_skips_for_other_status() -> None:
    rule = LicenceProviderUnavailableRule()
    findings = list(
        rule.evaluate(
            evidence=_evidence(observations=[{"provider": "deps_dev", "status": "available"}]),
            scan_run_id=1,
            repository_id=1,
        )
    )
    assert not findings


def test_licence_inventory_emits_informational() -> None:
    rule = LicenceInventoryRule()
    findings = list(
        rule.evaluate(
            evidence=_evidence(licence_assertions=["MIT"]),
            scan_run_id=1,
            repository_id=1,
        )
    )
    assert len(findings) == 1
    assert findings[0].rule_id == "LOCK-LIC-INV"


def test_licence_inventory_works_without_assertions() -> None:
    rule = LicenceInventoryRule()
    findings = list(
        rule.evaluate(evidence=_evidence(licence_assertions=[]), scan_run_id=1, repository_id=1)
    )
    assert len(findings) == 1
    assert findings[0].raw["evidence"]["licences"] == []


def test_licence_finding_has_no_legal_conclusion() -> None:
    """The rule never claims the licence is illegal."""
    rule = LicenceReviewRequiredRule()
    findings = list(
        rule.evaluate(
            evidence=_evidence(licence_assertions=["AGPL-3.0"]),
            scan_run_id=1,
            repository_id=1,
        )
    )
    summary = findings[0].raw["summary"]
    assert "illegal" not in summary.lower()
    assert "law" not in summary.lower()
    # The summary should mention review, not a verdict.
    assert "review" in summary.lower()
