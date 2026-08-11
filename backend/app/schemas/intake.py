"""Intake API schemas (GitHub URL, ZIP upload)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from app.models.workspace import WorkspaceKind, WorkspaceState
from app.providers.selection import ExternalEvidenceProviders
from app.schemas.common import NonEmptyStr, SchemaModel, ShortStr, TimestampMixin
from app.schemas.repository import RepositoryRead
from app.schemas.scan import ScanRead


class GitHubRepositoryCreate(SchemaModel):
    """Payload for ``POST /api/v1/repositories/github``."""

    canonical_url: NonEmptyStr
    requested_ref: ShortStr | None = None


class UploadedArchiveCreate(SchemaModel):
    """Payload for ``POST /api/v1/repositories/upload``.

    The actual bytes are sent as a multipart file field. The
    JSON portion of the request is optional; the route only
    needs the file.
    """

    description: ShortStr | None = None


class WorkspaceRead(TimestampMixin):
    """The safe metadata view of a workspace returned to the API."""

    id: int
    scan_run_id: int
    workspace_key: str
    kind: WorkspaceKind
    state: WorkspaceState
    # ``archive_filename`` is sanitised at write time
    # (``basename_safely``) by the workspace service.
    # The field validator below is defence-in-depth for
    # historical rows that pre-date the sanitiser, or
    # for operator-inserted rows that bypassed it. A
    # pathful value (Windows drive letter, POSIX
    # absolute path, parent traversal) is reduced to a
    # basename or ``None`` at the API boundary so the
    # public response never exposes a local absolute
    # path.
    archive_filename: str | None = None
    archive_sha256: str | None = None
    archive_size: int
    file_count: int
    uncompressed_size: int
    failure_code: str | None = None
    failure_summary: str | None = None
    ready_at: datetime | None = None
    cleaned_up_at: datetime | None = None

    @field_validator("archive_filename", mode="before")
    @classmethod
    def _sanitise_archive_filename(cls, value: object) -> object:
        """Apply :func:`basename_safely` at the API boundary.

        The intake layer sanitises the value at write
        time, but historical rows that pre-date the
        sanitiser (or rows inserted by an operator with
        a tool that bypassed it) can still carry a
        pathful value. The validator is the public
        boundary's last line of defence: a pathful value
        is reduced to a basename or ``None`` before the
        response is serialised.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        # Local import to avoid a circular dependency at
        # module load time; the helper is small and the
        # import is cached after the first call.
        from app.utils.paths import basename_safely

        return basename_safely(value)


class IntakeSummary(SchemaModel):
    """A free-form summary of the intake (different per source)."""

    values: dict[str, Any]


class IntakeResultRead(SchemaModel):
    """The full intake result returned to the API."""

    repository: RepositoryRead
    scan: ScanRead
    workspace: WorkspaceRead
    intake_summary: dict[str, Any]


class ScanCancelRequest(SchemaModel):
    """Optional payload for ``POST /api/v1/scans/{id}/cancel``."""

    reason: ShortStr | None = None


class ExternalEvidenceProvidersRequest(SchemaModel):
    """External evidence providers requested for one scan run."""

    osv: bool = True
    deps_dev: bool = True
    openssf: bool = True

    def to_domain(self) -> ExternalEvidenceProviders:
        return ExternalEvidenceProviders(
            osv=self.osv,
            deps_dev=self.deps_dev,
            openssf=self.openssf,
        )


class ScanRunRequest(SchemaModel):
    """Optional payload for ``POST /api/v1/scans/{id}/run``."""

    force: bool = False
    external_evidence_providers: ExternalEvidenceProvidersRequest | None = None

    def provider_selection(self) -> ExternalEvidenceProviders:
        requested = self.external_evidence_providers
        return requested.to_domain() if requested is not None else ExternalEvidenceProviders()


class ProviderLimit(SchemaModel):
    """Per-provider rate-limit snapshot."""

    provider: str
    operation: str
    status: str
    cache_status: str | None = None
    retry_after: datetime | None = None
    rate_limit_remaining: int | None = None
    rate_limit_reset: datetime | None = None


class SystemProviderLimitsResponse(SchemaModel):
    """Payload for ``GET /api/v1/system/provider-limits``."""

    github: list[ProviderLimit] = Field(default_factory=list)
    overall_cache_size: int = 0


class SystemWorkspaceCleanupResponse(SchemaModel):
    """Payload for ``POST /api/v1/system/workspaces/cleanup``."""

    removed: int
    removed_workspaces: list[WorkspaceRead] = Field(default_factory=list)


__all__ = [
    "ExternalEvidenceProvidersRequest",
    "GitHubRepositoryCreate",
    "IntakeResultRead",
    "IntakeSummary",
    "ProviderLimit",
    "ScanCancelRequest",
    "ScanRunRequest",
    "SystemProviderLimitsResponse",
    "SystemWorkspaceCleanupResponse",
    "UploadedArchiveCreate",
    "WorkspaceRead",
]
