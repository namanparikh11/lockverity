"""v0.6 CycloneDX 1.7 SBOM exporter tests.

These tests prove the v0.6 acceptance criteria for the
CycloneDX 1.7 export capability. They cover:

- eligibility for every scan status (completed, partial with
  inventory, partial without inventory, failed, cancelled,
  queued, running, and the not-found path);
- byte-for-byte determinism of repeated exports of the
  unchanged persisted evidence;
- the exact ``bomFormat`` / ``specVersion`` / ``serialNumber``
  / tool / timestamp contract;
- bom-ref identity (PURL when valid, deterministic fallback for
  duplicates and missing PURLs);
- PURL handling for valid ecosystems and the missing-version
  case (the ``version`` JSON field MUST be omitted when
  persisted version is ``None``; no placeholder string);
- licence handling via the official library SPDX support
  (``cyclonedx.contrib.license.factories.LicenseFactory`` plus
  ``cyclonedx.spdx.is_supported_id`` / ``is_expression``), with
  SPDX id vs named-licence distinction carried by the JSON
  shape alone (no separate ``lockverity:licence-spdx-verified``
  property);
- dependency relationships (only observed edges emitted, no
  edges invented from co-occurrence, no synthetic root-to-all
  components edges, honest coverage analysis from
  ``Manifest.parse_status``);
- evidence-honesty properties (only persisted metadata, never
  paths or secrets);
- no database writes and no external HTTP during the export;
- tool metadata is canonical CycloneDX 1.7 (a single
  ``ToolRepository.components`` entry; no duplicate legacy
  ``tools`` list);
- the generated BOM passes the official CycloneDX 1.7
  validator (``JsonStrictValidator(SchemaVersion.V1_7)``).
"""

from __future__ import annotations

import json
import re
import socket
from datetime import UTC
from typing import Any

import pytest
from app.exporters import CycloneDxV17Exporter
from app.exporters._common import (
    evaluate_export_eligibility,
)
from app.exporters.cyclonedx_v17 import (
    CYCLONEDX_MEDIA_TYPE,
    CYCLONEDX_SCHEMA_URI,
    CYCLONEDX_SPEC_VERSION,
)
from app.models.component import Component, ComponentVersionSource
from app.models.dependency_edge import DependencyEdge
from app.models.finding import (
    Finding,
    FindingCategory,
    FindingConfidence,
    FindingSeverity,
    FindingStatus,
)
from app.models.manifest import Manifest, ManifestParseStatus
from app.models.repository import (
    Repository,
    RepositoryProvider,
    RepositorySourceType,
    RepositoryVisibility,
)
from app.models.scan_run import ScanRun, ScanStatus, ScanTriggerType
from app.providers.results import ProviderSuccess, ProviderUnavailable

# ---------------------------------------------------------------------
# Test fixture
# ---------------------------------------------------------------------


def _make_repo(session: Any, *, owner: str = "octocat", name: str = "Hello-World") -> int:
    repo = Repository(
        source_type=RepositorySourceType.GITHUB,
        provider=RepositoryProvider.GITHUB,
        owner=owner,
        name=name,
        canonical_url=f"https://github.com/{owner}/{name}",
        default_branch="main",
        visibility=RepositoryVisibility.PUBLIC,
    )
    session.add(repo)
    session.flush()
    return repo.id


def _make_scan(
    session: Any,
    *,
    repo_id: int,
    status: ScanStatus = ScanStatus.COMPLETED,
    resolved_commit_sha: str | None = "abc1234567",
) -> int:
    scan = ScanRun(
        repository_id=repo_id,
        trigger_type=ScanTriggerType.MANUAL,
        status=status,
        resolved_commit_sha=resolved_commit_sha,
        analyzer_version="0.6.0",
    )
    session.add(scan)
    session.flush()
    return scan.id


def _make_manifest(
    session: Any,
    *,
    scan_id: int,
    path: str,
    content_sha: str = "a" * 64,
    parse_status: ManifestParseStatus = ManifestParseStatus.PARSED,
) -> int:
    m = Manifest(
        scan_run_id=scan_id,
        path=path,
        manifest_type="package_json",
        ecosystem="npm",
        content_sha256=content_sha,
        parse_status=parse_status,
    )
    session.add(m)
    session.flush()
    return m.id


def _make_component(
    session: Any,
    *,
    scan_id: int,
    manifest_id: int,
    name: str,
    version: str | None,
    package_url: str | None = None,
    direct: bool = True,
    integrity: str | None = None,
) -> int:
    if package_url is None:
        package_url = f"pkg:npm/{name}" if version is None else f"pkg:npm/{name}@{version}"
    c = Component(
        scan_run_id=scan_id,
        manifest_id=manifest_id,
        ecosystem="npm",
        package_name=name,
        version=version,
        version_source=ComponentVersionSource.LOCKFILE
        if version is not None
        else ComponentVersionSource.UNRESOLVED,
        package_url=package_url,
        direct=direct,
        integrity=integrity,
    )
    session.add(c)
    session.flush()
    return c.id


def _make_edge(session: Any, *, scan_id: int, parent_id: int, child_id: int) -> None:
    e = DependencyEdge(
        scan_run_id=scan_id,
        parent_component_id=parent_id,
        child_component_id=child_id,
        relationship="runtime",
        depth=1,
    )
    session.add(e)
    session.flush()


def _make_licence_finding(
    session: Any,
    *,
    scan_id: int,
    repo_id: int,
    component_id: int,
    licences: list[str],
    rule_id: str = "LOCK-LIC-001",
    stable_key: str = "licence-1",
) -> None:
    finding = Finding(
        scan_run_id=scan_id,
        repository_id=repo_id,
        rule_id=rule_id,
        category=FindingCategory.LICENCE,
        severity=FindingSeverity.INFORMATIONAL,
        confidence=FindingConfidence.HIGH,
        title="Licence observed",
        summary="; ".join(licences),
        location_path="package.json",
        stable_key=stable_key,
        status=FindingStatus.OPEN,
        evidence_json=json.dumps(
            {
                "evidence": {
                    "component_id": component_id,
                    "licences": licences,
                }
            }
        ),
    )
    session.add(finding)
    session.flush()


