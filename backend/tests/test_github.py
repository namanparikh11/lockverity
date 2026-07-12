"""Tests for :mod:`app.utils.github`."""

from __future__ import annotations

from app.utils.github import (
    GITHUB_DOWNLOAD_HOSTS,
    github_api_repo_url,
    github_tarball_url,
    is_commit_sha,
    is_valid_ref,
)
from app.utils.repo_url import NormalizedRepositoryUrl


def test_is_valid_ref_accepts_branch() -> None:
    assert is_valid_ref("main")
    assert is_valid_ref("feature/foo")
    assert is_valid_ref("v1.0.0")
    assert is_valid_ref("release-2024-01-01")


def test_is_valid_ref_rejects_bad_inputs() -> None:
    assert not is_valid_ref("")
    assert not is_valid_ref("-leading-dash")
    assert not is_valid_ref("..")
    assert not is_valid_ref("refs/heads/main")
    assert not is_valid_ref("/leading-slash")
    assert not is_valid_ref("with\x00null")
    assert not is_valid_ref("parent/../escape")


def test_is_commit_sha_accepts_only_hex() -> None:
    assert is_commit_sha("0123456789abcdef0123456789abcdef01234567")
    assert is_commit_sha("abcdef0")
    assert not is_commit_sha("XYZ123")
    assert not is_commit_sha("12345")
    assert not is_commit_sha("")


def test_github_api_repo_url() -> None:
    normalized = NormalizedRepositoryUrl(
        host="github.com",
        owner="octocat",
        name="Hello-World",
        canonical_url="https://github.com/octocat/Hello-World",
    )
    assert github_api_repo_url(normalized) == "https://api.github.com/repos/octocat/Hello-World"


def test_github_tarball_url_with_sha() -> None:
    normalized = NormalizedRepositoryUrl(
        host="github.com",
        owner="octocat",
        name="Hello-World",
        canonical_url="https://github.com/octocat/Hello-World",
    )
    sha = "0123456789abcdef0123456789abcdef01234567"
    url = github_tarball_url(normalized, ref=sha)
    assert url == f"https://codeload.github.com/octocat/Hello-World/tar.gz/{sha}"


def test_github_tarball_url_defaults_to_head() -> None:
    normalized = NormalizedRepositoryUrl(
        host="github.com",
        owner="octocat",
        name="Hello-World",
        canonical_url="https://github.com/octocat/Hello-World",
    )
    url = github_tarball_url(normalized)
    assert url == "https://codeload.github.com/octocat/Hello-World/tar.gz/HEAD"


def test_github_download_hosts_contains_both_hosts() -> None:
    assert "api.github.com" in GITHUB_DOWNLOAD_HOSTS
    assert "codeload.github.com" in GITHUB_DOWNLOAD_HOSTS
