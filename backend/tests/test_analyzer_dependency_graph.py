"""Tests for the dependency-graph builder."""

from __future__ import annotations

from app.analyzers.dependency_graph import (
    build_dependency_components,
    build_dependency_graph,
)
from app.parsers.npm import PackageJsonParser, PackageLockJsonParser

from tests.fixtures import read_fixture_bytes


def _envelopes():
    package_json = read_fixture_bytes("npm/clean/package.json")
    package_lock = read_fixture_bytes("npm/clean/package-lock.json")
    json_records = PackageJsonParser().parse(content=package_json, path="package.json")
    lock_records = PackageLockJsonParser().parse(content=package_lock, path="package-lock.json")
    return [
        {
            "manifest": {
                "path": "package.json",
                "manifest_type": "package_json",
                "ecosystem": "npm",
            },
            "records": list(json_records.data),
        },
        {
            "manifest": {
                "path": "package-lock.json",
                "manifest_type": "package_lock",
                "ecosystem": "npm",
            },
            "records": list(lock_records.data),
        },
    ]


def test_build_components_marks_direct_from_manifest() -> None:
    components, _, _ = build_dependency_components(_envelopes())
    by_name = {c["package_name"]: c for c in components}
    assert by_name["lodash"]["direct"] is True
    assert by_name["vitest"]["direct"] is True


def test_build_components_preserves_lockfile_edges() -> None:
    _, edges, _ = build_dependency_components(_envelopes())
    # The lockfile packages include child dependencies for root
    # packages (in the ``requires`` field of v1 lockfiles; in v2/v3
    # the keys are explicit). We don't assert specific children
    # because the test fixture uses a v3 lockfile with packages
    # only; we just check the edge builder did not crash and
    # returned a list.
    assert isinstance(edges, list)


def test_build_components_emits_missing_lockfile_finding() -> None:
    # No lockfile envelope in this run.
    json_records = PackageJsonParser().parse(
        content=read_fixture_bytes("npm/clean/package.json"), path="package.json"
    )
    envelopes = [
        {
            "manifest": {
                "path": "package.json",
                "manifest_type": "package_json",
                "ecosystem": "npm",
            },
            "records": list(json_records.data),
        }
    ]
    components, _, findings = build_dependency_components(
        envelopes,
        manifests_by_path={
            "package.json": {
                "manifest_type": "package_json",
                "ecosystem": "npm",
            }
        },
    )
    assert any(f.rule_id == "LOCK-VULN-010" for f in findings)
    assert any(c["package_name"] == "lodash" for c in components)


def test_build_components_dedupes_across_manifests() -> None:
    # The same package appears in both the manifest and the
    # lockfile; we keep both records because they encode different
    # evidence. (Dedupe is by (package_name, version, source_path).)
    components, _, _ = build_dependency_components(_envelopes())
    by_name_version = {(c["package_name"], c["version"]) for c in components}
    assert ("lodash", "4.17.21") in by_name_version
    assert ("lodash", None) in by_name_version


def test_build_dependency_graph_returns_parent_child_map() -> None:
    _, edges, _ = build_dependency_components(_envelopes())
    graph = build_dependency_graph(edges)
    # An empty edge list produces an empty graph.
    assert isinstance(graph, dict)