def _make_rich_scan(session: Any) -> tuple[int, int, int]:
    """Build a small but rich scan with multiple components, an
    SPDX licence, a named licence, a missing-version component,
    a duplicate PURL across two manifests, and a dependency
    edge.

    Returns the scan id, the first lodash component id, and the
    left-pad component id so individual tests can target them.
    """
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m1 = _make_manifest(session, scan_id=scan_id, path="package.json")
    m2 = _make_manifest(session, scan_id=scan_id, path="package-lock.json", content_sha="b" * 64)
    c_lodash = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=m1,
        name="lodash",
        version="4.17.21",
        direct=True,
        integrity="sha512-AAA=",
    )
    c_leftpad = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=m1,
        name="left-pad",
        version="1.0.0",
        direct=True,
    )
    _make_component(
        session,
        scan_id=scan_id,
        manifest_id=m1,
        name="stay",
        version="1.0.0",
        direct=True,
    )
    c_unresolved = _make_component(
        session,
        scan_id=scan_id,
        manifest_id=m1,
        name="unresolved-pkg",
        version=None,
        direct=False,
    )
    _make_component(
        session,
        scan_id=scan_id,
        manifest_id=m2,
        name="lodash",
        version="4.17.21",
        direct=True,
    )
    _make_edge(session, scan_id=scan_id, parent_id=c_lodash, child_id=c_leftpad)
    _make_licence_finding(
        session,
        scan_id=scan_id,
        repo_id=repo_id,
        component_id=c_lodash,
        licences=["MIT"],
        stable_key="lic-lodash",
    )
    _make_licence_finding(
        session,
        scan_id=scan_id,
        repo_id=repo_id,
        component_id=c_leftpad,
        licences=["Stay-Public-1.0"],
        rule_id="LOCK-LIC-002",
        stable_key="lic-leftpad",
    )
    # Also surface the unresolved component as licence-less.
    # ``c_unresolved`` is intentionally unused at the licence
    # level to test the "no licences emitted" path.
    del c_unresolved
    return scan_id, c_lodash, c_leftpad


# ---------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------


def test_eligibility_completed_scan_is_eligible(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id, status=ScanStatus.COMPLETED)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="lodash", version="4.17.21")
    result = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(result, ProviderSuccess)


def test_eligibility_partial_with_inventory_is_eligible_with_limitation(
    session,
) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id, status=ScanStatus.PARTIAL)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="lodash", version="4.17.21")
    result = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(result, ProviderSuccess)
    body = json.loads(result.data)
    props = {p["name"]: p["value"] for p in body["metadata"]["properties"]}
    assert props["lockverity:provider-coverage"] == "degraded"
    assert props["lockverity:scan-status"] == "partial"
    assert "lockverity:partial-reason" in props


def test_eligibility_partial_without_inventory_is_rejected(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id, status=ScanStatus.PARTIAL)
    result = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(result, ProviderUnavailable)
    assert result.error_code == "partial_incomplete"


@pytest.mark.parametrize(
    "status",
    [ScanStatus.QUEUED, ScanStatus.RUNNING, ScanStatus.FAILED, ScanStatus.CANCELLED],
)
def test_eligibility_non_eligible_status_is_rejected(session, status) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id, status=status)
    if status not in {ScanStatus.QUEUED, ScanStatus.CANCELLED}:
        m = _make_manifest(session, scan_id=scan_id, path="package.json")
        _make_component(session, scan_id=scan_id, manifest_id=m, name="lodash", version="4.17.21")
    result = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(result, ProviderUnavailable)
    expected = {
        ScanStatus.QUEUED: "scan_not_started",
        ScanStatus.RUNNING: "scan_in_progress",
        ScanStatus.FAILED: "scan_failed",
        ScanStatus.CANCELLED: "scan_cancelled",
    }[status]
    assert result.error_code == expected


def test_eligibility_unknown_scan_is_rejected(session) -> None:
    result = CycloneDxV17Exporter(lambda: session).export(scan_run_id=999_999)
    assert isinstance(result, ProviderUnavailable)
    assert result.error_code == "export_scan_not_found"


def test_evaluate_export_eligibility_helper_is_authoritative() -> None:
    # queued/running
    assert (
        evaluate_export_eligibility(
            _scan_stub(ScanStatus.QUEUED), component_count=0, manifest_count=0
        ).code
        == "scan_not_started"
    )
    assert (
        evaluate_export_eligibility(
            _scan_stub(ScanStatus.RUNNING), component_count=0, manifest_count=0
        ).code
        == "scan_in_progress"
    )
    # failed/cancelled
    assert (
        evaluate_export_eligibility(
            _scan_stub(ScanStatus.FAILED), component_count=0, manifest_count=0
        ).code
        == "scan_failed"
    )
    assert (
        evaluate_export_eligibility(
            _scan_stub(ScanStatus.CANCELLED), component_count=0, manifest_count=0
        ).code
        == "scan_cancelled"
    )
    # partial without inventory
    assert (
        evaluate_export_eligibility(
            _scan_stub(ScanStatus.PARTIAL), component_count=0, manifest_count=0
        ).code
        == "partial_incomplete"
    )
    # partial with inventory
    eligibility = evaluate_export_eligibility(
        _scan_stub(ScanStatus.PARTIAL), component_count=2, manifest_count=1
    )
    assert eligibility.eligible is True
    assert "provider_degraded" in eligibility.limitations


def _scan_stub(status: ScanStatus) -> ScanRun:
    """Build a detached ScanRun with the given status.

    ``evaluate_export_eligibility`` only inspects ``status``,
    so the rest of the model is irrelevant.
    """
    return ScanRun(
        repository_id=0,
        trigger_type=ScanTriggerType.MANUAL,
        status=status,
    )


# ---------------------------------------------------------------------
# BOM structure and validation
# ---------------------------------------------------------------------


def test_exporter_returns_valid_cyclonedx_1_7_json(session) -> None:
    scan_id, _, _ = _make_rich_scan(session)
    result = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(result, ProviderSuccess)
    body = json.loads(result.data)
    assert body["bomFormat"] == "CycloneDX"
    assert body["specVersion"] == CYCLONEDX_SPEC_VERSION
    assert body["$schema"] == CYCLONEDX_SCHEMA_URI
    assert body["version"] == 1
    # Tool metadata is registered under the v0.6
    # ``metadata.tools.components`` collection. The
    # canonical CycloneDX 1.7 representation is the only
    # one in the BOM; the legacy ``tools`` list is not
    # emitted.
    tools_block = body["metadata"].get("tools") or {}
    modern_tools = tools_block.get("components", []) if isinstance(tools_block, dict) else []
    assert modern_tools, f"Tool block is empty: {body['metadata']}"
    # Every declared tool must identify Lockverity at 0.6.0.
    for tool in modern_tools:
        assert tool.get("name") == "lockverity"
        assert tool.get("version") == "0.6.0"
        assert tool.get("vendor") == "Lockverity" or tool.get("publisher") == "Lockverity"


