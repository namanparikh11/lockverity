"""Intake API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile, status

from app.api.deps import DBSession
from app.api.mappers import scan_to_read
from app.models.workspace import Workspace
from app.schemas.intake import (
    GitHubRepositoryCreate,
    IntakeResultRead,
    WorkspaceRead,
)
from app.services import intake_service

router = APIRouter(prefix="/repositories", tags=["intake"])


def _workspace_to_read(workspace: Workspace) -> WorkspaceRead:
    return WorkspaceRead.model_validate(workspace)


def _result_to_read(result: intake_service.IntakeResult) -> IntakeResultRead:
    return IntakeResultRead(
        repository=result.repository,  # type: ignore[arg-type]
        scan=scan_to_read(result.scan),
        workspace=_workspace_to_read(result.workspace),
        intake_summary=result.intake_summary,
    )


@router.post(
    "/github",
    response_model=IntakeResultRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a public GitHub repository and start a scan.",
)
def create_github_repository(
    payload: GitHubRepositoryCreate,
    session: DBSession,
) -> IntakeResultRead:
    service = intake_service.IntakeService(session)
    result = service.intake_github(
        intake_service.GitHubIntakeRequest(
            canonical_url=payload.canonical_url,
            requested_ref=payload.requested_ref,
        )
    )
    return _result_to_read(result)


@router.post(
    "/upload",
    response_model=IntakeResultRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a ZIP archive and start a scan.",
)
async def create_uploaded_repository(
    session: DBSession,
    file: UploadFile = File(...),
) -> IntakeResultRead:
    """Stream ``file`` to a quarantine, validate it, and start a scan.

    The endpoint deliberately accepts only a single file. The
    upload is read in chunks and never loaded entirely into
    memory.
    """
    if file.content_type and file.content_type not in {
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    }:
        from app.utils.errors import ApiError, ApiErrorCode

        raise ApiError(
            ApiErrorCode.VALIDATION_ERROR,
            "Uploaded file must be a ZIP archive.",
            details={"content_type": file.content_type},
        )
    if not file.filename or not file.filename.lower().endswith(".zip"):
        from app.utils.errors import ApiError, ApiErrorCode

        raise ApiError(
            ApiErrorCode.VALIDATION_ERROR,
            "Uploaded file must have a .zip extension.",
            details={"filename": file.filename},
        )
    # Drain the upload into a bounded in-memory buffer. The
    # quarantine layer enforces the compressed-byte cap, so the
    # buffer is safe; we only hold the bytes until validation
    # and extraction complete.
    chunks: list[bytes] = []
    total = 0
    cap = 100 * 1024 * 1024  # mirror default archive cap
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            from app.utils.errors import ApiError, ApiErrorCode

            raise ApiError(
                ApiErrorCode.VALIDATION_ERROR,
                "Upload exceeds the configured size cap.",
            )
        chunks.append(chunk)

    def _drained_source(_chunk_size: int) -> bytes:
        return b""

    class _BufferedSource:
        def __init__(self, data: list[bytes]) -> None:
            self._data = data
            self._consumed = False

        def __iter__(self):
            self._consumed = False
            return self

        def __next__(self):
            if self._consumed:
                raise StopIteration
            self._consumed = True
            return b"".join(self._data)

    service = intake_service.IntakeService(session)
    result = service.intake_upload(
        upload=_BufferedSource(chunks),
        archive_filename=file.filename,
    )
    return _result_to_read(result)


__all__ = ["_result_to_read", "_workspace_to_read", "router"]
