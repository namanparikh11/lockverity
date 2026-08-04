"""Tests for the IntakeService."""

from __future__ import annotations

import io
import json
import re
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
    # ``details.correlation_id``. ``secrets.token_hex(8)``
    # produces 8 random bytes encoded as a 16-character
    # lowercase hex string (``^[0-9a-f]{16}$``); the
    # contract is that the id is exactly 16 lowercase hex
    # characters long so an operator can grep the runtime
    # log for the same id without false positives.
    assert exc.value.details is not None
    cid = exc.value.details.get("correlation_id")
    assert isinstance(cid, str)
    assert len(cid) == 16
    assert re.fullmatch(r"[0-9a-f]{16}", cid) is not None


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


# ---------------------------------------------------------------------------
# v2.1.1 acceptance: invalid_ref (valid-looking but missing ref) on a
# known-existing public repository is a distinct failure mode from
# "repository not found / private". The two must never be conflated.
# ---------------------------------------------------------------------------


def _queue_github_metadata(
    fake_client: _FakeClient, *, sha: str, default_branch: str = "main"
) -> None:
    """Queue the repository-metadata + branch 200 responses used by the
    invalid-ref tests. The branch response is intentionally followed
    by a 404 from the branch lookup so ``_resolve_ref_to_sha`` ends
    up at the "both 404" branch.
    """
    fake_client.queue(
        "/repos/octocat/Hello-World",
        _FakeResponse(
            200,
            json.dumps(
                {
                    "default_branch": default_branch,
                    "visibility": "public",
                    "archived": False,
                }
            ).encode("utf-8"),
            {"Content-Type": "application/json"},
        ),
    )