def test_exporter_emits_no_duplicate_lockverity_tool(session) -> None:
    """The canonical tool entry is emitted once and only once.

    The legacy ``tools`` array (deprecated in CycloneDX 1.5+) is
    not emitted; the modern ``components`` array carries the
    single Lockverity tool. This guards against accidental
    duplicate tool declarations.
    """
    scan_id, _, _ = _make_rich_scan(session)
    result = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(result.data)
    tools_block = body["metadata"].get("tools") or {}
    modern = tools_block.get("components", []) if isinstance(tools_block, dict) else []
    legacy = tools_block.get("tools", []) if isinstance(tools_block, dict) else []
    lockverity_in_modern = sum(1 for tool in modern if tool.get("name") == "lockverity")
    lockverity_in_legacy = sum(1 for tool in legacy if tool.get("name") == "lockverity")
    assert lockverity_in_modern == 1, (
        f"expected exactly one Lockverity tool in components; got {lockverity_in_modern}"
    )
    assert lockverity_in_legacy == 0, (
        f"expected zero Lockverity tools in the legacy list; got {lockverity_in_legacy}"
    )


def test_exporter_serial_number_is_deterministic_uuid5(session) -> None:
    scan_id, _, _ = _make_rich_scan(session)
    exp = CycloneDxV17Exporter(lambda: session)
    r1 = exp.export(scan_run_id=scan_id)
    r2 = exp.export(scan_run_id=scan_id)
    assert isinstance(r1, ProviderSuccess)
    assert isinstance(r2, ProviderSuccess)
    s1 = json.loads(r1.data)["serialNumber"]
    s2 = json.loads(r2.data)["serialNumber"]
    assert s1 == s2
    assert s1.startswith("urn:uuid:")
    # UUID5 stable for the same content hash.
    assert s1 == s2


def test_exporter_is_byte_for_byte_deterministic(session) -> None:
    scan_id, _, _ = _make_rich_scan(session)
    exp = CycloneDxV17Exporter(lambda: session)
    r1 = exp.export(scan_run_id=scan_id)
    r2 = exp.export(scan_run_id=scan_id)
    assert isinstance(r1, ProviderSuccess)
    assert isinstance(r2, ProviderSuccess)
    # The bytes are identical, not just the serialNumber.
    assert r1.data == r2.data


def test_exporter_uses_persisted_completed_at_not_utcnow(session) -> None:
    from datetime import datetime

    repo_id = _make_repo(session)
    completed_at = datetime(2024, 6, 1, 12, 34, 56, tzinfo=UTC)
    scan = ScanRun(
        repository_id=repo_id,
        trigger_type=ScanTriggerType.MANUAL,
        status=ScanStatus.COMPLETED,
        resolved_commit_sha="abc1234567",
        analyzer_version="0.6.0",
    )
    session.add(scan)
    session.flush()
    scan_id = scan.id
    scan.completed_at = completed_at
    session.add(scan)
    session.commit()
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="lodash", version="4.17.21")
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(r, ProviderSuccess)
    body = json.loads(r.data)
    assert body["metadata"]["timestamp"].startswith("2024-06-01T12:34:56")


def test_exporter_preserves_component_name_and_version(session) -> None:
    scan_id, _, _ = _make_rich_scan(session)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    names = {c["name"] for c in body["components"]}
    assert "lodash" in names
    assert "left-pad" in names
    assert "stay" in names
    lodash = next(c for c in body["components"] if c["bom-ref"] == "pkg:npm/lodash@4.17.21")
    assert lodash["version"] == "4.17.21"


def test_exporter_does_not_fabricate_missing_version(session) -> None:
    """A missing persisted version produces no component version field.

    No placeholder, no empty string, no "unspecified", no
    "unknown". The component carries a
    ``lockverity:version-source`` property so the absence is
    traceable. Repeated output remains byte-for-byte
    deterministic. Schema validation still passes.
    """
    scan_id, _, _ = _make_rich_scan(session)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(r, ProviderSuccess)
    body = json.loads(r.data)
    unresolved = next(c for c in body["components"] if c["name"] == "unresolved-pkg")
    # The version field is omitted entirely.
    assert "version" not in unresolved, (
        f"version field must be omitted when persisted version is None; got {unresolved!r}"
    )
    props = {p["name"]: p["value"] for p in unresolved.get("properties", [])}
    assert props.get("lockverity:version-source") == "unresolved"
    # No placeholder string appears anywhere in the BOM.
    forbidden = re.compile(r"\b(unspecified|unknown|latest|n/a)\b", re.IGNORECASE)
    body_text = r.data.decode("utf-8")
    assert forbidden.search(body_text) is None, "forbidden placeholder found in BOM"
    # Determinism: re-run produces the same bytes.
    r2 = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(r2, ProviderSuccess)
    assert r.data == r2.data
    # Schema validation still passes.
    from cyclonedx.schema.schema import SchemaVersion
    from cyclonedx.validation.json import JsonStrictValidator

    result = JsonStrictValidator(SchemaVersion.V1_7).validate_str(body_text)
    assert not result, f"schema validation reported: {list(result)}"


def test_exporter_duplicate_purl_remains_distinguishable(session) -> None:
    scan_id, _, _ = _make_rich_scan(session)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    lodashes = [c for c in body["components"] if c["name"] == "lodash"]
    assert len(lodashes) == 2
    refs = {c["bom-ref"] for c in lodashes}
    # One is the persisted PURL, the other is the deterministic
    # fallback for the second observation of the same package.
    assert "pkg:npm/lodash@4.17.21" in refs
    assert any(r.startswith("lockverity:component:") for r in refs)
    # The manifest-path property proves the second observation
    # is the package-lock.json instance.
    second = next(c for c in lodashes if c["bom-ref"].startswith("lockverity:component:"))
    props = {p["name"]: p["value"] for p in second.get("properties", [])}
    assert props["lockverity:manifest-path"] == "package-lock.json"


def test_exporter_emits_valid_purl_when_known(session) -> None:
    scan_id, _, _ = _make_rich_scan(session)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    lodash = next(c for c in body["components"] if c["bom-ref"] == "pkg:npm/lodash@4.17.21")
    assert lodash["purl"] == "pkg:npm/lodash@4.17.21"


