"""Tests for the manifest discovery analyzer."""

from __future__ import annotations

from app.analyzers.manifest_discovery import ManifestDiscoveryAnalyzer
from app.utils.manifest_scanner import SkipReason

from tests.fixtures import read_fixture_bytes


def test_analyze_returns_no_findings_for_clean_tree() -> None:
    files = [
        ("package.json", read_fixture_bytes("npm/clean/package.json")),
        ("package-lock.json", read_fixture_bytes("npm/clean/package-lock.json")),
    ]
    analyzer = ManifestDiscoveryAnalyzer()
    result = analyzer.analyze(files=files, scan_run_id=1)
    # We only emit data-quality findings for ``unknown_manifest`` /
    # ``ignored_directory`` which are intentionally not findings.
    assert result.findings == ()


def test_analyze_emits_finding_for_skipped_oversized() -> None:
    big = b'{"name":"x"}' + b" " * 100_000
    files = [("package.json", big)]
    analyzer = ManifestDiscoveryAnalyzer(max_manifest_bytes=128)
    result = analyzer.analyze(files=files, scan_run_id=1)
    assert any(f.rule_id == "LOCK-DATA-001" for f in result.findings)
    # Warnings carry a structured ``code`` we can match on.
    assert any(
        getattr(s, "code", None) == f"manifest_skipped_{SkipReason.TOO_LARGE.value}"
        for s in result.warnings
    )


def test_analyze_emits_finding_for_unsafe_path() -> None:
    files = [("../package.json", b"{}")]
    analyzer = ManifestDiscoveryAnalyzer()
    result = analyzer.analyze(files=files, scan_run_id=1)
    # Unsafe paths are recorded as warnings; we don't surface them
    # as findings because they typically indicate a malicious
    # archive that the manifest scanner already rejected.
    assert any(s.code == "manifest_skipped_unsafe_path" for s in result.warnings)


def test_analyze_ignores_node_modules() -> None:
    files = [
        ("node_modules/some-pkg/package.json", b"{}"),
        ("package.json", read_fixture_bytes("npm/clean/package.json")),
    ]
    analyzer = ManifestDiscoveryAnalyzer()
    result = analyzer.analyze(files=files, scan_run_id=1)
    # The node_modules entry is dropped silently.
    assert result.findings == ()


def test_discover_method_returns_deterministic_order() -> None:
    files = [
        ("package.json", b"{}"),
        ("package-lock.json", b"{}"),
        ("requirements.txt", b"foo==1.0\n"),
    ]
    analyzer = ManifestDiscoveryAnalyzer()
    discovery = analyzer.discover(files)
    assert [m.path for m in discovery.manifests] == sorted(m.path for m in discovery.manifests)


def test_discover_uses_content_hash() -> None:
    files = [("package.json", b'{"name": "x"}')]
    analyzer = ManifestDiscoveryAnalyzer()
    discovery = analyzer.discover(files)
    assert len(discovery.manifests) == 1
    digest = discovery.manifests[0].content_sha256
    assert len(digest) == 64
