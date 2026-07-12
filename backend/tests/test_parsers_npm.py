"""Tests for the npm parsers."""

from __future__ import annotations

import json

import pytest
from app.parsers import npm as npm_parser
from app.parsers.base import ParserError
from app.parsers.npm import PackageJsonParser, PackageLockJsonParser

from tests.fixtures import read_fixture_bytes


def test_package_json_basic_direct_deps() -> None:
    parser = PackageJsonParser()
    content = json.dumps(
        {
            "name": "x",
            "version": "1.0.0",
            "dependencies": {"lodash": "^4.17.21", "left-pad": "1.3.0"},
            "devDependencies": {"vitest": "^1.0.0"},
            "optionalDependencies": {"fsevents": "^2.3.0"},
        }
    ).encode("utf-8")
    result = parser.parse(content=content, path="package.json")
    assert result.records_processed == 4
    by_name = {r["package_name"]: r for r in result.data}
    assert by_name["lodash"]["relationship"] == "direct"
    assert by_name["lodash"]["version_source"] == "UNRESOLVED"
    assert by_name["lodash"]["direct"] is True
    assert by_name["left-pad"]["version_source"] == "MANIFEST"
    assert by_name["left-pad"]["version"] == "1.3.0"
    assert by_name["vitest"]["development"] is True
    assert by_name["fsevents"]["optional"] is True


def test_package_json_scoped_packages() -> None:
    parser = PackageJsonParser()
    content = json.dumps(
        {
            "name": "x",
            "dependencies": {"@scope/pkg": "^1.0.0"},
        }
    ).encode("utf-8")
    result = parser.parse(content=content, path="package.json")
    record = result.data[0]
    assert record["package_name"] == "@scope/pkg"
    assert record["scope"] == "scope"
    assert record["package_url"] == "pkg:npm/@scope/pkg"


def test_package_json_unsupported_git_ref() -> None:
    parser = PackageJsonParser()
    content = json.dumps(
        {
            "name": "x",
            "dependencies": {"internal": "git+https://github.com/example/internal.git"},
        }
    ).encode("utf-8")
    result = parser.parse(content=content, path="package.json")
    record = result.data[0]
    assert record["is_unsupported"] is True
    assert record["unsupported_kind"] == "git_ref"
    assert record["version"] is None
    assert record["version_source"] == "UNRESOLVED"


def test_package_json_unsupported_url_ref() -> None:
    parser = PackageJsonParser()
    content = json.dumps(
        {
            "name": "x",
            "dependencies": {"tarball": "https://example.com/pkg-1.0.0.tgz"},
        }
    ).encode("utf-8")
    result = parser.parse(content=content, path="package.json")
    record = result.data[0]
    assert record["is_unsupported"] is True
    assert record["unsupported_kind"] == "url_ref"


def test_package_json_unsupported_workspace_ref() -> None:
    parser = PackageJsonParser()
    content = json.dumps(
        {
            "name": "x",
            "dependencies": {"local": "workspace:*"},
        }
    ).encode("utf-8")
    result = parser.parse(content=content, path="package.json")
    record = result.data[0]
    assert record["is_unsupported"] is True
    assert record["unsupported_kind"] == "workspace_ref"


def test_package_json_workspaces_emit_globs() -> None:
    parser = PackageJsonParser()
    content = json.dumps({"name": "x", "workspaces": ["packages/*"]}).encode("utf-8")
    result = parser.parse(content=content, path="package.json")
    globs = [r for r in result.data if r["kind"] == "workspace_glob"]
    assert globs and globs[0]["package_name"] == "packages/*"


def test_package_json_invalid_json_raises() -> None:
    parser = PackageJsonParser()
    with pytest.raises(ParserError):
        parser.parse(content=b"{not-json", path="package.json")


def test_package_json_root_not_object_raises() -> None:
    parser = PackageJsonParser()
    with pytest.raises(ParserError):
        parser.parse(content=b"[]", path="package.json")


def test_package_lock_v3_resolves_packages() -> None:
    parser = PackageLockJsonParser()
    content = read_fixture_bytes("npm/clean/package-lock.json")
    result = parser.parse(content=content, path="package-lock.json")
    by_name = {r["package_name"]: r for r in result.data}
    assert by_name["lodash"]["version_source"] == "LOCKFILE"
    assert by_name["lodash"]["version"] == "4.17.21"
    assert by_name["lodash"]["integrity"].startswith("sha512-")
    assert by_name["lodash"]["package_url"] == "pkg:npm/lodash@4.17.21"
    assert by_name["vitest"]["development"] is True
    # The lockfile does not know the direct/transitive distinction
    # for the root package; we leave that to the dependency_graph
    # analyzer.
    assert by_name["lodash"]["direct"] is False


def test_package_lock_v1_resolves_dependencies() -> None:
    parser = PackageLockJsonParser()
    content = json.dumps(
        {
            "name": "x",
            "lockfileVersion": 1,
            "dependencies": {
                "lodash": {
                    "version": "4.17.21",
                    "resolved": "https://registry.npmjs.org/lodash/-/lodash-4.17.21.tgz",
                    "integrity": "sha512-...",
                }
            },
        }
    ).encode("utf-8")
    result = parser.parse(content=content, path="package-lock.json")
    record = result.data[0]
    assert record["package_name"] == "lodash"
    assert record["version"] == "4.17.21"
    assert record["version_source"] == "LOCKFILE"


def test_package_lock_malformed_warns() -> None:
    parser = PackageLockJsonParser()
    content = read_fixture_bytes("npm/malformed_lock/package-lock.json")
    result = parser.parse(content=content, path="package-lock.json")
    # The record missing 'name' and 'version' is dropped; the empty
    # ``oops`` package contributes no records because the value is
    # not a dict.
    assert result.records_processed == 0
    assert any(w.code == "package_lock_no_entries" for w in result.warnings)


def test_package_lock_invalid_json_raises() -> None:
    parser = PackageLockJsonParser()
    with pytest.raises(ParserError):
        parser.parse(content=b"{not-json", path="package-lock.json")


def test_npm_parse_dependencies_helper_matches_class() -> None:
    content = json.dumps({"name": "x", "dependencies": {"a": "^1"}}).encode("utf-8")
    out = npm_parser.npm_parse_dependencies(content, "package.json")
    assert out.records_processed == 1
    assert out.data[0]["package_name"] == "a"


def test_npm_parse_lock_helper_matches_class() -> None:
    out = npm_parser.npm_parse_lock(b'{"name": "x", "lockfileVersion": 1}', "package-lock.json")
    assert out.records_processed == 0