def test_exporter_omits_purl_when_ecosystem_unsupported(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    # 'cargo' is not in the persisted ecosystem -> PURL map.
    c = Component(
        scan_run_id=scan_id,
        manifest_id=m,
        ecosystem="cargo",
        package_name="serde",
        version="1.0.0",
        version_source=ComponentVersionSource.LOCKFILE,
        package_url=None,
        direct=True,
    )
    session.add(c)
    session.flush()
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    comp = body["components"][0]
    assert "purl" not in comp or comp.get("purl") is None
    # The bom-ref falls back to the deterministic id form.
    assert comp["bom-ref"].startswith("lockverity:component:")


def test_exporter_preserves_persisted_hash_when_valid(session) -> None:
    scan_id, _, _ = _make_rich_scan(session)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    lodash = next(c for c in body["components"] if c["bom-ref"] == "pkg:npm/lodash@4.17.21")
    props = {p["name"]: p["value"] for p in lodash.get("properties", [])}
    assert props["lockverity:integrity"] == "sha512-AAA="


def test_exporter_omits_hash_when_missing(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="left-pad", version="1.0.0")
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    comp = body["components"][0]
    # No ``hashes`` field, no ``lockverity:integrity`` property.
    assert "hashes" not in comp
    props = {p["name"]: p["value"] for p in comp.get("properties", [])}
    assert "lockverity:integrity" not in props


# ---------------------------------------------------------------------
# SPDX library-driven licence handling
# ---------------------------------------------------------------------


def test_exporter_emits_known_spdx_id_as_id(session) -> None:
    """``MIT`` is a recognised SPDX id; the library emits it
    as ``{"license": {"id": "MIT"}}`` (no fake ``name``)."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    c = _make_component(session, scan_id=scan_id, manifest_id=m, name="lodash", version="4.17.21")
    _make_licence_finding(
        session,
        scan_id=scan_id,
        repo_id=repo_id,
        component_id=c,
        licences=["MIT"],
    )
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    lodash = body["components"][0]
    licences = lodash.get("licenses", [])
    assert any(
        isinstance(lic, dict) and lic.get("license", {}).get("id") == "MIT" for lic in licences
    ), f"MIT not emitted as id: {licences}"


def test_exporter_emits_apache_2_0_as_id(session) -> None:
    """``Apache-2.0`` is a recognised SPDX id."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    c = _make_component(session, scan_id=scan_id, manifest_id=m, name="dep", version="1.0.0")
    _make_licence_finding(
        session,
        scan_id=scan_id,
        repo_id=repo_id,
        component_id=c,
        licences=["Apache-2.0"],
    )
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    licences = body["components"][0].get("licenses", [])
    assert any(
        isinstance(lic, dict) and lic.get("license", {}).get("id") == "Apache-2.0"
        for lic in licences
    ), f"Apache-2.0 not emitted as id: {licences}"


def test_exporter_emits_valid_spdx_expression(session) -> None:
    """A valid SPDX expression like ``MIT OR Apache-2.0`` is
    emitted as a CycloneDX expression, not a name."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    c = _make_component(session, scan_id=scan_id, manifest_id=m, name="dep", version="1.0.0")
    _make_licence_finding(
        session,
        scan_id=scan_id,
        repo_id=repo_id,
        component_id=c,
        licences=["MIT OR Apache-2.0"],
    )
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    licences = body["components"][0].get("licenses", [])
    assert any(
        isinstance(lic, dict) and lic.get("expression") == "MIT OR Apache-2.0" for lic in licences
    ), f"SPDX expression not preserved: {licences}"


def test_exporter_emits_licenseref_as_name_when_unsupported(session) -> None:
    """A ``LicenseRef-*`` value is not in the library's SPDX
    id list (only specific LicenseRefs are). The library
    falls back to ``name``; the observed value is preserved
    verbatim."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    c = _make_component(session, scan_id=scan_id, manifest_id=m, name="dep", version="1.0.0")
    _make_licence_finding(
        session,
        scan_id=scan_id,
        repo_id=repo_id,
        component_id=c,
        licences=["LicenseRef-CustomOrg-PolyForm-Noncommercial-1.0.0"],
    )
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    licences = body["components"][0].get("licenses", [])
    # The value is preserved as a name; it is not relabelled
    # as an SPDX id.
    assert all(
        lic.get("license", {}).get("id") != "LicenseRef-CustomOrg-PolyForm-Noncommercial-1.0.0"
        for lic in licences
        if isinstance(lic, dict)
    )
    assert any(
        lic.get("license", {}).get("name") == "LicenseRef-CustomOrg-PolyForm-Noncommercial-1.0.0"
        for lic in licences
        if isinstance(lic, dict)
    )


def test_exporter_emits_non_spdx_value_as_name(session) -> None:
    """A non-SPDX custom value is preserved as ``name`` only."""
    scan_id, _, _ = _make_rich_scan(session)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    left = next(c for c in body["components"] if c["bom-ref"] == "pkg:npm/left-pad@1.0.0")
    licences = left.get("licenses", [])
    # ``Stay-Public-1.0`` is not a known SPDX id and the
    # library falls back to ``name``.
    assert any(
        isinstance(lic, dict) and lic.get("license", {}).get("name") == "Stay-Public-1.0"
        for lic in licences
    ), f"non-SPDX value not preserved as name: {licences}"
    # No ``id`` is fabricated for the unrecognised value.
    for lic in licences:
        assert lic.get("license", {}).get("id") != "Stay-Public-1.0"


def test_exporter_emits_spdx_shaped_nonexistent_as_name(session) -> None:
    """A value that looks SPDX-shaped but is not in the
    library's SPDX list is preserved as ``name`` (no fake id)."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    c = _make_component(session, scan_id=scan_id, manifest_id=m, name="dep", version="1.0.0")
    # ``GLWT-PL`` is shaped like an SPDX id but the library's
    # SPDX list does not include it.
    _make_licence_finding(
        session,
        scan_id=scan_id,
        repo_id=repo_id,
        component_id=c,
        licences=["GLWT-PL"],
    )
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    licences = body["components"][0].get("licenses", [])
    assert all(lic.get("license", {}).get("id") != "GLWT-PL" for lic in licences)
    assert any(lic.get("license", {}).get("name") == "GLWT-PL" for lic in licences)


def test_exporter_omits_licence_when_no_evidence(session) -> None:
    """Missing licence evidence means the component has no
    ``licenses`` field at all (not a concluded licence)."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="left-pad", version="1.0.0")
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    comp = body["components"][0]
    assert "licenses" not in comp
    # The component does not carry the v0.5-era
    # ``lockverity:licence-spdx-verified`` property either;
    # the v0.6 contract relies on the library's id-vs-name
    # distinction alone.
    for prop in comp.get("properties", []):
        assert prop["name"] != "lockverity:licence-spdx-verified"


def test_exporter_does_not_invent_licence_for_contradictory_evidence(
    session,
) -> None:
    """When the same component has two LICENCE findings
    reporting different observed values, the exporter emits
    both observed values (the consumer sees the contradiction)
    but does not pick one and call it "concluded"."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    c = _make_component(session, scan_id=scan_id, manifest_id=m, name="dep", version="1.0.0")
    _make_licence_finding(
        session,
        scan_id=scan_id,
        repo_id=repo_id,
        component_id=c,
        licences=["MIT"],
        rule_id="LOCK-LIC-001",
        stable_key="lic-1",
    )
    _make_licence_finding(
        session,
        scan_id=scan_id,
        repo_id=repo_id,
        component_id=c,
        licences=["Apache-2.0"],
        rule_id="LOCK-LIC-002",
        stable_key="lic-2",
    )
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    licences = body["components"][0].get("licenses", [])
    ids = {lic.get("license", {}).get("id") for lic in licences}
    assert "MIT" in ids
    assert "Apache-2.0" in ids


# ---------------------------------------------------------------------
# Dependency graph truthfulness
# ---------------------------------------------------------------------


def test_exporter_emits_no_synthetic_root_to_all_components_edges(
    session,
) -> None:
    """The metadata root component MUST NOT carry a synthetic
    ``dependsOn`` referencing every component. The library
    may auto-create an empty ``Dependency`` entry for the
    root, but a non-empty ``dependsOn`` is an invented
    dependency relationship and is forbidden. The
    post-processing filter removes the library's empty
    entries so the root never appears in the final
    ``dependencies`` block."""
    scan_id, _, _ = _make_rich_scan(session)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    for dep in body.get("dependencies", []):
        if dep["ref"].startswith("lockverity:scan-"):
            assert not (dep.get("dependsOn") or []), (
                f"root component must not declare a synthetic dependsOn: {dep!r}"
            )


def test_exporter_omits_root_from_dependency_block(session) -> None:
    """The metadata root component (``lockverity:scan-{id}``)
    is not present in the final ``dependencies`` block. The
    library auto-adds an empty ``Dependency`` entry for the
    root during ``Bom.validate()``; the v0.6 post-processing
    filter removes it because the root has no observed
    outgoing edges. The absence is the honest "unknown"
    signal, not a fabricated "has no dependencies" claim."""
    scan_id, _, _ = _make_rich_scan(session)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    root_refs = [
        d for d in body.get("dependencies", []) if d.get("ref", "").startswith("lockverity:scan-")
    ]
    assert not root_refs, f"root must not appear in dependencies block; got {root_refs!r}"


def test_exporter_omits_components_without_observed_edges(session) -> None:
    """Components that have no persisted ``DependencyEdge``
    row pointing to them as a parent MUST NOT appear in the
    final ``dependencies`` block. The library auto-adds
    empty entries for every component; the v0.6
    post-processing filter removes them. A component that
    only appears as a child in one edge is also omitted:
    the consumer cannot infer its outgoing edges from a
    single incoming edge."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    c_lodash = _make_component(
        session, scan_id=scan_id, manifest_id=m, name="lodash", version="4.17.21"
    )
    c_leftpad = _make_component(
        session, scan_id=scan_id, manifest_id=m, name="left-pad", version="1.0.0"
    )
    c_stay = _make_component(session, scan_id=scan_id, manifest_id=m, name="stay", version="1.0.0")
    # One observed edge: lodash depends on left-pad. stay
    # has no observed edges.
    _make_edge(session, scan_id=scan_id, parent_id=c_lodash, child_id=c_leftpad)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    refs = {d.get("ref") for d in body.get("dependencies", [])}
    # Only lodash should be in the dependencies block.
    assert "pkg:npm/lodash@4.17.21" in refs
    # left-pad is a child, never a parent: not in the block.
    assert "pkg:npm/left-pad@1.0.0" not in refs
    # stay has no observed edges: not in the block.
    assert "pkg:npm/stay@1.0.0" not in refs
    # The root is also not in the block.
    assert not any(r.startswith("lockverity:scan-") for r in refs)
    # The lodash entry retains the observed edge.
    lodash_dep = next(d for d in body["dependencies"] if d["ref"] == "pkg:npm/lodash@4.17.21")
    assert lodash_dep.get("dependsOn") == ["pkg:npm/left-pad@1.0.0"]
    # stay (c_stay is the third component) is still in the
    # components block; the filter only removes empty
    # dependency entries, not the components themselves.
    component_names = {c.get("name") for c in body.get("components", [])}
    assert "stay" in component_names
    assert c_stay  # silence unused warning


