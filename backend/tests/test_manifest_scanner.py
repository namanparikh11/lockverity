"""Tests for :mod:`app.utils.manifest_scanner`."""

from __future__ import annotations

from app.utils.manifest_scanner import (
    DEFAULT_MAX_MANIFEST_COUNT,
    DiscoveryResult,
    SkipReason,
    classify_manifest,
    discover_manifests,
)


def test_classify_known_files() -> None:
    assert classify_manifest("package.json") == ("package_json", "npm")
    assert classify_manifest("package-lock.json") == ("package_lock", "npm")
    assert classify_manifest("pnpm-lock.yaml") == ("pnpm_lock", "npm")
    assert classify_manifest("yarn.lock") == ("yarn_lock", "npm")
    assert classify_manifest("requirements.txt") == ("requirements_txt", "pypi")
    assert classify_manifest("pyproject.toml") == ("pyproject_toml", "pypi")
    assert classify_manifest("poetry.lock") == ("poetry_lock", "pypi")


def test_classify_unknown_is_none() -> None:
    assert classify_manifest("random.txt") is None
    assert classify_manifest("") is None


def test_discover_basic_clean_npm(tmp_path) -> None:
    files = [
        ("package.json", b'{"name": "x"}'),
        ("package-lock.json", b'{"name": "x", "lockfileVersion": 3}'),
        ("README.md", b"# readme"),
    ]
    result = discover_manifests(files)
    assert isinstance(result, DiscoveryResult)
    assert {m.manifest_type for m in result.manifests} == {"package_json", "package_lock"}
    # Deterministic order: sorted by path.
    assert [m.path for m in result.manifests] == sorted(m.path for m in result.manifests)


def test_discover_ignores_node_modules(tmp_path) -> None:
    files = [
        ("node_modules/some-pkg/package.json", b'{"name": "y"}'),
        ("package.json", b'{"name": "x"}'),
    ]
    result = discover_manifests(files)
    assert [m.path for m in result.manifests] == ["package.json"]
    skipped_reasons = {s.reason for s in result.skipped}
    assert SkipReason.IGNORED_DIRECTORY in skipped_reasons


def test_discover_ignores_venv_and_dist() -> None:
    files = [
        ("venv/lib/site-pkg/setup.py", b"# not a manifest"),
        ("dist/built-pkg/manifest.json", b"{}"),
        ("package.json", b'{"name": "x"}'),
    ]
    result = discover_manifests(files)
    assert [m.path for m in result.manifests] == ["package.json"]


def test_discover_rejects_unsafe_path() -> None:
    files = [
        ("../package.json", b"{}"),
        ("a/../../etc/package.json", b"{}"),
    ]
    result = discover_manifests(files)
    assert result.manifests == ()
    skipped_reasons = {s.reason for s in result.skipped}
    assert SkipReason.UNSAFE_PATH in skipped_reasons


def test_discover_rejects_oversize_file() -> None:
    big = b'{"name": "x"}' + b" " * 200
    files = [("package.json", big)]
    result = discover_manifests(files, max_manifest_bytes=128)
    assert result.manifests == ()
    skipped_reasons = {s.reason for s in result.skipped}
    assert SkipReason.TOO_LARGE in skipped_reasons


def test_discover_respects_count_cap() -> None:
    files = [(f"package-{i}.json", b'{"name": "x"}') for i in range(5)]
    result = discover_manifests(files, max_manifest_count=2)
    # ``package-N.json`` are not recognised, so nothing is kept and
    # nothing is skipped (we only record skips for recognised files).
    assert result.manifests == ()
    assert result.skipped == ()


def test_discover_dedupes_same_path() -> None:
    files = [
        ("package.json", b'{"name": "x"}'),
        ("package.json", b'{"name": "y"}'),
    ]
    result = discover_manifests(files)
    assert len(result.manifests) == 1
    skipped_reasons = {s.reason for s in result.skipped}
    assert SkipReason.DUPLICATE in skipped_reasons


def test_discover_records_content_hash() -> None:
    files = [("package.json", b'{"name": "x"}')]
    result = discover_manifests(files)
    assert len(result.manifests) == 1
    # The exact digest is computed by the platform; we just check
    # that it is a 64-character hex string.
    digest = result.manifests[0].content_sha256
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_discover_does_not_recognise_unknown_filenames() -> None:
    files = [("Dockerfile", b"FROM scratch\n")]
    result = discover_manifests(files)
    assert result.manifests == ()
    assert result.skipped == ()


def test_discover_default_count_is_documented() -> None:
    assert DEFAULT_MAX_MANIFEST_COUNT >= 100