def test_intake_github_handles_invalid_ref_missing_branch(
    app_config, workspace_root, fake_client: _FakeClient
) -> None:
    """A valid-looking branch that does not exist on a public repo
    is ``invalid_ref``, not ``not_found``.
    """
    _queue_github_metadata(fake_client, sha="0123456789abcdef0123456789abcdef01234567")
    # Both branch and tag lookups 404. The fake client
    # already maps 404 -> http_not_found, which ``_resolve_ref_to_sha``
    # now distinguishes from a real "repository missing" failure.
    fake_client.queue(
        "/repos/octocat/Hello-World/branches/definitely-not-a-real-lockverity-branch",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    fake_client.queue(
        "/repos/octocat/Hello-World/git/refs/tags/definitely-not-a-real-lockverity-branch",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        with pytest.raises(ApiError) as exc:
            service.intake_github(
                GitHubIntakeRequest(
                    canonical_url="https://github.com/octocat/Hello-World",
                    requested_ref="definitely-not-a-real-lockverity-branch",
                )
            )
    assert exc.value.code == ApiErrorCode.INVALID_REF.value
    assert "branch, tag, or commit" in exc.value.message
    assert "Check the ref" in exc.value.message
    # The original provider code stays in ``details`` for diagnostics.
    assert exc.value.details is not None
    assert exc.value.details.get("code") == "github_invalid_ref"


def test_intake_github_handles_invalid_ref_missing_tag(
    app_config, workspace_root, fake_client: _FakeClient
) -> None:
    """A valid-looking tag that does not exist on a public repo is
    also ``invalid_ref``.
    """
    _queue_github_metadata(fake_client, sha="0123456789abcdef0123456789abcdef01234567")
    fake_client.queue(
        "/repos/octocat/Hello-World/branches/v9.9.9-typo",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    fake_client.queue(
        "/repos/octocat/Hello-World/git/refs/tags/v9.9.9-typo",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        with pytest.raises(ApiError) as exc:
            service.intake_github(
                GitHubIntakeRequest(
                    canonical_url="https://github.com/octocat/Hello-World",
                    requested_ref="v9.9.9-typo",
                )
            )
    assert exc.value.code == ApiErrorCode.INVALID_REF.value


def test_intake_github_handles_malformed_full_sha(
    app_config, workspace_root, fake_client: _FakeClient
) -> None:
    """A 40-character ref that is uppercase hex (not lowercase) is
    a syntactically valid branch/tag ref name (the ``_REF_RE``
    allows uppercase) but not a valid SHA. It reaches the
    GitHub ref-lookup path; both branch and tag lookups return
    404, so the failure mode is ``invalid_ref`` (not
    ``validation_error``).

    The distinction matters: a malformed SHA that LOOKS like a
    SHA (e.g. ``Z`` * 40) is not the same as
    ``-leading-dash`` (which ``is_valid_ref`` rejects before
    any GitHub call). The hotfix keeps the two failure modes
    distinct so the UI can render the right actionable message.
    """
    _queue_github_metadata(fake_client, sha="0123456789abcdef0123456789abcdef01234567")
    fake_client.queue(
        f"/repos/octocat/Hello-World/branches/{'Z' * 40}",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    fake_client.queue(
        f"/repos/octocat/Hello-World/git/refs/tags/{'Z' * 40}",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        with pytest.raises(ApiError) as exc:
            service.intake_github(
                GitHubIntakeRequest(
                    canonical_url="https://github.com/octocat/Hello-World",
                    requested_ref="Z" * 40,  # 40 chars but not lowercase hex
                )
            )
    assert exc.value.code == ApiErrorCode.INVALID_REF.value


def test_intake_github_handles_valid_full_sha(
    app_config, workspace_root, fake_client: _FakeClient
) -> None:
    """A valid lowercase 40-char SHA on a public repo is accepted;
    the tarball endpoint is hit and the scan reaches ``READY``.
    """
    sha = "0123456789abcdef0123456789abcdef01234567"
    _queue_github_metadata(fake_client, sha=sha)
    # A SHA-typed ref bypasses the branches/tags lookup and
    # goes straight to the tarball endpoint.
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
            GitHubIntakeRequest(
                canonical_url="https://github.com/octocat/Hello-World",
                requested_ref=sha,
            )
        )
        s.commit()
    assert result.workspace.state == WorkspaceState.READY


# ---------------------------------------------------------------------------
# v2.1.1 acceptance: direct database cleanup assertions for every failed
# intake path. After failure, the database must not contain a misleading
# running scan or a READY workspace; retrying the same repository must
# be safe; a classified 404 must not create a partial scan; an internal
# exception must not leave an orphan scan record.
# ---------------------------------------------------------------------------


def _no_running_or_queued_scan_rows(session) -> None:
    """Assert that no scan row is in a misleading non-terminal state.

    The intake flow creates ``ScanRun`` rows with status ``queued``
    while it works; a failed intake must roll back the row or move
    it to a terminal state. The terminal states are ``completed``,
    ``failed``, ``cancelled``, ``partial``, and the orchestrator
    states ``running`` / ``succeeded``. Anything else is a leak.
    """
    from app.models.scan_run import ScanStatus

    session.expire_all()
    rows = session.query(  # type: ignore[attr-defined]
        __import__("app.models.scan_run", fromlist=["ScanRun"]).ScanRun
    ).all()
    terminal = {
        ScanStatus.COMPLETED.value,
        ScanStatus.FAILED.value,
        ScanStatus.CANCELLED.value,
        ScanStatus.PARTIAL.value,
    }
    for row in rows:
        assert row.status in terminal, (
            f"scan row id={row.id} left in non-terminal status {row.status!r}"
        )


def _no_ready_workspace_rows(session) -> None:
    from app.models.workspace import WorkspaceState

    rows = session.query(  # type: ignore[attr-defined]
        __import__("app.models.workspace", fromlist=["Workspace"]).Workspace
    ).all()
    for row in rows:
        assert row.state != WorkspaceState.READY.value, (
            f"workspace id={row.id} left in READY state after failed intake"
        )


def test_intake_404_does_not_create_workspace_or_scan(
    app_config, workspace_root, fake_client: _FakeClient
) -> None:
    """A classified 404 must not create a partial workspace or scan.

    A failing intake must NOT leave a ``Workspace`` /
    ``ScanRun`` row in a misleading non-terminal
    state; otherwise the UI shows a misleading
    "running" or "queued" scan. The function may either
    roll back the partial rows or transition them to a
    terminal state (``failed``); both are acceptable.
    """
    fake_client.queue(
        "/repos/octocat/Hello-World",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        with pytest.raises(ApiError):
            service.intake_github(
                GitHubIntakeRequest(canonical_url="https://github.com/octocat/Hello-World")
            )
        _no_ready_workspace_rows(s)
        _no_running_or_queued_scan_rows(s)


def test_intake_invalid_ref_does_not_create_workspace_or_scan(
    app_config, workspace_root, fake_client: _FakeClient
) -> None:
    """An ``invalid_ref`` failure must also avoid leaving a
    non-terminal workspace or scan. A 404 from the branches
    AND tags APIs on a known-existing public repo is the
    canonical ``invalid_ref`` case.
    """
    _queue_github_metadata(fake_client, sha="0123456789abcdef0123456789abcdef01234567")
    fake_client.queue(
        "/repos/octocat/Hello-World/branches/nope",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    fake_client.queue(
        "/repos/octocat/Hello-World/git/refs/tags/nope",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        with pytest.raises(ApiError) as exc:
            service.intake_github(
                GitHubIntakeRequest(
                    canonical_url="https://github.com/octocat/Hello-World",
                    requested_ref="nope",
                )
            )
        assert exc.value.code == ApiErrorCode.INVALID_REF.value
        _no_ready_workspace_rows(s)
        _no_running_or_queued_scan_rows(s)


def test_intake_internal_error_does_not_leave_orphan(
    app_config, workspace_root, fake_client: _FakeClient, monkeypatch
) -> None:
    """An ``INTERNAL_UNEXPECTED`` must not leave a READY workspace
    or a queued/running scan. The workspace is transitioned to
    ``FAILED`` for diagnostics; the scan is moved to
    ``FAILED`` (a terminal state) so the UI does not show a
    misleading running scan.
    """
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
        assert exc.value.code == ApiErrorCode.INTERNAL_UNEXPECTED.value
        _no_ready_workspace_rows(s)
        _no_running_or_queued_scan_rows(s)


def test_intake_404_retry_is_safe(app_config, workspace_root, fake_client: _FakeClient) -> None:
    """Retrying a 404 with the same canonical URL is safe: the
    second attempt must not collide with any leftover state and
    must not leave a misleading running scan.
    """
    fake_client.queue(
        "/repos/octocat/Hello-World",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    fake_client.queue(
        "/repos/octocat/Hello-World",
        _FakeResponse(404, b"{}", {"Content-Type": "application/json"}),
    )
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        for _ in range(2):
            with pytest.raises(ApiError) as exc:
                service.intake_github(
                    GitHubIntakeRequest(canonical_url="https://github.com/octocat/Hello-World")
                )
            assert exc.value.code == ApiErrorCode.NOT_FOUND.value
            _no_ready_workspace_rows(s)
            _no_running_or_queued_scan_rows(s)


# ---------------------------------------------------------------------------
# v2.1.1 acceptance: correlation-ID log contract. The ID returned in
# the response envelope MUST equal the ID written to the local log;
# the traceback is in the log only; secrets / paths / upstream bodies
# are absent from the response.
# ---------------------------------------------------------------------------


def test_intake_internal_error_correlation_id_log_contract(
    app_config, workspace_root, fake_client: _FakeClient, monkeypatch, caplog
) -> None:
    """The correlation id in the response equals the one in the
    rotating runtime log, the traceback is log-only, and the
    response carries no upstream body, no path, no token.
    """
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
    caplog.set_level("ERROR", logger="lockverity")
    with _db_session.SessionLocal() as s:
        service = IntakeService(s)
        with pytest.raises(ApiError) as exc:
            service.intake_github(
                GitHubIntakeRequest(canonical_url="https://github.com/octocat/Hello-World")
            )
        s.rollback()
    # Response correlation id format
    response_cid = exc.value.details.get("correlation_id")
    assert re.fullmatch(r"[0-9a-f]{16}", response_cid) is not None
    # Log contains the same id
    log_blob = "\n".join(record.getMessage() for record in caplog.records)
    log_blob_full = (
        log_blob
        + "\n"
        + "\n".join(getattr(record, "exc_text", "") or "" for record in caplog.records)
    )
    assert response_cid in log_blob, (
        f"correlation id {response_cid!r} must appear in the runtime log"
    )
    # The traceback is in the log
    assert "RuntimeError" in log_blob_full or "Traceback" in log_blob_full, (
        "the full traceback must be written to the local log"
    )
    # The traceback is NOT in the response message
    assert "Traceback" not in exc.value.message
    assert "RuntimeError" not in exc.value.message
    # The response message has no upstream body, no filesystem path,
    # no simulated marker, and no provider token.
    assert "simulated" not in exc.value.message
    assert "_internal" not in exc.value.message
    assert "x-access-token" not in exc.value.message
    assert "ghp_" not in exc.value.message


def test_intake_internal_error_no_secrets_in_response_details(
    app_config, workspace_root, fake_client: _FakeClient, monkeypatch
) -> None:
    """The response ``details`` envelope is never asked to carry
    secrets. The hotfix only emits ``correlation_id`` and ``kind``;
    the captured tests assert no other keys are present.
    """
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
    details = exc.value.details
    assert set(details.keys()) <= {"correlation_id", "kind"}, (
        f"unexpected keys in details: {sorted(details.keys())!r}"
    )
    assert isinstance(details["correlation_id"], str)
    assert re.fullmatch(r"[0-9a-f]{16}", details["correlation_id"]) is not None
    # ``kind`` records which intake path raised the
    # failure; the bounded set is ``github`` for the
    # GitHub URL flow, ``upload`` for the archive
    # upload flow, and the corresponding extraction
    # stage (``tar_gz`` / ``zip``) when the failure
    # happened AFTER the scan was created (e.g. the
    # simulated ``RuntimeError`` in this test fires
    # inside ``intake_tar_gz``).
    assert details["kind"] in {"github", "upload", "tar_gz", "zip"}


# ---------------------------------------------------------------------------
# v2.1.1 packaged-runtime acceptance: a top-level try/except in
# ``IntakeService.intake_github`` and ``intake_upload`` sanitises
# every unhandled exception (e.g. a database write failure that
# escapes the inner ``_quarantine_validate_extract`` block) into
# the documented ``INTERNAL_UNEXPECTED`` envelope with a non-PII
# 16-character lowercase hex ``correlation_id``. This is the
# exact failure mode the v2.1.1 packaged-runtime acceptance
# discovered when the runtime database was set read-only: the
# write failure inside ``_get_or_create_github_repository``
# escaped the inner extraction block and surfaced as the
# legacy ``internal_error`` envelope without a correlation
# id. The top-level wrapper closes that gap.
# ---------------------------------------------------------------------------


def test_intake_top_level_internal_error_sanitised(
    app_config, workspace_root, fake_client: _FakeClient, monkeypatch
) -> None:
    """A non-ApiError exception that escapes the inner
    ``_quarantine_validate_extract`` block (e.g. a database
    write failure from ``_get_or_create_github_repository``)
    is sanitised into ``INTERNAL_UNEXPECTED`` with a
    16-character lowercase hex ``correlation_id``.
    """

    def _raise_db_error(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("simulated db write failure")

    # Patch ``_get_or_create_github_repository`` so the failure
    # happens AFTER the GitHub metadata is fetched successfully
    # but BEFORE the inner ``_quarantine_validate_extract``
    # block. This is the exact code path the packaged-runtime
    # acceptance discovered: a DB write failure (the runtime
    # database was set read-only) escaped the inner
    # extraction block and surfaced as the legacy
    # ``internal_error`` envelope without a correlation id.
    monkeypatch.setattr(
        "app.services.intake_service.IntakeService._get_or_create_github_repository",
        _raise_db_error,
    )
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
    # The outer handler must sanitise the non-ApiError
    # exception into the documented ``INTERNAL_UNEXPECTED``
    # envelope, NOT the legacy ``INTERNAL`` envelope.
    assert exc.value.code == ApiErrorCode.INTERNAL_UNEXPECTED.value
    # The response ``details`` carries a 16-character
    # lowercase hex ``correlation_id`` and ``kind=github``.
    assert exc.value.details is not None
    cid = exc.value.details.get("correlation_id")
    assert isinstance(cid, str)
    assert re.fullmatch(r"[0-9a-f]{16}", cid) is not None
    assert exc.value.details.get("kind") == "github"
    # The response message is the bounded safe message; the
    # exception class name and the simulated message are NOT
    # in the response.
    assert "RuntimeError" not in exc.value.message
    assert "simulated" not in exc.value.message
    assert "Traceback" not in exc.value.message
    # The exception is chained from the original so the log
    # has the full traceback.
    assert exc.value.__cause__ is not None


def test_intake_top_level_internal_error_preserves_classified_errors(
    app_config, workspace_root, fake_client: _FakeClient
) -> None:
    """The top-level wrapper does NOT swallow classified
    ``ApiError`` instances. A 404 from the GitHub metadata
    endpoint surfaces as the existing ``not_found`` envelope,
    not as a new ``INTERNAL_UNEXPECTED``.
    """
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
    # 404 still maps to ``not_found`` (the actionable
    # ``Repository could not be accessed.`` message) and is
    # not collapsed into ``INTERNAL_UNEXPECTED``.
    assert exc.value.code == ApiErrorCode.NOT_FOUND.value
    assert "could not be accessed" in exc.value.message
    assert "private" in exc.value.message.lower()
    # The classified envelope does NOT carry a correlation id
    # because the failure was classified by the inner
    # ``_github_error_to_api_error`` mapping, not by the
    # top-level wrapper.
    assert "correlation_id" not in (exc.value.details or {})