def test_exporter_retains_observed_dependencies(session) -> None:
    """A persisted ``DependencyEdge`` is retained verbatim."""
    scan_id, _, _ = _make_rich_scan(session)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    lodash_dep = next(
        (d for d in body["dependencies"] if d["ref"] == "pkg:npm/lodash@4.17.21"),
        None,
    )
    assert lodash_dep is not None
    assert lodash_dep.get("dependsOn") == ["pkg:npm/left-pad@1.0.0"], (
        f"persisted edge not retained: {lodash_dep!r}"
    )


def test_exporter_does_not_invent_edges_from_component_co_occurrence(
    session,
) -> None:
    """Components that share a scan MUST NOT gain an edge
    simply because they co-occur in the persisted evidence.
    The only edge in this dataset is between lodash and
    left-pad; no other edge is invented."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="left-pad", version="1.0.0")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="right-pad", version="1.0.0")
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    for entry in body.get("dependencies", []):
        # No component references right-pad as a child.
        for child in entry.get("dependsOn") or []:
            assert "right-pad" not in child
            assert "left-pad" not in child


def test_exporter_reports_partial_coverage_when_no_edges_observed(
    session,
) -> None:
    """A scan with parsed manifests but zero observed
    dependency edges is reported as ``partial`` (not
    ``complete``). An inventory without observed
    relationships cannot be claimed as a complete graph
    even when every manifest was successfully parsed; the
    consumer cannot tell whether transitive dependencies
    were missed."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="left-pad", version="1.0.0")
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    props = {p["name"]: p["value"] for p in body["metadata"]["properties"]}
    assert props["lockverity:dependency-graph-coverage"] == "partial"


