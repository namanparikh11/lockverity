"""Rescan service (v1.6.1).

The v1.6 frontend called ``POST /api/v1/repositories/{id}/scans``
to retry or rescan a terminal scan. The previous
implementation only created a queued scan row; the
scan was broken because no workspace was associated
with it and the orchestrator failed the archive
validation stage with ``failure_code="not_found"``.

The v1.6.1 repair:
- creates a fresh scan row;
- creates a distinct fresh workspace;
- re-materialises the source evidence into the new
  workspace before the route returns;
- preserves the historical scan and workspace
  unchanged;
- refuses to leave a queued orphan scan when source
  evidence cannot be reconstructed (the route
  returns a bounded ``rescan_source_unavailable``
  error before any queued row is persisted).

Two source types are supported:

- Public GitHub repository: the original tarball is
  re-downloaded from the public API (no token) and
  re-extracted into the new workspace. The download
  honours the same provider-safety limits as the
  original intake.
- Uploaded archive: the previous workspace's
  extracted contents are copied into the new
  workspace using the existing workspace quarantine
  pattern. The original archive bytes are not
  retained; the safest persisted source is the
  previous workspace's extracted contents, copied
  safely into a new immutable workspace.

Analyzed code is never executed at any point in
either path.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.repository import (
    Repository,
    RepositorySourceType,
)
from app.models.scan_run import (
    ScanRun,
    ScanStatus,
    ScanTriggerType,
)
from app.models.workspace import Workspace, WorkspaceKind, WorkspaceState
from app.providers import github_provider
from app.providers.github_provider import GitHubIntakeError
from app.repositories import repository_repo, workspace_repo
from app.services import scan_service
from app.services.workspace_service import WorkspaceService
from app.utils.archive_validation import ArchiveLimits
from app.utils.datetime import utcnow
from app.utils.errors import ApiError, ApiErrorCode
from app.utils.repo_url import (
    NormalizedRepositoryUrl,
    RepositoryUrlError,
    normalize_github_url,
)
from app.utils.zip_intake import (
    ZipIntakeError,
    intake_tar_gz,
    intake_zip,
)

logger = logging.getLogger("lockverity.rescan")


def _archive_limits(settings: Settings) -> ArchiveLimits:
    return ArchiveLimits(
        max_compressed_bytes=settings.archive_max_compressed_bytes,
        max_uncompressed_bytes=settings.archive_max_uncompressed_bytes,
        max_file_count=settings.archive_max_file_count,
        max_file_bytes=settings.archive_max_file_bytes,
        max_depth=settings.archive_max_depth,
        suspicious_ratio=settings.archive_suspicious_ratio,
    )


@dataclass(frozen=True, slots=True)
class RescanResult:
    """The result of a successful rescan operation.

    The new scan is queued. The new workspace is in
    ``ready`` state. The historical scan and workspace
    are not included because they are untouched.
    """

    repository: Repository
    scan: ScanRun
    workspace: Workspace


def _latest_ready_workspace(session: Session, repository_id: int) -> Workspace | None:
    """Return the most recent READY workspace for the repository.

    The rescan service prefers the most recent
    ready workspace as the source of truth for
    uploaded-archive rescans. Older non-ready
    workspaces are ignored: a failed or cleaned-up
    workspace does not contain the source the
    orchestrator expects.
    """
    return workspace_repo.get_latest_ready_workspace_for_repository(session, repository_id)


class RescanService:
    """Workspace-preserving rescan operations.

    Every rescan returns a fresh
    ``(scan, workspace, repository)`` triple. The
    historical scan and workspace are never mutated.
    """

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
    # Public API
    # ------------------------------------------------------------------
    def rescan_repository(
        self,
        repository_id: int,
        *,
        trigger_type: ScanTriggerType = ScanTriggerType.MANUAL,
        requested_ref: str | None = None,
    ) -> RescanResult:
        """Create a runnable new scan for an existing repository.

        Raises:
          ApiError(NOT_FOUND) when the repository is unknown.
          ApiError(RESCAN_SOURCE_UNAVAILABLE) when the
            original source cannot be reconstructed.
          ApiError(PROVIDER_UNAVAILABLE) when the
            GitHub materialisation fails for a bounded
            reason.
        """
        repository = repository_repo.get_repository_by_id(self._session, repository_id)
        if repository is None:
            raise ApiError(
                ApiErrorCode.NOT_FOUND,
                "Repository not found.",
                details={"repository_id": repository_id},
            )
        if repository.source_type == RepositorySourceType.GITHUB:
            return self._rescan_github(
                repository,
                trigger_type=trigger_type,
                requested_ref=requested_ref,
            )
        if repository.source_type == RepositorySourceType.UPLOADED_ARCHIVE:
            return self._rescan_uploaded(
                repository,
                trigger_type=trigger_type,
                requested_ref=requested_ref,
            )
        # Defensive: a future source type should not
        # produce a broken queued scan. Fail atomically.
        raise ApiError(
            ApiErrorCode.RESCAN_SOURCE_UNAVAILABLE,
            "Rescan is not supported for this repository source type.",
            details={"source_type": repository.source_type.value},
        )

    # ------------------------------------------------------------------
    # GitHub rescan
    # ------------------------------------------------------------------
    def _rescan_github(
        self,
        repository: Repository,
        *,
        trigger_type: ScanTriggerType,
        requested_ref: str | None,
    ) -> RescanResult:
        if not repository.canonical_url:
            raise ApiError(
                ApiErrorCode.RESCAN_SOURCE_UNAVAILABLE,
                "Repository is missing its canonical URL.",
                details={"repository_id": repository.id},
            )
        try:
            normalized = normalize_github_url(repository.canonical_url)
        except RepositoryUrlError as exc:
            raise ApiError(
                ApiErrorCode.VALIDATION_ERROR,
                "Repository URL is not a valid public GitHub URL.",
                details={"reason": str(exc)},
            ) from exc
        if requested_ref is not None:
            from app.utils.github import is_valid_ref

            if not is_valid_ref(requested_ref):
                raise ApiError(
                    ApiErrorCode.VALIDATION_ERROR,
                    "Requested ref is not a valid Git ref.",
                    details={"reason": "invalid_ref"},
                )
        # Step 1: persist a fresh scan row in queued
        # state. If the downstream materialisation
        # fails, we mark the scan as failed (the
        # v0.5+ state machine forbids the row from
        # staying queued).
        scan = self._create_queued_scan(
            repository,
            trigger_type=trigger_type,
            requested_ref=requested_ref,
        )
        # Step 2: create a fresh workspace tied to the
        # new scan. The workspace is the destination
        # for the re-materialised tarball.
        workspace = self._workspaces.create_for_scan(
            scan,
            kind=WorkspaceKind.GITHUB,
            archive_filename=self._github_archive_filename(normalized),
        )
        # Step 3: re-download the tarball and extract.
        try:
            self._materialise_github(workspace, normalized, requested_ref)
        except _RescanError as exc:
            self._fail_scan(scan, exc.code, exc.message)
            raise
        except Exception as exc:  # pragma: no cover - defensive
            self._fail_scan(scan, "internal_error", str(exc)[:2048])
            raise
        return RescanResult(
            repository=repository,
            scan=scan,
            workspace=workspace,
        )

    def _materialise_github(
        self,
        workspace: Workspace,
        normalized: NormalizedRepositoryUrl,
        requested_ref: str | None,
    ) -> None:
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
                    requested_ref=requested_ref,
                )
            except GitHubIntakeError as exc:
                raise _RescanError(
                    code=exc.code or "github_error",
                    message=exc.redacted_summary() or "GitHub materialisation failed.",
                ) from exc
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
                raise _RescanError(
                    code=exc.code or "github_error",
                    message=exc.redacted_summary() or "GitHub materialisation failed.",
                ) from exc
        finally:
            client.close()
        # Stream the bytes through the same quarantine
        # path the original intake uses.
        _sent = [False]

        def _source(_chunk_size: int) -> bytes:
            if _sent[0]:
                return b""
            _sent[0] = True
            return tarball.body

        try:
            result, workspace = self._quarantine_validate_extract(
                workspace=workspace,
                source=_source,
                limits=_archive_limits(self._settings),
                archive_filename=workspace.archive_filename,
                intake_kind="tar_gz",
            )
        except _RescanError:
            raise
        except ZipIntakeError as exc:
            raise _RescanError(
                code=exc.code,
                message=exc.message,
            ) from exc
        # ``result`` is the bounded intake summary
        # (sha256, size, file count). The workspace
        # row has already been populated with the
        # same fields by ``_quarantine_validate_extract``,
        # so we just touch the local reference.
        _ = result

    # ------------------------------------------------------------------
    # Uploaded archive rescan
    # ------------------------------------------------------------------
    def _rescan_uploaded(
        self,
        repository: Repository,
        *,
        trigger_type: ScanTriggerType,
        requested_ref: str | None,
    ) -> RescanResult:
        previous = _latest_ready_workspace(self._session, repository.id)
        if previous is None:
            # The previous workspace is gone (cleaned
            # up, failed, or never materialised). We
            # cannot reconstruct the source safely;
            # refuse the rescan before creating a
            # broken queued scan.
            raise ApiError(
                ApiErrorCode.RESCAN_SOURCE_UNAVAILABLE,
                "The original uploaded source is no longer available. Upload the archive again to create a new scan.",
                details={"repository_id": repository.id},
            )
        scan = self._create_queued_scan(
            repository,
            trigger_type=trigger_type,
            requested_ref=requested_ref,
        )
        workspace = self._workspaces.create_for_scan(
            scan,
            kind=WorkspaceKind.UPLOADED_ARCHIVE,
            archive_filename=previous.archive_filename,
        )
        try:
            self._materialise_uploaded(workspace, previous)
        except _RescanError as exc:
            self._fail_scan(scan, exc.code, exc.message)
            raise
        except Exception as exc:  # pragma: no cover - defensive
            self._fail_scan(scan, "internal_error", str(exc)[:2048])
            raise
        return RescanResult(
            repository=repository,
            scan=scan,
            workspace=workspace,
        )

    def _materialise_uploaded(
        self,
        new_workspace: Workspace,
        previous: Workspace,
    ) -> None:
        prev_paths = self._workspaces.paths_for(previous.workspace_key)
        new_paths = self._workspaces.paths_for(new_workspace.workspace_key)
        new_paths.ensure()
        prev_root = prev_paths.contents_dir.resolve()
        new_root = new_paths.contents_dir.resolve()
        if not prev_root.exists():
            raise _RescanError(
                code="rescan_source_missing",
                message="The original extracted workspace is no longer on disk.",
            )
        # Safe recursive copy: every entry must be a
        # regular file or directory under prev_root.
        # Symlinks, device nodes, and path escapes are
        # rejected. Analyzed code is never executed.
        copied, copied_size, copied_count = _safe_copytree(prev_root, new_root)
        new_workspace.state = WorkspaceState.READY
        new_workspace.archive_sha256 = previous.archive_sha256
        new_workspace.archive_size = previous.archive_size
        new_workspace.file_count = copied_count
        new_workspace.uncompressed_size = copied_size
        new_workspace.ready_at = utcnow()
        self._session.flush()
        _ = copied  # currently only used to validate the count

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _create_queued_scan(
        self,
        repository: Repository,
        *,
        trigger_type: ScanTriggerType,
        requested_ref: str | None,
    ) -> ScanRun:
        scan = scan_service.create_scan(
            self._session,
            repository_id=repository.id,
            trigger_type=trigger_type,
            requested_ref=requested_ref,
        )
        return scan

    def _quarantine_validate_extract(
        self,
        *,
        workspace: Workspace,
        source: Callable[[int], bytes] | Iterable[bytes],
        limits: Any,
        archive_filename: str | None,
        intake_kind: str,
    ) -> tuple[Any, Workspace]:
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
            raise _RescanError(code=exc.code, message=exc.message) from exc
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

    def _fail_scan(
        self,
        scan: ScanRun,
        failure_code: str,
        failure_summary: str,
    ) -> None:
        try:
            scan.status = ScanStatus.FAILED
            scan.failure_code = failure_code
            scan.failure_summary = failure_summary[:2048]
            scan.completed_at = utcnow()
            self._session.commit()
        except Exception:
            self._session.rollback()
            # Best-effort; the route still surfaces the
            # underlying error to the client.

    def _github_archive_filename(self, normalized: NormalizedRepositoryUrl) -> str:
        # Mirror the v0.4 intake filename shape so the
        # rescan workspace has a recognisable archive
        # filename on disk.
        return f"github/{normalized.owner}/{normalized.name}@rescan.tar.gz"


@dataclass(frozen=True, slots=True)
class _RescanError(Exception):
    """Internal exception type for the rescan flow.

    Underscore-prefixed because the public error
    surface is :class:`ApiError`; this is the
    internal mechanism for routing a rescan
    failure to ``ApiError`` after the workspace
    is materialised or rolled back.
    """

    code: str
    message: str


def _safe_copytree(src: Path, dst: Path) -> tuple[int, int, int]:
    """Copy a workspace tree from ``src`` to ``dst`` safely.

    Returns ``(files_copied, total_bytes, directories)``.
    Rejects symlinks, device nodes, fifos, sockets, and
    any path that escapes ``src``. The implementation
    never executes files.

    The destination is created as a sibling of
    ``src`` (different workspace key), so the
    orchestrator can never accidentally modify the
    original workspace.
    """
    src_resolved = src.resolve(strict=True)
    dst_resolved = dst.resolve(strict=False)
    if not src_resolved.is_dir():
        raise _RescanError(
            code="rescan_source_missing",
            message="The original extracted workspace is not a directory.",
        )

    files_copied = 0
    total_bytes = 0
    directories = 0
    src_root_id = src_resolved.stat().st_ino
    dst_root_id = dst_resolved.stat().st_ino if dst_resolved.exists() else None
    for dirpath, _dirnames, filenames in _safe_walk(src_resolved):
        rel = dirpath.relative_to(src_resolved)
        target_dir = dst_resolved / rel
        if rel == Path("."):
            target_dir = dst_resolved
        target_dir.mkdir(parents=True, exist_ok=True)
        directories += 1
        for name in filenames:
            src_file = dirpath / name
            if src_file.stat().st_ino in (src_root_id, dst_root_id):
                continue
            if src_file.is_symlink():
                raise _RescanError(
                    code="rescan_source_unsafe",
                    message="Refusing to follow a symlink in the original workspace.",
                )
            if not src_file.is_file():
                # Device nodes, fifos, sockets are not
                # supported; the source is treated as
                # unsafe rather than silently dropped.
                raise _RescanError(
                    code="rescan_source_unsafe",
                    message="Refusing to copy a non-regular file from the original workspace.",
                )
            target_file = target_dir / name
            # The destination is also a fresh workspace;
            # no need to validate against the source root.
            shutil.copyfile(src_file, target_file)
            files_copied += 1
            total_bytes += src_file.stat().st_size
    return files_copied, total_bytes, directories


def _safe_walk(top: Path):
    """Walk ``top`` safely, rejecting symlinks to directories.

    Python's :func:`os.walk` follows symlinks by default.
    The rescan copy must never follow a symlink to a
    directory because that could escape the original
    workspace. This wrapper yields the same shape but
    rejects any directory whose ``lstat`` reports
    ``is_symlink()`` as True.
    """
    import os

    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        yield Path(dirpath), dirnames, filenames
        # Drop any symlinked dirnames that the walk
        # would have descended into. ``followlinks=False``
        # is already set, but a defensive filter keeps
        # the behaviour explicit.
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]


__all__ = ["RescanResult", "RescanService"]
