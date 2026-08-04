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
    # v2.1.1: the 404 message must be actionable, not the
    # raw "Upstream returned 404 Not Found." string. The
    # operator should be told to verify the URL and the
    # visibility, and that private repos are not
    # supported.
    assert "could not be accessed" in exc.value.message
    assert "private" in exc.value.message.lower()
    # The original upstream code stays in ``details`` so
    # diagnostics tooling can still see it.
    assert exc.value.details is not None
    assert exc.value.details.get("code") == "github_not_found"


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
    # v2.1.1: the rate-limit message must be actionable
    # (retry, configure a token) and must NOT leak the
    # raw upstream "429 Too Many Requests." string.
    assert "rate limit" in exc.value.message.lower()
    assert "Retry" in exc.value.message or "retry" in exc.value.message
    assert "429" not in exc.value.message


def test_intake_github_archive_rejection_message_is_actionable(
    app_config, workspace_root, monkeypatch
) -> None:
    """v2.1.1: archive rejection surfaces a category-specific actionable message.

    The intake's archive-rejection branch used to surface
    the literal zip_intake failure code as the user
    message ("Archive was rejected."), which is correct
    for diagnostics tooling but a poor UX for the
    operator. The v2.1.1 hotfix maps each rejection
    code to a category-specific actionable message; the
    original code stays in ``details`` so debugging is
    unchanged.
    """
    from app.services.intake_service import _archive_rejection_message

    # A representative set of codes must have an
    # actionable message.
    for code, expected_keyword in (
        ("archive_unsafe_path", "outside the archive root"),
        ("archive_symlink_forbidden", "symbolic or hard link"),
        ("archive_too_many_files", "more files than"),
        ("archive_entry_too_large", "single entry exceeds"),
        ("archive_uncompressed_too_large", "cumulative uncompressed"),
        ("archive_overwrite_forbidden", "already contains"),
        ("archive_path_resolve_failed", "could not be resolved"),
        ("archive_path_escape", "outside the workspace"),
        ("archive_extract_failed", "could not be extracted"),
    ):
        message = _archive_rejection_message(code)
        assert expected_keyword.lower() in message.lower(), (
            f"archive rejection message for {code!r} must be actionable; got {message!r}"
        )
    # Unknown codes fall through to a generic message
    # that still tells the operator the archive was
    # rejected.
    generic = _archive_rejection_message("some_unknown_code_xyz")
    assert "rejected" in generic.lower()


def test_intake_internal_error_has_correlation_id(
    app_config, workspace_root, fake_client: _FakeClient, monkeypatch
) -> None:
    """v2.1.1: an unexpected exception is sanitised into ``INTERNAL_UNEXPECTED`` with a correlation id.

    The historical intake re-raised every unexpected
    exception as a bare ``Exception``, which the global
    handler turned into a generic 500 with the raw
    stack trace. The v2.1.1 hotfix catches the
    unexpected exception, transitions the workspace to
    ``FAILED``, and re-raises as
    :class:`ApiError` with code
    :attr:`ApiErrorCode.INTERNAL_UNEXPECTED` and a
    bounded message. The original exception is recorded
    in the workspace's ``failure_summary`` and the
    rotating runtime log; the response carries a
    short, non-PII correlation id under
    ``details.correlation_id``.
    """
    # The intake flow covers many error categories
    # explicitly (URL validation, ref validation, GitHub
    # errors, archive rejection). To exercise the
    # catch-all branch we patch the tarball extractor
    # to raise a non-``ZipIntakeError`` exception after
    # the tarball has been streamed to disk. The hotfix
    # must surface this as ``INTERNAL_UNEXPECTED``,
    # not as the legacy bare 500.
    import app.services.intake_service as intake_service_mod

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("simulated non-archive exception")

    monkeypatch.setattr(intake_service_mod, "intake_tar_gz", _raise)
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
        with pytest.raises(ApiError) as exc:
            service.intake_github(
                GitHubIntakeRequest(canonical_url="https://github.com/octocat/Hello-World")
            )
    # The new code is the documented v2.1.1
    # ``INTERNAL_UNEXPECTED`` value; the legacy ``INTERNAL``
    # is a different name reserved for unrelated cases.
    assert exc.value.code == ApiErrorCode.INTERNAL_UNEXPECTED.value
    # The user-facing message must be bounded: it must
    # NOT contain a stack trace, a filesystem path, a
    # provider token, or the simulated exception string.
    safe_message = exc.value.message
    assert "Traceback" not in safe_message
    assert "FileNotFoundError" not in safe_message
    assert "_internal" not in safe_message
    assert "simulated" not in safe_message
    assert "RuntimeError" not in safe_message
    # The correlation id is a short hex token under
    # ``details.correlation_id``.
    assert exc.value.details is not None
    cid = exc.value.details.get("correlation_id")
    assert isinstance(cid, str)
    assert len(cid) >= 8


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
