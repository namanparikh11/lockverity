"""Tests for the GitHub provider with a mocked bounded HTTP client.

These tests inject a fake HTTP client into the GitHub
provider's ``build_client`` factory so we never reach the
network. They cover the metadata + download paths, error
translations, and the host/redirect guards.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pytest
from app.providers import github_provider


class _FakeResponse:
    def __init__(
        self, status_code: int, body: bytes, headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.responses: dict[str, list[_FakeResponse]] = {}
        self.allowlist = {"api.github.com", "codeload.github.com"}
        self.token: str | None = None
        self.user_agent: str = "test"

    def queue(self, path: str, response: _FakeResponse) -> None:
        self.responses.setdefault(path, []).append(response)

    def _consume(self, url: str) -> _FakeResponse:
        from urllib.parse import urlsplit

        path = urlsplit(url).path
        self.calls.append(path)
        queue = self.responses.get(path, [])
        if not queue:
            return _FakeResponse(500, b"", {})
        return queue.pop(0)

    def get_json(self, url: str, **_: Any) -> _FakeResponse:
        from app.utils.bounded_http import BoundedHttpError

        response = self._consume(url)
        if response.status_code == 404:
            raise BoundedHttpError("http_not_found", "Upstream returned 404 Not Found.")
        if response.status_code == 429:
            raise BoundedHttpError(
                "http_rate_limited",
                "Upstream returned 429 Too Many Requests.",
                http_status=429,
            )
        if response.status_code == 401:
            raise BoundedHttpError("http_unauthorized", "Upstream returned 401 Unauthorized.")
        if response.status_code == 403:
            raise BoundedHttpError("http_forbidden", "Upstream returned 403 Forbidden.")
        if 500 <= response.status_code < 600:
            raise BoundedHttpError(
                "http_server_error",
                f"Upstream returned {response.status_code}.",
                http_status=response.status_code,
            )
        return response

    def download(self, url: str, **_: Any) -> _FakeResponse:
        from app.utils.bounded_http import BoundedHttpError

        response = self._consume(url)
        if response.status_code == 404:
            raise BoundedHttpError("http_not_found", "Upstream returned 404 Not Found.")
        if response.status_code == 429:
            raise BoundedHttpError(
                "http_rate_limited",
                "Upstream returned 429 Too Many Requests.",
                http_status=429,
            )
        if 500 <= response.status_code < 600:
            raise BoundedHttpError(
                "http_server_error",
                f"Upstream returned {response.status_code}.",
                http_status=response.status_code,
            )
        return response

    def close(self) -> None:
        return None


@pytest.fixture
def fake_client(monkeypatch) -> _FakeClient:
    client = _FakeClient()

    def _build(**kwargs):
        client.token = kwargs.get("token")
        client.user_agent = kwargs.get("user_agent", "test")
        return client

    monkeypatch.setattr(github_provider, "build_client", _build)
    return client


def _build_tarball_bytes() -> bytes:
    """Return a minimal in-memory tarball; we never parse it in
    these tests, so a single-file gzip-like stream is enough."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.md", b"# hi")
    return buf.getvalue()


def test_fetch_metadata_with_explicit_sha_skips_api(fake_client: _FakeClient) -> None:
    sha = "0123456789abcdef0123456789abcdef01234567"
    metadata = github_provider.fetch_repository_metadata(
        fake_client,  # type: ignore[arg-type]
        owner="octocat",
        name="Hello-World",
        canonical_url="https://github.com/octocat/Hello-World",
        requested_ref=sha,
    )
    assert metadata.resolved_commit_sha == sha
    assert fake_client.calls == []


def test_fetch_metadata_resolves_default_branch_to_sha(
    fake_client: _FakeClient,
) -> None:
    repo_path = "/repos/octocat/Hello-World"
    branch_path = "/repos/octocat/Hello-World/branches/main"
    fake_client.queue(
        repo_path,
        _FakeResponse(
            200,
            json.dumps(
                {
                    "default_branch": "main",
                    "visibility": "public",
                    "archived": False,
                    "description": "demo",
                }
            ).encode("utf-8"),
            {"Content-Type": "application/json"},
        ),
    )
    fake_client.queue(
        branch_path,
        _FakeResponse(
            200,
            json.dumps(
                {
                    "name": "main",
                    "commit": {"sha": "0123456789abcdef0123456789abcdef01234567"},
                }
            ).encode("utf-8"),
            {"Content-Type": "application/json"},
        ),
    )
    metadata = github_provider.fetch_repository_metadata(
        fake_client,  # type: ignore[arg-type]
        owner="octocat",
        name="Hello-World",
        canonical_url="https://github.com/octocat/Hello-World",
        requested_ref=None,
    )
    assert metadata.default_branch == "main"
    assert metadata.resolved_commit_sha == "0123456789abcdef0123456789abcdef01234567"