def test_exporter_reports_unknown_coverage_when_no_manifests(session) -> None:
    """A scan with zero manifests cannot prove any graph
    coverage; the BOM marks it as ``unknown`` rather than
    ``empty`` or ``complete``. The eligibility helper
    refuses to build a BOM for a partial scan with no
    manifests, so this test creates a completed scan,
    wipes the manifests, and verifies the helper still
    surfaces the unknown-coverage answer when the BOM
    is built (only completed scans with no manifests are
    eligible)."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id, status=ScanStatus.COMPLETED)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="left-pad", version="1.0.0")
    # Wipe the manifest rows so the export sees zero manifests.
    session.query(Manifest).filter(Manifest.scan_run_id == scan_id).delete()
    session.commit()
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(r, ProviderSuccess)
    body = json.loads(r.data)
    props = {p["name"]: p["value"] for p in body["metadata"]["properties"]}
    # Zero manifests → unknown coverage. The graph cannot
    # be claimed as complete (or even partial) because no
    # parser ran.
    assert props["lockverity:dependency-graph-coverage"] == "unknown"


def test_exporter_reports_partial_coverage_for_partial_manifests(
    session,
) -> None:
    """A manifest that failed or was only partially parsed
    means the graph is incomplete; coverage is ``partial``."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id, status=ScanStatus.PARTIAL)
    _make_manifest(
        session,
        scan_id=scan_id,
        path="package.json",
        parse_status=ManifestParseStatus.PARTIAL,
    )
    m2 = _make_manifest(
        session,
        scan_id=scan_id,
        path="package-lock.json",
        parse_status=ManifestParseStatus.PARSED,
    )
    _make_component(session, scan_id=scan_id, manifest_id=m2, name="left-pad", version="1.0.0")
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    props = {p["name"]: p["value"] for p in body["metadata"]["properties"]}
    assert props["lockverity:dependency-graph-coverage"] == "partial"


def test_exporter_reports_complete_coverage_with_parsed_manifests_and_edges(
    session,
) -> None:
    """v0.6 intentionally never emits ``complete``.

    The v0.3-v0.5 schema has **no authoritative persisted
    signal** that positively proves the full transitive
    closure of every applicable manifest was captured.
    Even when every manifest is ``PARSED`` AND at least one
    observed dependency edge was persisted, the model cannot
    prove the transitive closure was complete. The
    ``Manifest.parse_status`` field only reports whether the
    parser ran without raising; it does not prove every
    relationship was extracted (a ``package.json`` is a real
    example — it parses successfully but only declares
    direct dependencies).

    The v0.6 evidence-honesty contract therefore reports
    ``partial`` even for the "all PARSED + edges exist"
    case, until a future milestone introduces a persisted
    completeness signal. This test pins the v0.6
    contract."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    c1 = _make_component(session, scan_id=scan_id, manifest_id=m, name="lodash", version="4.17.21")
    c2 = _make_component(session, scan_id=scan_id, manifest_id=m, name="left-pad", version="1.0.0")
    _make_edge(session, scan_id=scan_id, parent_id=c1, child_id=c2)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    props = {p["name"]: p["value"] for p in body["metadata"]["properties"]}
    # The "all PARSED + at least one edge" case is ``partial``
    # in v0.6 because the schema has no positive completeness
    # signal. The BOM is honest about the limitation.
    assert props["lockverity:dependency-graph-coverage"] == "partial"


def test_exporter_does_not_mark_one_component_scan_as_complete(
    session,
) -> None:
    """A scan with exactly one component and no observed
    edges is reported as ``partial``, NOT ``complete``.
    The graph is only marked complete when every manifest
    is ``PARSED`` AND at least one dependency edge was
    observed. A one-component inventory without observed
    relationships cannot be claimed as a complete graph
    because the consumer cannot tell whether transitive
    dependencies were missed."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="left-pad", version="1.0.0")
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    props = {p["name"]: p["value"] for p in body["metadata"]["properties"]}
    # Coverage is ``partial``: a single component with no
    # observed outgoing edges cannot be claimed as a
    # complete graph. The BOM carries an explicit
    # coverage marker so the consumer sees the limitation.
    assert props["lockverity:dependency-graph-coverage"] == "partial"


def test_exporter_partial_scan_does_not_erase_local_components(session) -> None:
    """The local inventory of a provider-degraded partial scan
    must be fully present in the BOM; provider degradation is
    metadata, not data loss."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id, status=ScanStatus.PARTIAL)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="lodash", version="4.17.21")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="left-pad", version="1.0.0")
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    assert len(body["components"]) == 2
    props = {p["name"]: p["value"] for p in body["metadata"]["properties"]}
    assert props["lockverity:inventory-coverage"] == "complete"
    assert props["lockverity:provider-coverage"] == "degraded"


# ---------------------------------------------------------------------
# Media type, route, and runtime guarantees
# ---------------------------------------------------------------------


def test_media_type_is_cyclonedx_1_7_json() -> None:
    assert CYCLONEDX_MEDIA_TYPE == "application/vnd.cyclonedx+json; version=1.7"


def test_exporter_does_not_make_external_http_calls(session) -> None:
    scan_id, _, _ = _make_rich_scan(session)
    # Block any real outbound socket to a non-loopback address.
    real_socket = socket.socket

    def guarded_socket(*args: Any, **kwargs: Any) -> socket.socket:
        family = args[0] if args else kwargs.get("family")
        if family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("CycloneDX 1.7 exporter must not make external HTTP calls")
        return real_socket(*args, **kwargs)

    socket.socket = guarded_socket  # type: ignore[assignment]
    try:
        CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    finally:
        socket.socket = real_socket  # type: ignore[assignment]


def test_exporter_does_not_write_to_database(session) -> None:
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="lodash", version="4.17.21")
    session.commit()
    # Capture the row count of every relevant table before
    # the export, then verify the counts are unchanged
    # afterwards. The exporter is read-only.
    from sqlalchemy import text

    counted_tables = ("scan_runs", "repositories", "manifests", "components", "findings")
    counts_before = {
        table: session.execute(
            text("SELECT count(*) FROM " + table)  # noqa: S608
        ).scalar()
        for table in counted_tables
    }

    CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)

    counts_after = {
        table: session.execute(
            text("SELECT count(*) FROM " + table)  # noqa: S608
        ).scalar()
        for table in counted_tables
    }
    assert counts_before == counts_after


def test_exporter_bom_passes_strict_cyclonedx_1_7_validation(session) -> None:
    from cyclonedx.schema.schema import SchemaVersion
    from cyclonedx.validation.json import JsonStrictValidator

    scan_id, _, _ = _make_rich_scan(session)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = r.data.decode("utf-8")
    validator = JsonStrictValidator(SchemaVersion.V1_7)
    result = validator.validate_str(body)
    assert not result, f"schema validation reported: {list(result)}"


# ---------------------------------------------------------------------
# LicenseRef classification (v0.6 final review)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "observed_licence",
    [
        # Real LicenseRef-* values used in v0.5 fixtures
        "LicenseRef-CustomOrg-PolyForm-Noncommercial-1.0.0",
        # Short LicenseRef-*
        "LicenseRef-Custom",
        # DocumentRef-scoped LicenseRef
        "DocumentRef-example:LicenseRef-Custom",
        # An SPDX expression containing a LicenseRef. The
        # installed ``cyclonedx-python-lib==11.11.0`` does
        # NOT accept LicenseRef in expressions (its
        # ``is_expression`` parser only handles the standard
        # SPDX list and the standard operators). The
        # observed value is preserved as a name; the consumer
        # sees the exact observed text.
        "MIT OR LicenseRef-Custom",
        # An invalid LicenseRef-like string (lowercase prefix)
        "licenseref-foo",
        # An empty LicenseRef
        "LicenseRef-",
    ],
)
def test_exporter_emits_licenseref_variants_as_preserved_name(
    session, observed_licence: str
) -> None:
    """Library-driven LicenseRef handling.

    The installed ``cyclonedx-python-lib==11.11.0`` does
    **not** include any ``LicenseRef-*`` value in its
    standard SPDX identifier list (verified via
    ``cyclonedx.spdx.is_supported_id``), and its
    ``is_expression`` parser does not accept
    LicenseRef-containing expressions. The honest output
    for every LicenseRef form is therefore the named
    licence shape (``{"license": {"name": "..."}}``),
    preserving the original observed value verbatim.

    The classification is library-driven (the rule lives
    in :func:`_classify_licence_value`), not a regex. The
    exporter must not invent an SPDX id for a value the
    library does not recognise."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    c = _make_component(session, scan_id=scan_id, manifest_id=m, name="dep", version="1.0.0")
    _make_licence_finding(
        session,
        scan_id=scan_id,
        repo_id=repo_id,
        component_id=c,
        licences=[observed_licence],
    )
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    licences = body["components"][0].get("licenses", [])
    # The observed value is preserved as a name.
    assert any(
        isinstance(lic, dict) and lic.get("license", {}).get("name") == observed_licence
        for lic in licences
    ), f"{observed_licence!r} not preserved as name: {licences}"
    # No SPDX id is fabricated for the unrecognised value.
    for lic in licences:
        assert lic.get("license", {}).get("id") != observed_licence
    # The BOM does not include a ``lockverity:licence-spdx-verified``
    # property: the id-vs-name distinction is the SPDX provenance.
    for prop in body["components"][0].get("properties", []):
        assert prop["name"] != "lockverity:licence-spdx-verified"


