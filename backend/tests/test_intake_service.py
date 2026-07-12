"""Tests for the IntakeService."""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from typing import Any

import pytest
from app.db import session as _db_session
from app.models.repository import (
    RepositoryProvider,
    RepositorySourceType,
    RepositoryVisibility,
)
from app.models.workspace import WorkspaceKind, WorkspaceState
from app.providers import github_provider
from app.services.intake_service import (
    GitHubIntakeRequest,
    IntakeService,
)
from app.utils.errors import ApiError, ApiErrorCode


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
        return client

    monkeypatch.setattr(github_provider, "build_client", _build)
    return client


def _build_tarball_bytes() -> bytes:
    """Build a real gzip-compressed tar archive containing a single README."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"# hi"
        import tarfile as _tf

        info = _tf.TarInfo("README.md")
        info.size = len(data)
        import io as _io

        tf.addfile(info, _io.BytesIO(data))
    return buf.getvalue()


def test_intake_github_happy_path(app_config, workspace_root, fake_client: _FakeClient) -> None:
    sha = "0123456789abcdef0123456789abcdef01234567"
    fake_client.queue(
        "/repos/octocat/Hello-World",
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
    fake_client.queue(
        "/repos/octocat/Hello-World/branches/main",
        _FakeResponse(
            200,
            json.dumps(
                {
                    "name": "main",
                    "commit": {"sha": sha},
                }
            ).encode("utf-8"),
            {"Content-Type": "application/json"},
        ),
    )
    fake_client.queue(
        f"/octocat/Hello-World/tar.gz/{sha}",
        _FakeResponse(
            200,
            _build_tarball_bytes(),
            {"Content-Type": "application/x-gzip"},
        ),
    )
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        try:
            result = service.intake_github(
                GitHubIntakeRequest(canonical_url="https://github.com/octocat/Hello-World")
            )
        except ApiError as e:
            print("\nDEBUG details:", e.details)
            raise
        s.commit()
    assert result.repository.provider == RepositoryProvider.GITHUB
    assert result.repository.source_type == RepositorySourceType.GITHUB
    assert result.repository.visibility == RepositoryVisibility.PUBLIC
    assert result.workspace.kind == WorkspaceKind.GITHUB
    assert result.workspace.state == WorkspaceState.READY
    assert result.intake_summary["resolved_commit_sha"] == sha


def test_intake_github_idempotent_on_canonical_url(
    app_config, workspace_root, fake_client: _FakeClient
) -> None:
    sha = "0123456789abcdef0123456789abcdef01234567"
    for _ in range(2):
        fake_client.queue(
            "/repos/octocat/Hello-World",
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
        fake_client.queue(
            "/repos/octocat/Hello-World/branches/main",
            _FakeResponse(
                200,
                json.dumps(
                    {
                        "name": "main",
                        "commit": {"sha": sha},
                    }
                ).encode("utf-8"),
                {"Content-Type": "application/json"},
            ),
        )
        fake_client.queue(
            f"/octocat/Hello-World/tar.gz/{sha}",
            _FakeResponse(
                200,
                _build_tarball_bytes(),
                {"Content-Type": "application/x-gzip"},
            ),
        )
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        first = service.intake_github(
            GitHubIntakeRequest(canonical_url="https://github.com/octocat/Hello-World")
        )
        s.commit()
        first_id = first.repository.id
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        second = service.intake_github(
            GitHubIntakeRequest(canonical_url="https://github.com/octocat/Hello-World")
        )
        s.commit()
        assert second.repository.id == first_id


def test_intake_github_rejects_non_github_url(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        with pytest.raises(ApiError) as exc:
            service.intake_github(
                GitHubIntakeRequest(canonical_url="https://example.com/octocat/Hello-World")
            )
    assert exc.value.code == ApiErrorCode.VALIDATION_ERROR.value


def test_intake_github_rejects_bad_ref(app_config, workspace_root) -> None:
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        with pytest.raises(ApiError) as exc:
            service.intake_github(
                GitHubIntakeRequest(
                    canonical_url="https://github.com/octocat/Hello-World",
                    requested_ref="-leading-dash",
                )
            )
    assert exc.value.code == ApiErrorCode.VALIDATION_ERROR.value


def test_intake_github_handles_404(app_config, workspace_root, fake_client: _FakeClient) -> None:
    fake_client.queue(
        "/repos/octocat/Hello-World",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        with pytest.raises(ApiError) as exc:
            service.intake_github(
                GitHubIntakeRequest(canonical_url="https://github.com/octocat/Hello-World")
            )
    assert exc.value.code == ApiErrorCode.NOT_FOUND.value


def test_intake_github_handles_rate_limit(
    app_config, workspace_root, fake_client: _FakeClient
) -> None:
    fake_client.queue(
        "/repos/octocat/Hello-World",
        _FakeResponse(429, b"{}", {"Content-Type": "application/json"}),
    )
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        with pytest.raises(ApiError) as exc:
            service.intake_github(
                GitHubIntakeRequest(canonical_url="https://github.com/octocat/Hello-World")
            )
    assert exc.value.code == ApiErrorCode.RATE_LIMITED.value


def test_intake_github_token_not_in_response(
    app_config, workspace_root, fake_client: _FakeClient
) -> None:
    """The intake result must not leak the server-side token."""
    sha = "0123456789abcdef0123456789abcdef01234567"
    fake_client.queue(
        "/repos/octocat/Hello-World",
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
    fake_client.queue(
        "/repos/octocat/Hello-World/branches/main",
        _FakeResponse(
            200,
            json.dumps({"name": "main", "commit": {"sha": sha}}).encode("utf-8"),
            {"Content-Type": "application/json"},
        ),
    )
    fake_client.queue(
        f"/octocat/Hello-World/tar.gz/{sha}",
        _FakeResponse(
            200,
            _build_tarball_bytes(),
            {"Content-Type": "application/x-gzip"},
        ),
    )
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        result = service.intake_github(
            GitHubIntakeRequest(canonical_url="https://github.com/octocat/Hello-World")
        )
        s.commit()
    summary = result.intake_summary
    summary_str = json.dumps(summary, default=str)
    assert "token" not in summary_str
    assert "secret" not in summary_str


def test_intake_upload_happy_path(app_config, workspace_root) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", b"hi")
    body = buf.getvalue()
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        result = service.intake_upload(
            upload=[body],
            archive_filename="hello.zip",
        )
        s.commit()
    assert result.repository.provider == RepositoryProvider.LOCAL_UPLOAD
    assert result.workspace.kind == WorkspaceKind.UPLOADED_ARCHIVE
    assert result.workspace.state == WorkspaceState.READY
    assert result.workspace.archive_sha256 is not None
    assert result.workspace.file_count == 1


def test_intake_upload_rejects_traversal(app_config, workspace_root) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.txt", b"evil")
    body = buf.getvalue()
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        with pytest.raises(ApiError) as exc:
            service.intake_upload(upload=[body], archive_filename="evil.zip")
    assert exc.value.code == ApiErrorCode.ARCHIVE_UNSAFE.value


def test_intake_upload_rejects_oversized(app_config, workspace_root) -> None:
    # Larger than the default archive cap (100 MiB). We stream
    # a single big chunk; the intake layer should reject it
    # before any extraction happens.
    body = b"x" * (100 * 1024 * 1024 + 1)
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        with pytest.raises(ApiError) as exc:
            service.intake_upload(upload=[body], archive_filename="big.zip")
    assert exc.value.code == ApiErrorCode.ARCHIVE_UNSAFE.value
