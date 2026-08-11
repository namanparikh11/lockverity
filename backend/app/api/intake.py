"""Intake API endpoints.

Event-loop note (v2.0.6 release-closure cycle 2):

The upload route is declared ``async def`` for FastAPI
ergonomics, but the body of the route delegates to a
**synchronous** intake pipeline
(``intake_service.intake_upload``). The synchronous
work reads the upload in fixed-size chunks, writes the
quarantine file to disk, computes the SHA-256, validates
the archive, and commits the database session. For the
local-first Phase 1 release this is acceptable because:

- The configured compressed-byte cap
  (``LOCKVERITY_ARCHIVE_MAX_COMPRESSED_BYTES``,
  default 100 MiB) bounds the worst-case work the
  pipeline does. The event loop is blocked for at most
  the time it takes to read, hash, and validate a
  100 MiB archive; the current Stage 1 cap and the
  sequential pipeline make this the realistic upper
  bound.
- The local-first deployment model is single-user on a
  developer's laptop; the request queue is at most one
  request at a time and the operator is not waiting on
  a shared connection pool.
- Offloading the sync work to the framework's
  threadpool helper (``anyio.to_thread.run_sync`` or
  ``starlette.concurrency.run_in_threadpool``) would
  require the SQLAlchemy session to cross a thread
  boundary; SQLAlchemy 2.0 ``Session`` objects are
  **not** thread-safe, and the route's request-scoped
  session is owned by the request context. Moving the
  work to a worker thread would either need a
  per-thread session (architectural redesign of the
  session lifecycle) or a fresh session created in the
  worker (which would commit outside the request
  scope and require explicit lifecycle management).

The Codex audit (cycle 2) explicitly classified this
as IMPORTANT POST-LAUNCH for the local-first Phase 1
release: a future release that adds a hosted
deployment with concurrent requests should offload the
synchronous intake pipeline to a worker thread. The
work is out of scope for the v2.0.6 public-closure
cycle because (a) the current cap bounds the work,
(b) the local-first model does not need concurrent
intake, and (c) the database-session-safety
re-engineering is a broader change.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, File, UploadFile, status

from app.api.deps import DBSession
from app.api.mappers import scan_to_read
from app.core.config import get_settings
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
    summary="Retrieve a public GitHub repository and prepare a queued scan.",
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


# Starlette's :class:`UploadFile` rolls over to an on-disk
# ``SpooledTemporaryFile`` once the upload exceeds its
# in-memory threshold, so the read loop below never keeps
# the whole archive in RAM regardless of the configured
# cap. We honour the cap from the application settings
# (``LOCKVERITY_ARCHIVE_MAX_COMPRESSED_BYTES``) rather than
# duplicating a hard-coded value, and we hand the underlying
# file-like object to the intake service as a callable
# source so the quarantine layer streams the bytes
# directly to disk without ever materialising the full
# archive in process memory.
UPLOAD_READ_CHUNK = 1024 * 1024


def _spooled_upload_source(spooled) -> Callable[[int], bytes]:
    """Return a callable that drains the upload into the quarantine.

    The callable yields successive chunks from the
    upload's underlying file-like object until the upload
    is exhausted; an empty ``bytes`` value signals end of
    stream. The quarantine layer reads in
    :data:`DEFAULT_CHUNK_SIZE` increments; the callable
    is therefore agnostic to the requested chunk size.
    """

    def _source(_chunk_size: int) -> bytes:
        return spooled.read(UPLOAD_READ_CHUNK)

    return _source


@router.post(
    "/upload",
    response_model=IntakeResultRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a ZIP archive and prepare a queued scan.",
)
async def create_uploaded_repository(
    session: DBSession,
    file: UploadFile = File(...),
) -> IntakeResultRead:
    """Stream ``file`` to a quarantine, validate it, and prepare a queued scan.

    The endpoint deliberately accepts only a single file.
    The upload is streamed chunk-by-chunk to the quarantine
    layer, which writes the bytes to a bounded temporary
    file and computes the SHA-256 on the fly. The body is
    never fully materialised in process memory; the only
    cap that applies here is the application setting
    ``LOCKVERITY_ARCHIVE_MAX_COMPRESSED_BYTES``, which the
    quarantine layer enforces as it writes.
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
        # The error envelope must never echo the raw
        # client-supplied filename: a pathful value
        # (``C:\\Users\\me\\secret.zip``) must not leak
        # through the response. The detail surfaces only
        # the **sanitised** basename (``basename_safely``
        # returns ``None`` for an unsafe value, in which
        # case the detail is the bounded empty string).
        from app.utils.errors import ApiError, ApiErrorCode
        from app.utils.paths import basename_safely

        safe_filename = basename_safely(file.filename) or ""
        raise ApiError(
            ApiErrorCode.VALIDATION_ERROR,
            "Uploaded file must have a .zip extension.",
            details={"filename": safe_filename},
        )

    # Apply the configured compressed-byte cap with an early
    # ``Content-Length`` short-circuit when the upstream
    # declares a length that already exceeds the cap. We
    # never read the body when the declared length is
    # already too large; the quarantine layer enforces
    # the same cap for streams that omit ``Content-Length``
    # or lie about it.
    settings = get_settings()
    cap = settings.archive_max_compressed_bytes
    declared = file.size
    if declared is not None and declared > cap:
        from app.utils.errors import ApiError, ApiErrorCode

        raise ApiError(
            ApiErrorCode.VALIDATION_ERROR,
            "Upload exceeds the configured size cap.",
            details={
                "declared_bytes": declared,
                "max_compressed_bytes": cap,
            },
        )

    # Hand Starlette's spooled file directly to the
    # intake service. The quarantine layer reads from
    # ``file.file`` in fixed-size chunks and writes to a
    # temporary file under the workspace; the archive
    # body is never fully materialised in process memory.
    spooled = file.file
    if not hasattr(spooled, "read"):
        # Fallback for test stubs that pass a plain
        # ``bytes`` object: read the whole body once, then
        # iterate. The endpoint tests use a real Starlette
        # ``UploadFile``; this branch is for ad-hoc use.
        spooled = _BytesBuffer(spooled)

    service = intake_service.IntakeService(session)
    result = service.intake_upload(
        upload=_spooled_upload_source(spooled),
        archive_filename=file.filename,
    )
    return _result_to_read(result)


class _BytesBuffer:
    """In-memory iterator used when ``file.file`` is a plain ``bytes``.

    Starlette's :class:`UploadFile` always exposes a
    file-like ``.file`` attribute. In production that is a
    ``SpooledTemporaryFile``; in unit tests it is sometimes a
    plain ``bytes`` instance. The intake service expects a
    callable source; this adapter bridges the two shapes
    so the production code path can stay stream-only.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        if self._pos >= len(self._data):
            return b""
        if size < 0:
            chunk = self._data[self._pos :]
            self._pos = len(self._data)
            return chunk
        end = min(self._pos + size, len(self._data))
        chunk = self._data[self._pos : end]
        self._pos = end
        return chunk


__all__ = ["UPLOAD_READ_CHUNK", "_result_to_read", "_workspace_to_read", "router"]