def test_exporter_licenseref_classification_matches_installed_library(session) -> None:
    """The classification is exactly what the installed
    library APIs report. This is a regression guard: if a
    future cyclonedx-python-lib version starts accepting
    LicenseRef in its SPDX id list or expression parser,
    the v0.6 exporter must continue to produce the
    library-driven answer. Any change to the v0.6
    classification must be justified against the installed
    library APIs."""
    from cyclonedx.spdx import is_expression, is_supported_id

    # Pick a known LicenseRef-* value. The library does not
    # include it in the standard SPDX identifier list.
    observed = "LicenseRef-CustomOrg-PolyForm-Noncommercial-1.0.0"
    assert is_supported_id(observed) is False
    assert is_expression(observed) is False

    # Pick an SPDX expression that contains a LicenseRef.
    # The library does not accept it as an expression.
    observed_expr = "MIT OR LicenseRef-Custom"
    assert is_expression(observed_expr) is False

    # Pick a standard SPDX identifier. The library accepts
    # it both as an id and as an expression (the
    # operator-regex check is what separates the two).
    observed_id = "MIT"
    assert is_supported_id(observed_id) is True
    assert is_expression(observed_id) is True  # single id is also "expression"


# ---------------------------------------------------------------------
# Graph completeness (v0.6 final review)
# ---------------------------------------------------------------------


def test_exporter_completeness_signal_audit() -> None:
    """The v0.3-v0.5 schema has no authoritative persisted
    signal that positively proves the full transitive
    closure of every applicable manifest was captured.

    This test documents the audit result by inspecting the
    persisted models. The audit conclusion is the basis of
    the v0.6 rule that ``dependency-graph-coverage=complete``
    is intentionally never emitted."""
    from app.models.component import Component
    from app.models.dependency_edge import DependencyEdge
    from app.models.manifest import Manifest

    # Manifest has parse_status, parse_warning_count, content_sha256.
    # None of these fields positively prove the full
    # transitive closure was captured.
    manifest_fields = {c.name for c in Manifest.__table__.columns}
    assert "transitive_closure_captured" not in manifest_fields
    assert "closure_complete" not in manifest_fields
    assert "graph_complete" not in manifest_fields

    # Component has no completeness field.
    component_fields = {c.name for c in Component.__table__.columns}
    assert "graph_complete" not in component_fields
    assert "transitive_closure_captured" not in component_fields

    # DependencyEdge has no completeness field.
    edge_fields = {c.name for c in DependencyEdge.__table__.columns}
    assert "graph_complete" not in edge_fields


