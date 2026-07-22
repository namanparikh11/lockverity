"""Intake service.

The :class:`IntakeService` is the single entry point for adding
a new repository to the system. It supports two flows:

- :meth:`intake_github` - resolve a public GitHub URL to a
  commit SHA, download the tarball, validate and extract it.
- :meth:`intake_upload` - accept a streamed ZIP upload, validate
  and extract it.

Both flows create a fresh :class:`Repository`, a :class:`ScanRun`,
a :class:`Workspace`, and a default stage pipeline. The
resulting scan is in ``queued`` state; the orchestrator picks it
up via the executor.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.repository import (
    Repository,
    RepositoryProvider,
    RepositorySourceType,
    RepositoryVisibility,
)
from app.models.scan_run import ScanRun, ScanTriggerType
from app.models.workspace import Workspace, WorkspaceKind, WorkspaceState
from app.providers import github_provider
from app.providers.github_provider import GitHubIntakeError
from app.repositories import repository_repo
from app.services import scan_service
from app.services.workspace_service import WorkspaceService
from app.utils.archive_validation import ArchiveLimits
from app.utils.errors import ApiError, ApiErrorCode
from app.utils.github import is_valid_ref
from app.utils.repo_url import (
    NormalizedRepositoryUrl,
    RepositoryUrlError,
    normalize_github_url,
)
from app.utils.zip_intake import (
    ZipIntakeError,
    ZipIntakeResult,
    intake_tar_gz,
    intake_zip,
)

logger = logging.getLogger("lockverity.intake")


def _archive_limits(settings) -> Any:
    """Build an :class:`ArchiveLimits` from application settings."""
    return ArchiveLimits(
        max_compressed_bytes=settings.archive_max_compressed_bytes,
        max_uncompressed_bytes=settings.archive_max_uncompressed_bytes,
        max_file_count=settings.archive_max_file_count,
        max_file_bytes=settings.archive_max_file_bytes,
        max_depth=settings.archive_max_depth,
        suspicious_ratio=settings.archive_suspicious_ratio,
    )


@dataclass(frozen=True, slots=True)
class GitHubIntakeRequest:
    canonical_url: str
    requested_ref: str | None = None


@dataclass(frozen=True, slots=True)
class IntakeResult:
    repository: Repository
    scan: ScanRun
    workspace: Workspace
    intake_summary: dict[str, Any]


class IntakeService:
    """All repository and scan creation paths."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._workspaces = WorkspaceService(session, settings=self._settings)

    # ------------------------------------------------------------------
    # GitHub intake
    # ------------------------------------------------------------------
    def intake_github(self, payload: GitHubIntakeRequest) -> IntakeResult:
        # Step 1: Normalize the URL.
        try:
            normalized = normalize_github_url(payload.canonical_url)
        except RepositoryUrlError as exc:
            raise ApiError(
                ApiErrorCode.VALIDATION_ERROR,
                "Repository URL is not a valid public GitHub URL.",
                details={"reason": str(exc)},
            ) from exc

        if payload.requested_ref is not None and not is_valid_ref(payload.requested_ref):
            raise ApiError(
                ApiErrorCode.VALIDATION_ERROR,
                "Requested ref is not a valid Git ref.",
                details={"reason": "invalid_ref"},
            )

        # Step 2: Resolve metadata + commit SHA.
        client = github_provider.build_client(
            token=self._settings.github_token,
            user_agent=self._settings.github_user_agent,
        )
        try:
            try:
                metadata = github_provider.fetch_repository_metadata(
                    client,
                    owner=normalized.owner,
                    name=normalized.name,
                    canonical_url=normalized.canonical_url,
                    requested_ref=payload.requested_ref,
                )
            except GitHubIntakeError as exc:
                raise _github_error_to_api_error(exc) from exc
            # Step 3: Download the tarball.
            try:
                tarball = github_provider.download_tarball(
                    client,
                    owner=normalized.owner,
                    name=normalized.name,
                    commit_sha=metadata.resolved_commit_sha,
                    max_response_bytes=self._settings.github_max_download_bytes,
                    timeout_seconds=self._settings.github_timeout_seconds,
                )
            except GitHubIntakeError as exc:
                raise _github_error_to_api_error(exc) from exc
        finally:
            client.close()

        # Step 4: Persist repository, scan, workspace.
        repository = self._get_or_create_github_repository(normalized, metadata)
        scan = self._queue_scan(repository, ScanTriggerType.MANUAL, metadata.resolved_commit_sha)
        workspace = self._workspaces.create_for_scan(
            scan,
            kind=WorkspaceKind.GITHUB,
            archive_filename=f"github/{metadata.owner}/{metadata.name}@{metadata.resolved_commit_sha}.tar.gz",
        )

        # Step 5: Quarantine the tarball bytes, validate, and extract.
        # Build a one-shot source: the first call returns the
        # whole body, subsequent calls return empty bytes so the
        # quarantine loop terminates.
        _sent = [False]

        def _tarball_source(_chunk_size: int) -> bytes:
            if _sent[0]:
                return b""
            _sent[0] = True
            return tarball.body

        result, workspace = self._quarantine_validate_extract(
            workspace=workspace,
            source=_tarball_source,
            limits=_archive_limits(self._settings),
            archive_filename=workspace.archive_filename,
            intake_kind="tar_gz",
        )
        return IntakeResult(
            repository=repository,
            scan=scan,
            workspace=workspace,
            intake_summary={
                "kind": "github",
                "owner": metadata.owner,
                "name": metadata.name,
                "resolved_commit_sha": metadata.resolved_commit_sha,
                "default_branch": metadata.default_branch,
                "visibility": metadata.visibility,
                "archive_sha256": result.archive_sha256,
                "archive_size": result.archive_size,
                "file_count": result.file_count,
                "uncompressed_size": result.uncompressed_size,
                "etag": tarball.etag,
                "last_modified": tarball.last_modified,
            },
        )

    # ------------------------------------------------------------------
    # ZIP upload intake
    # ------------------------------------------------------------------
    def intake_upload(
        self,
        *,
        upload: Callable[[int], bytes] | Iterable[bytes],
        archive_filename: str | None = None,
    ) -> IntakeResult:
        """Intake a streamed ZIP upload.

        ``upload`` is either an iterable of byte chunks or a
        callable that returns a single chunk per invocation. The
        repository and scan are created on the fly; the upload
        content is not retained outside the workspace.
        """
        # v2.0.5: the original filename (basename-only) is
        # persisted on the repository row for the
        # human-readable label. ``basename_safely`` strips
        # absolute paths and other unsafe forms; an empty or
        # unsafe value resolves to ``None`` (the API will
        # surface a bounded fallback label).
        repository = self._create_upload_repository(original_filename=archive_filename)
        scan = self._queue_scan(
            repository,
            ScanTriggerType.UPLOAD,
            requested_ref=None,
        )
        workspace = self._workspaces.create_for_scan(
            scan,
            kind=WorkspaceKind.UPLOADED_ARCHIVE,
            archive_filename=archive_filename or "upload.zip",
        )
        result, workspace = self._quarantine_validate_extract(
            workspace=workspace,
            source=upload,
            limits=_archive_limits(self._settings),
            archive_filename=workspace.archive_filename,
        )
        return IntakeResult(
            repository=repository,
            scan=scan,
            workspace=workspace,
            intake_summary={
                "kind": "uploaded_archive",
                "archive_sha256": result.archive_sha256,
                "archive_size": result.archive_size,
                "file_count": result.file_count,
                "uncompressed_size": result.uncompressed_size,
            },
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _quarantine_validate_extract(
        self,
        *,
        workspace: Workspace,
        source: Callable[[int], bytes] | Iterable[bytes],
        limits: Any,
        archive_filename: str | None,
        intake_kind: str = "zip",
    ) -> tuple[ZipIntakeResult, Workspace]:
        paths = self._workspaces.paths_for(workspace.workspace_key)
        self._workspaces.transition(workspace, target=WorkspaceState.VALIDATING)
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        try:
            if intake_kind == "tar_gz":
                result = intake_tar_gz(paths, source=source, limits=limits)
            else:
                result = intake_zip(paths, source=source, limits=limits)
        except ZipIntakeError as exc:
            self._workspaces.transition(
                workspace,
                target=WorkspaceState.FAILED,
                failure_code=exc.code,
                failure_summary=exc.message,
            )
            self._workspaces.cleanup(workspace)
            try:
                self._session.commit()
            except Exception:
                self._session.rollback()
            raise ApiError(
                ApiErrorCode.ARCHIVE_UNSAFE,
                "Archive was rejected.",
                details={
                    "code": exc.code,
                    "message": exc.message,
                    "filename": archive_filename,
                },
            ) from exc
        except Exception as exc:
            self._workspaces.transition(
                workspace,
                target=WorkspaceState.FAILED,
                failure_code="archive_internal_error",
                failure_summary=str(exc)[:2048],
            )
            self._workspaces.cleanup(workspace)
            try:
                self._session.commit()
            except Exception:
                self._session.rollback()
            raise
        self._workspaces.transition(
            workspace,
            target=WorkspaceState.READY,
            archive_sha256=result.archive_sha256,
            archive_size=result.archive_size,
            file_count=result.file_count,
            uncompressed_size=result.uncompressed_size,
        )
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return result, workspace

    def _get_or_create_github_repository(
        self,
        normalized: NormalizedRepositoryUrl,
        metadata: github_provider.GitHubRepositoryMetadata,
    ) -> Repository:
        existing = repository_repo.get_repository_by_canonical_url(
            self._session, normalized.canonical_url
        )
        if existing is not None:
            # Refresh the public metadata that the GitHub API
            # returned. We never overwrite identity fields.
            existing.default_branch = metadata.default_branch or existing.default_branch
            existing.description = metadata.description or existing.description
            existing.visibility = _to_visibility(metadata.visibility)
            existing.archived = metadata.archived
            try:
                self._session.commit()
            except Exception:
                self._session.rollback()
                raise
            return existing
        repo = repository_repo.create_github_repository(
            self._session,
            owner=normalized.owner,
            name=normalized.name,
            canonical_url=normalized.canonical_url,
            description=metadata.description,
            default_branch=metadata.default_branch,
            visibility=metadata.visibility,
        )
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return repo

    def _create_upload_repository(self, original_filename: str | None = None) -> Repository:
        # Uploaded archives are uniquely identified by their
        # archive SHA-256 once it has been computed. We cannot
        # know the SHA before the upload completes, so we use a
        # stable placeholder URL; the actual SHA replaces it
        # after validation. The unique constraint on
        # ``canonical_url`` keeps the placeholder from
        # double-creating the row.
        import hashlib
        import secrets

        marker = secrets.token_hex(8)
        placeholder_url = f"upload://{marker}"
        repo = repository_repo.create_github_repository(  # type: ignore[arg-type]
            self._session,
            owner="upload",
            name=marker,
            canonical_url=placeholder_url,
            description="Uploaded archive",
            default_branch=None,
            visibility="private",
        )
        repo.source_type = RepositorySourceType.UPLOADED_ARCHIVE
        repo.provider = RepositoryProvider.LOCAL_UPLOAD
        # v2.0.5: persist the basename of the client-supplied
        # filename. ``original_filename`` is stored as
        # basename-only; an absolute path the client sends
        # never reaches the database. The column is nullable
        # for v0.x-v2.0.4 historical rows; the intake path
        # populates it for new uploads. The field is used as
        # the primary human-readable label by the repository
        # list and search endpoints.
        if original_filename is not None:
            from app.utils.paths import basename_safely

            repo.original_filename = basename_safely(original_filename)
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        # Reference hashlib so static analyzers see the dependency.
        _ = hashlib.sha256
        return repo

    def _queue_scan(
        self,
        repository: Repository,
        trigger: ScanTriggerType,
        requested_ref: str | None,
    ) -> ScanRun:
        scan = scan_service.create_scan(
            self._session,
            repository_id=repository.id,
            trigger_type=trigger,
            requested_ref=requested_ref,
        )
        return scan


def _to_visibility(value: str) -> RepositoryVisibility:
    value = (value or "").lower()
    if value == "public":
        return RepositoryVisibility.PUBLIC
    if value == "private":
        return RepositoryVisibility.PRIVATE
    return RepositoryVisibility.UNKNOWN


def _github_error_to_api_error(exc: GitHubIntakeError) -> ApiError:
    code = ApiErrorCode.PROVIDER_UNAVAILABLE
    http_status = exc.http_status
    safe_message = exc.redacted_summary()
    details: dict[str, Any] = {"code": exc.code}
    if http_status is not None:
        details["http_status"] = http_status
    if exc.code in {"github_not_found"}:
        code = ApiErrorCode.NOT_FOUND
    elif exc.code in {"github_rate_limited"}:
        code = ApiErrorCode.RATE_LIMITED
    elif exc.code in {"github_unauthorized", "github_forbidden"}:
        code = ApiErrorCode.FORBIDDEN
    elif exc.code in {"github_response_too_large"}:
        code = ApiErrorCode.VALIDATION_ERROR
    elif exc.code in {"github_host_forbidden"}:
        code = ApiErrorCode.FORBIDDEN
    safe_message = safe_message or "GitHub intake failed."
    return ApiError(code, safe_message, details=details)


__all__ = [
    "GitHubIntakeRequest",
    "IntakeResult",
    "IntakeService",
]
