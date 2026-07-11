"""Tests for :mod:`app.utils.repo_url`."""

from __future__ import annotations

import pytest
from app.utils.repo_url import RepositoryUrlError, normalize_github_url


def test_accepts_canonical_https() -> None:
    out = normalize_github_url("https://github.com/octocat/Hello-World")
    assert out.owner == "octocat"
    assert out.name == "Hello-World"
    assert out.canonical_url == "https://github.com/octocat/Hello-World"


def test_accepts_dot_git_suffix() -> None:
    out = normalize_github_url("https://github.com/octocat/Hello-World.git")
    assert out.name == "Hello-World"


def test_rejects_non_https() -> None:
    for bad in (
        "http://github.com/octocat/Hello-World",
        "git://github.com/octocat/Hello-World",
        "ssh://git@github.com/octocat/Hello-World",
    ):
        with pytest.raises(RepositoryUrlError):
            normalize_github_url(bad)


def test_rejects_non_github_host() -> None:
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://gitlab.com/octocat/Hello-World")
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://example.com/octocat/Hello-World")


def test_rejects_embedded_credentials() -> None:
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://user:pass@github.com/octocat/Hello-World")


def test_rejects_extra_path_segments() -> None:
    for bad in (
        "https://github.com/octocat/Hello-World/tree/main",
        "https://github.com/octocat/Hello-World/blob/main/README.md",
        "https://github.com/octocat/Hello-World/issues",
    ):
        with pytest.raises(RepositoryUrlError):
            normalize_github_url(bad)


def test_rejects_query_and_fragment() -> None:
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://github.com/octocat/Hello-World?ref=abc")
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://github.com/octocat/Hello-World#readme")


def test_rejects_port() -> None:
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://github.com:443/octocat/Hello-World")


def test_rejects_invalid_owner() -> None:
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://github.com/-bad-/Hello-World")
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://github.com/.bad/Hello-World")


def test_rejects_invalid_name() -> None:
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://github.com/octocat/..evil")
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://github.com/octocat/bad..name")
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://github.com/octocat/-bad")
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://github.com/octocat/.bad")


def test_rejects_empty() -> None:
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("")
    with pytest.raises(RepositoryUrlError):
        normalize_github_url("https://github.com/")


def test_is_idempotent() -> None:
    out = normalize_github_url("https://github.com/OctoCat/Hello-World.git")
    again = normalize_github_url(out.canonical_url)
    assert out.canonical_url == again.canonical_url