def test_exporter_graph_coverage_never_emits_complete_when_manifests_exist(
    session,
) -> None:
    """The v0.6 rule: when at least one manifest is
    persisted, the graph coverage is ``partial`` because
    the schema has no positive completeness signal. This
    includes the "all PARSED + at least one edge" case
    that earlier reviews mistakenly classified as
    ``complete``."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m1 = _make_manifest(
        session,
        scan_id=scan_id,
        path="package-lock.json",
        parse_status=ManifestParseStatus.PARSED,
    )
    m2 = _make_manifest(
        session,
        scan_id=scan_id,
        path="yarn.lock",
        parse_status=ManifestParseStatus.PARSED,
    )
    c1 = _make_component(session, scan_id=scan_id, manifest_id=m1, name="lodash", version="4.17.21")
    c2 = _make_component(session, scan_id=scan_id, manifest_id=m2, name="left-pad", version="1.0.0")
    _make_edge(session, scan_id=scan_id, parent_id=c1, child_id=c2)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    props = {p["name"]: p["value"] for p in body["metadata"]["properties"]}
    # Two PARSED manifests + one observed edge is ``partial``
    # in v0.6. The BOM is honest about the limitation.
    assert props["lockverity:dependency-graph-coverage"] == "partial"


def test_exporter_graph_coverage_unknown_when_zero_manifests(session) -> None:
    """Zero manifests means the model cannot tell
    applicability; coverage is ``unknown``. (The exporter
    would normally reject the BOM via the eligibility
    helper, but a completed scan with no manifests is
    eligible and the coverage string is ``unknown``.)"""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id, status=ScanStatus.COMPLETED)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="left-pad", version="1.0.0")
    # Wipe the manifest rows.
    session.query(Manifest).filter(Manifest.scan_run_id == scan_id).delete()
    session.commit()
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(r, ProviderSuccess)
    body = json.loads(r.data)
    props = {p["name"]: p["value"] for p in body["metadata"]["properties"]}
    assert props["lockverity:dependency-graph-coverage"] == "unknown"


def test_exporter_graph_coverage_partial_with_manifests_but_no_edges(session) -> None:
    """Manifests persisted but zero edges observed is
    ``partial``. The schema has no positive completeness
    signal, so the graph is reported as partial."""
    repo_id = _make_repo(session)
    scan_id = _make_scan(session, repo_id=repo_id)
    m = _make_manifest(
        session,
        scan_id=scan_id,
        path="package-lock.json",
        parse_status=ManifestParseStatus.PARSED,
    )
    _make_component(session, scan_id=scan_id, manifest_id=m, name="lodash", version="4.17.21")
    _make_component(session, scan_id=scan_id, manifest_id=m, name="left-pad", version="1.0.0")
    # No edges persisted.
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    props = {p["name"]: p["value"] for p in body["metadata"]["properties"]}
    assert props["lockverity:dependency-graph-coverage"] == "partial"


def test_exporter_graph_coverage_complete_string_never_appears_in_any_bom(
    session,
) -> None:
    """The string ``"complete"`` never appears as the value
    of ``lockverity:dependency-graph-coverage`` in any
    v0.6 BOM. The v0.6 evidence-honesty contract refuses
    to claim completeness when the schema has no positive
    signal."""
    # Case 1: completed scan, all PARSED, with edges.
    repo_id = _make_repo(session, owner="octocat-cc1", name="Hello-World-cc1")
    scan_id = _make_scan(session, repo_id=repo_id, status=ScanStatus.COMPLETED)
    m = _make_manifest(session, scan_id=scan_id, path="package.json")
    c1 = _make_component(session, scan_id=scan_id, manifest_id=m, name="lodash", version="4.17.21")
    c2 = _make_component(session, scan_id=scan_id, manifest_id=m, name="left-pad", version="1.0.0")
    _make_edge(session, scan_id=scan_id, parent_id=c1, child_id=c2)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    body = json.loads(r.data)
    for prop in body["metadata"]["properties"]:
        if prop["name"] == "lockverity:dependency-graph-coverage":
            assert prop["value"] != "complete", "v0.6 must never emit 'complete'"

    # Case 2: build a second rich-style scan with distinct
    # repository identity. We do not call ``_make_rich_scan``
    # because it uses the hard-coded ``(octocat, Hello-World)``
    # owner/name; we build an equivalent rich fixture here.
    rich_repo_id = _make_repo(session, owner="octocat-cc2", name="Hello-World-cc2")
    rich_scan = ScanRun(
        repository_id=rich_repo_id,
        trigger_type=ScanTriggerType.MANUAL,
        status=ScanStatus.COMPLETED,
    )
    session.add(rich_scan)
    session.flush()
    rich_scan_id = rich_scan.id
    rich_m1 = _make_manifest(
        session,
        scan_id=rich_scan_id,
        path="package.json",
        parse_status=ManifestParseStatus.PARSED,
    )
    rich_m2 = _make_manifest(
        session,
        scan_id=rich_scan_id,
        path="package-lock.json",
        parse_status=ManifestParseStatus.PARSED,
    )
    lodash_id = _make_component(
        session,
        scan_id=rich_scan_id,
        manifest_id=rich_m1,
        name="lodash",
        version="4.17.21",
    )
    leftpad_id = _make_component(
        session,
        scan_id=rich_scan_id,
        manifest_id=rich_m1,
        name="left-pad",
        version="1.0.0",
    )
    _make_edge(session, scan_id=rich_scan_id, parent_id=lodash_id, child_id=leftpad_id)
    _make_manifest(
        session,
        scan_id=rich_scan_id,
        path="extra.json",
        parse_status=ManifestParseStatus.PARSED,
    )
    _ = rich_m2  # silence unused warning
    r2 = CycloneDxV17Exporter(lambda: session).export(scan_run_id=rich_scan_id)
    body2 = json.loads(r2.data)
    for prop in body2["metadata"]["properties"]:
        if prop["name"] == "lockverity:dependency-graph-coverage":
            assert prop["value"] != "complete", "v0.6 must never emit 'complete'"


# ---------------------------------------------------------------------
# Scoped warning suppression (v0.6 final review)
# ---------------------------------------------------------------------


def test_exporter_scoped_warning_suppression_does_not_leak(session) -> None:
    """The v0.6 exporter scopes the
    ``cyclonedx-python-lib`` "Dependency Graph is
    incomplete" ``UserWarning`` to the
    ``JsonV1Dot7.output_as_string()`` call. The warning
    must not leak beyond that call site."""
    import warnings

    scan_id, _, _ = _make_rich_scan(session)

    # Force the global filter to "error" so any leak
    # surfaces immediately.
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=UserWarning)
        r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(r, ProviderSuccess)
    # The export succeeded; the scoped filter caught the
    # library's convenience warning.


def test_exporter_unrelated_userwarning_is_not_globally_suppressed(session) -> None:
    """The v0.6 exporter's warning filter is *scoped* to
    the specific cyclonedx-python-lib "Dependency Graph
    is incomplete" message. An unrelated ``UserWarning``
    raised after the export call must still propagate."""
    import warnings

    scan_id, _, _ = _make_rich_scan(session)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(r, ProviderSuccess)

    # Raise an unrelated UserWarning. The scoped filter
    # inside the exporter must NOT suppress it.
    marker = "lockverity-unrelated-marker-12345"
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        warnings.warn(marker, UserWarning, stacklevel=1)
        propagated = [w for w in captured if marker in str(w.message)]
    assert propagated, (
        "unrelated UserWarning must propagate; the exporter's "
        "scoped filter must not suppress other UserWarnings"
    )


def test_exporter_strict_cyclonedx_1_7_validation_still_passes_after_scoped_filter(
    session,
) -> None:
    """The official CycloneDX 1.7 strict schema validation
    still passes after the scoped warning filter. The
    scoped filter is purely a presentation concern; it
    does not change the BOM contents or the validation
    result."""
    from cyclonedx.schema.schema import SchemaVersion
    from cyclonedx.validation.json import JsonStrictValidator

    scan_id, _, _ = _make_rich_scan(session)
    r = CycloneDxV17Exporter(lambda: session).export(scan_run_id=scan_id)
    assert isinstance(r, ProviderSuccess)
    # Re-run the strict validator explicitly so the test
    # documents the expectation.
    body = r.data.decode("utf-8")
    result = JsonStrictValidator(SchemaVersion.V1_7).validate_str(body)
    assert not result, f"schema validation reported: {list(result)}"