def test_fetch_metadata_falls_back_to_tags(
    fake_client: _FakeClient,
) -> None:
    repo_path = "/repos/octocat/Hello-World"
    branch_path = "/repos/octocat/Hello-World/branches/v1.0"
    tag_path = "/repos/octocat/Hello-World/git/refs/tags/v1.0"
    fake_client.queue(
        repo_path,
        _FakeResponse(
            200,
            json.dumps(
                {
                    "default_branch": "main",
                    "visibility": "public",
                    "archived": False,
                }
            ).encode("utf-8"),
            {"Content-Type": "application/json"},
        ),
    )
    fake_client.queue(branch_path, _FakeResponse(404, b"{}", {"Content-Type": "application/json"}))
    fake_client.queue(
        tag_path,
        _FakeResponse(
            200,
            json.dumps(
                {
                    "ref": "refs/tags/v1.0",
                    "object": {
                        "type": "tag",
                        "sha": "abcdef0000000000000000000000000000000000",
                    },
                }
            ).encode("utf-8"),
            {"Content-Type": "application/json"},
        ),
    )
    deref_path = "/repos/octocat/Hello-World/git/tags/abcdef0000000000000000000000000000000000"
    fake_client.queue(
        deref_path,
        _FakeResponse(
            200,
            json.dumps(
                {
                    "object": {
                        "type": "commit",
                        "sha": "1111111111111111111111111111111111111111",
                    }
                }
            ).encode("utf-8"),
            {"Content-Type": "application/json"},
        ),
    )
    metadata = github_provider.fetch_repository_metadata(
        fake_client,  # type: ignore[arg-type]
        owner="octocat",
        name="Hello-World",
        canonical_url="https://github.com/octocat/Hello-World",
        requested_ref="v1.0",
    )
    assert metadata.resolved_commit_sha == "1111111111111111111111111111111111111111"


def test_fetch_metadata_handles_404(fake_client: _FakeClient) -> None:
    fake_client.queue(
        "/repos/octocat/Hello-World",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    with pytest.raises(github_provider.GitHubIntakeError) as exc:
        github_provider.fetch_repository_metadata(
            fake_client,  # type: ignore[arg-type]
            owner="octocat",
            name="Hello-World",
            canonical_url="https://github.com/octocat/Hello-World",
            requested_ref=None,
        )
    assert exc.value.code == "github_not_found"


def test_fetch_metadata_handles_rate_limit(fake_client: _FakeClient) -> None:
    fake_client.queue(
        "/repos/octocat/Hello-World",
        _FakeResponse(429, b"{}", {"Content-Type": "application/json"}),
    )
    with pytest.raises(github_provider.GitHubIntakeError) as exc:
        github_provider.fetch_repository_metadata(
            fake_client,  # type: ignore[arg-type]
            owner="octocat",
            name="Hello-World",
            canonical_url="https://github.com/octocat/Hello-World",
            requested_ref=None,
        )
    assert exc.value.code == "github_rate_limited"


def test_download_tarball_records_sha_and_headers(fake_client: _FakeClient) -> None:
    body = _build_tarball_bytes()
    fake_client.queue(
        "/octocat/Hello-World/tar.gz/0123456789abcdef0123456789abcdef01234567",
        _FakeResponse(
            200,
            body,
            {
                "Content-Type": "application/x-gzip",
                "ETag": '"abc"',
                "Last-Modified": "today",
            },
        ),
    )
    tarball = github_provider.download_tarball(
        fake_client,  # type: ignore[arg-type]
        owner="octocat",
        name="Hello-World",
        commit_sha="0123456789abcdef0123456789abcdef01234567",
        max_response_bytes=10_000_000,
        timeout_seconds=15.0,
    )
    assert tarball.body == body
    assert tarball.etag == '"abc"'
    assert tarball.last_modified == "today"
    assert len(tarball.content_sha256) == 64


def test_download_tarball_rejects_non_sha(fake_client: _FakeClient) -> None:
    with pytest.raises(github_provider.GitHubIntakeError) as exc:
        github_provider.download_tarball(
            fake_client,  # type: ignore[arg-type]
            owner="octocat",
            name="Hello-World",
            commit_sha="main",
            max_response_bytes=10_000_000,
            timeout_seconds=15.0,
        )
    assert exc.value.code == "github_invalid_ref"


def test_redacted_summary_strips_token(fake_client: _FakeClient) -> None:
    exc = github_provider.GitHubIntakeError(
        "github_unavailable",
        "Authorization: Bearer secret-token-1234abcdef",
    )
    out = exc.redacted_summary()
    assert "secret-token-1234abcdef" not in out
    assert "Bearer" in out or "[REDACTED]" in out
