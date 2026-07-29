"""Regression tests for the v2.0.4 UTF-8 BOM compatibility fix.

v2.0.3 shipped with ``PackageJsonParser`` and
``PackageLockJsonParser`` decoding the manifest bytes as plain
UTF-8: ``content.decode("utf-8")``. A leading UTF-8 BOM
(``EF BB BF``) — produced by Notepad on Windows and many other
editors — is preserved as a literal ``\ufeff`` in the decoded
string, which ``json.loads`` then rejects. The orchestrator
records the manifest but the parser raises
``ParserError("package.json is not valid JSON: ...")``, the
component record list is empty, and the analysis returns zero
components. The field-test repro saw this twice (scan #6,
scan #7) on ``test-06-package-json-only.zip``: one manifest
discovered, one parser warning, zero components.

v2.0.4 changes the decode to ``utf-8-sig``, which transparently
strips a single leading UTF-8 BOM. The test cases below pin:

1. package.json with UTF-8 BOM parses successfully.
2. The expected direct dependencies (axios 1.7.9, lodash 4.17.21)
   survive the BOM exactly, with no leading invisible
   character polluting names, versions, or PURLs.
3. package-lock.json with UTF-8 BOM parses successfully.
4. The no-BOM control is unchanged.
5. Invalid JSON following a BOM remains a bounded parser
   failure (the BOM is stripped, then the rest is parsed).
6. A BOM-like codepoint in the middle of a string is
   preserved (we do not strip arbitrary invisible characters).
7. Source path and evidence provenance are preserved.
8. Parser warning is not generated merely because of the BOM.
9. End-to-end orchestrator scan produces components rather than
   an empty inventory.
10. A nested BOM package.json is discovered and parsed.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from app.parsers.base import ParserError
from app.parsers.npm import PackageJsonParser, PackageLockJsonParser

# The :func:`conftest._fake_providers_for_scan_tests`
# autouse fixture applies the shared fakes globally; this
# module no longer needs to import the per-module fixture.
# Some tests in this file run the full scan orchestrator
# and rely on the global fakes to keep the test offline.

UTF8_BOM = b"\xef\xbb\xbf"

PACKAGE_JSON_BODY = {
    "name": "lockverity-field-test-package-only",
    "version": "1.0.0",
    "private": True,
    "dependencies": {
        "axios": "1.7.9",
        "lodash": "4.17.21",
    },
}


def _with_bom(payload: bytes) -> bytes:
    """Return ``payload`` prefixed with a single UTF-8 BOM."""
    return UTF8_BOM + payload


# ---- package.json with UTF-8 BOM ----


def test_package_json_with_utf8_bom_parses_successfully() -> None:
    """A package.json prefixed with a UTF-8 BOM is parsed as a manifest."""
    parser = PackageJsonParser()
    body = json.dumps(PACKAGE_JSON_BODY).encode("utf-8")
    result = parser.parse(content=_with_bom(body), path="package.json")
    assert result.records_processed == 2
    assert result.warnings == ()


def test_package_json_bom_yields_expected_two_direct_dependencies() -> None:
    """Both direct dependencies survive the BOM exactly."""
    parser = PackageJsonParser()
    body = json.dumps(PACKAGE_JSON_BODY).encode("utf-8")
    result = parser.parse(content=_with_bom(body), path="package.json")
    by_name = {r["package_name"]: r for r in result.data}
    assert set(by_name) == {"axios", "lodash"}
    assert by_name["axios"]["version"] == "1.7.9"
    assert by_name["lodash"]["version"] == "4.17.21"


def test_package_json_bom_names_versions_and_purls_are_clean() -> None:
    """The BOM must not become part of a name, version, or PURL."""
    parser = PackageJsonParser()
    body = json.dumps(PACKAGE_JSON_BODY).encode("utf-8")
    result = parser.parse(content=_with_bom(body), path="package.json")
    for record in result.data:
        assert "\ufeff" not in record["package_name"]
        assert record["version"] is None or "\ufeff" not in record["version"]
        if record["package_url"] is not None:
            assert "\ufeff" not in record["package_url"]
            assert "%EF%BB%BF" not in record["package_url"]
    by_name = {r["package_name"]: r for r in result.data}
    assert by_name["axios"]["package_url"] == "pkg:npm/axios@1.7.9"
    assert by_name["lodash"]["package_url"] == "pkg:npm/lodash@4.17.21"


def test_package_json_bom_sets_relationship_direct() -> None:
    """BOM does not change the dependency relationship classification."""
    parser = PackageJsonParser()
    body = json.dumps(PACKAGE_JSON_BODY).encode("utf-8")
    result = parser.parse(content=_with_bom(body), path="package.json")
    for record in result.data:
        assert record["relationship"] == "direct"
        assert record["direct"] is True
        assert record["development"] is False
        assert record["optional"] is False


def test_package_json_bom_source_path_is_preserved() -> None:
    """The source path and provenance are not mutated by BOM handling."""
    parser = PackageJsonParser()
    body = json.dumps({"name": "x", "version": "1.0.0", "dependencies": {"axios": "1.7.9"}}).encode(
        "utf-8"
    )
    result = parser.parse(content=_with_bom(body), path="frontend/package.json")
    record = result.data[0]
    assert record["source_path"] == "frontend/package.json"


def test_package_json_without_bom_remains_unchanged() -> None:
    """The no-BOM control path is unchanged by the v2.0.4 fix."""
    parser = PackageJsonParser()
    body = json.dumps(
        {"name": "x", "version": "1.0.0", "dependencies": {"lodash": "4.17.21"}}
    ).encode("utf-8")
    result = parser.parse(content=body, path="package.json")
    assert result.records_processed == 1
    record = result.data[0]
    assert record["package_name"] == "lodash"
    assert record["version"] == "4.17.21"
    assert record["package_url"] == "pkg:npm/lodash@4.17.21"
    assert result.warnings == ()


# ---- package-lock.json with UTF-8 BOM ----


def test_package_lock_json_with_utf8_bom_parses_successfully() -> None:
    """A package-lock.json prefixed with a UTF-8 BOM is parsed as a manifest."""
    parser = PackageLockJsonParser()
    body = json.dumps(
        {
            "name": "lockverity-field-test-package-only",
            "version": "1.0.0",
            "lockfileVersion": 3,
            "packages": {
                "node_modules/axios": {"version": "1.7.9"},
                "node_modules/lodash": {"version": "4.17.21"},
            },
        }
    ).encode("utf-8")
    result = parser.parse(content=_with_bom(body), path="package-lock.json")
    by_name = {r["package_name"] for r in result.data}
    assert by_name == {"axios", "lodash"}
    for record in result.data:
        assert "\ufeff" not in record["package_name"]


# ---- negative cases ----


def test_package_json_bom_followed_by_invalid_json_still_fails() -> None:
    """A BOM is stripped; the remaining bytes are still validated as JSON."""
    parser = PackageJsonParser()
    with pytest.raises(ParserError):
        parser.parse(content=_with_bom(b"{not-json"), path="package.json")


def test_package_json_bom_like_codepoint_in_middle_of_string_is_preserved() -> None:
    """A BOM-like codepoint inside a string value is not silently removed.

    ``utf-8-sig`` only strips a *leading* BOM. A mid-string
    ``\\uFEFF`` (the same codepoint as a UTF-8 BOM, expressed
    here via a JSON escape) must survive verbatim so we do not
    silently rewrite package metadata.
    """
    parser = PackageJsonParser()
    weird_name = "weird\ufeffname"
    body = json.dumps(
        {
            "name": "x",
            "version": "1.0.0",
            "dependencies": {weird_name: "1.0.0"},
        }
    ).encode("utf-8")
    result = parser.parse(content=body, path="package.json")
    by_name = {r["package_name"]: r for r in result.data}
    assert weird_name in by_name


# ---- end-to-end orchestrator with a BOM-prefixed package.json ----


def test_orchestrator_scan_with_bom_package_json_produces_components(
    app_config, workspace_root
) -> None:
    """A full scan with a BOM-prefixed package.json produces components.

    This test materialises a workspace, plants a BOM-prefixed
    package.json in the contents directory, runs the orchestrator
    end-to-end, and asserts that the components table contains
    the expected packages (axios 1.7.9, lodash 4.17.21).

    Pre-v2.0.4 4 behaviour: parser raises ``ParserError("package.json
    is not valid JSON: Expecting value: line 1 column 1
    (char 0)")``, the manifest is recorded with parse_status
    ``NOT_PARSED`` (or ``PARTIAL`` with one warning), and
    zero components are created.
    """
    from app.db import session as _db_session
    from app.models.scan_run import ScanStatus, ScanTriggerType
    from app.models.workspace import WorkspaceKind, WorkspaceState
    from app.services import repository_service, scan_service
    from app.services.orchestrator_service import ScanOrchestrator
    from app.services.workspace_service import WorkspaceService

    body = json.dumps(PACKAGE_JSON_BODY).encode("utf-8")
    bom_bytes = _with_bom(body)

    with _db_session.SessionLocal() as s:
        repo = repository_service.create_repository_from_url(
            s, "https://github.com/octocat/Hello-World"
        )
        scan = scan_service.create_scan(
            s, repository_id=repo.id, trigger_type=ScanTriggerType.MANUAL
        )
        workspaces = WorkspaceService(s)
        workspace = workspaces.create_for_scan(scan, kind=WorkspaceKind.GITHUB)
        paths = workspaces.paths_for(workspace.workspace_key)
        paths.contents_dir.mkdir(parents=True, exist_ok=True)
        (paths.contents_dir / "package.json").write_bytes(bom_bytes)
        workspaces.transition(workspace, target=WorkspaceState.VALIDATING)
        workspaces.transition(
            workspace,
            target=WorkspaceState.READY,
            archive_sha256="b" * 64,
            archive_size=len(bom_bytes),
            file_count=1,
            uncompressed_size=len(bom_bytes),
        )
        s.commit()
        scan_id = scan.id

    orchestrator = ScanOrchestrator(_db_session.SessionLocal)
    outcome = orchestrator.run(scan_id)
    # The external providers (OSV, deps.dev, OpenSSF
    # Scorecard) are faked as unavailable by the
    # shared autouse fixture. Local work still
    # completes; the terminal status is ``partial``
    # rather than ``completed`` because the
    # provider-backed stages recorded honest
    # ``provider_unavailable`` observations.
    assert outcome.final_status in {ScanStatus.COMPLETED, ScanStatus.PARTIAL}

    with _db_session.SessionLocal() as s:
        from app.models.component import Component
        from app.models.manifest import Manifest

        components = s.query(Component).filter(Component.scan_run_id == scan_id).all()
        names = {c.package_name for c in components}
        assert "axios" in names
        assert "lodash" in names
        versions = {c.package_name: c.version for c in components}
        assert versions["axios"] == "1.7.9"
        assert versions["lodash"] == "4.17.21"

        # No BOM-related parser warning; the parse is clean.
        manifests = s.query(Manifest).filter(Manifest.scan_run_id == scan_id).all()
        bom_manifest = next((m for m in manifests if m.manifest_type == "package_json"), None)
        assert bom_manifest is not None
        # ``parse_status`` is the SQLAlchemy enum's ``value`` (lowercase);
        # for a successful BOM-stripped parse the orchestrator records
        # ``ManifestParseStatus.PARSED`` whose value is ``"parsed"``.
        assert bom_manifest.parse_status.value == "parsed"


def test_nested_bom_package_json_is_discovered_and_parsed(tmp_path: Path) -> None:
    """A nested ``frontend/package.json`` with a BOM is still parsed.

    This pins the interaction between the orchestrator's
    basename-based manifest discovery (the v2.0.2 fix) and the
    parser-level BOM handling (the v2.0.4 fix).
    """
    body = json.dumps(PACKAGE_JSON_BODY).encode("utf-8")
    bom_bytes = _with_bom(body)

    zip_path = tmp_path / "nested-bom.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("frontend/package.json", bom_bytes)
        zf.writestr("README.md", "# nested BOM test\n")

    contents_dir = tmp_path / "contents"
    contents_dir.mkdir()
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(contents_dir)

    from app.services.orchestrator_service import _discover_manifest_files

    found = _discover_manifest_files(contents_dir)
    assert "frontend/package.json" in found

    nested = (contents_dir / "frontend" / "package.json").read_bytes()
    parser = PackageJsonParser()
    result = parser.parse(content=nested, path="frontend/package.json")
    assert result.records_processed == 2
    by_name = {r["package_name"]: r for r in result.data}
    assert by_name["axios"]["version"] == "1.7.9"
    assert by_name["lodash"]["version"] == "4.17.21"
