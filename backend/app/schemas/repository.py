"""Repository API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import field_validator

from app.models.repository import (
    RepositoryProvider,
    RepositorySourceType,
    RepositoryVisibility,
)
from app.models.scan_run import ScanStatus, ScanTriggerType
from app.schemas.common import NonEmptyStr, SchemaModel, TimestampMixin


class RepositoryCreate(SchemaModel):
    """Payload for ``POST /api/v1/repositories``.

    For now only public GitHub repositories are accepted. Uploaded
    archives are a separate, archive-specific endpoint that arrives in
    a later milestone.
    """

    canonical_url: NonEmptyStr


class RepositoryRead(TimestampMixin):
    id: int
    source_type: RepositorySourceType
    provider: RepositoryProvider
    owner: str
    name: str
    canonical_url: str | None = None
    default_branch: str | None = None
    description: str | None = None
    visibility: RepositoryVisibility
    archived: bool
    last_provider_sync_at: datetime | None = None
    # v2.0.5: human-readable primary label. Basename of the
    # uploaded filename for uploaded archives, ``None`` for
    # GitHub repositories (the operator uses ``owner/name``
    # instead). Backwards-compatible additive field. The
    # value is sanitised at write time (``basename_safely``)
    # by the intake service; the field validator below is
    # defence-in-depth for historical rows that pre-date
    # the sanitiser or that were inserted by an operator
    # with a tool that bypassed it.
    original_filename: str | None = None

    @field_validator("original_filename", mode="before")
    @classmethod
    def _sanitise_original_filename(cls, value: object) -> object:
        """Apply :func:`basename_safely` at the API boundary.

        Defence in depth: a pathful value is reduced to
        a basename or ``None`` before the response is
        serialised. The intake layer sanitises the
        value at write time; this validator covers any
        historical row that pre-dates the sanitiser.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        from app.utils.paths import basename_safely

        return basename_safely(value)


# v2.0.5: per-row summary data returned alongside each
# repository in the list response. The summary is computed by
# a single batched query (``get_repository_summaries``) so
# the list endpoint does not produce an N+1 request pattern
# to look up per-row scan counts.
class RepositoryLatestScan(SchemaModel):
    """The most recent scan for a repository, or ``None`` if no scans exist."""

    id: int
    status: ScanStatus
    trigger_type: ScanTriggerType
    created_at: datetime
    completed_at: datetime | None = None


class RepositorySummary(SchemaModel):
    """Bounded summary of a repository's scan history.

    ``scan_count`` is the total number of scan rows for the
    repository. ``eligible_comparison_scan_count`` is the
    number of scans that the comparator will accept
    (``completed`` or ``partial``; the same set the
    ``/repositories/{id}/compare`` page uses). ``latest_scan``
    is the scan with the largest ``id`` (monotonic on
    SQLite); it is ``None`` when no scan has ever run.
    """

    scan_count: int
    eligible_comparison_scan_count: int
    latest_scan: RepositoryLatestScan | None = None


class RepositoryWithSummary(RepositoryRead):
    """``RepositoryRead`` augmented with the per-row summary.

    Used by ``GET /api/v1/repositories`` to keep the
    existing ``RepositoryRead`` shape backwards-compatible
    for callers that ignore the new fields.
    """

    summary: RepositorySummary
    # Bounded human-readable label: ``owner/repository`` for
    # GitHub rows, ``original_filename`` for uploaded rows
    # (or the bounded fallback when ``original_filename``
    # is null). Callers use this as the primary row title;
    # the opaque ``canonical_url`` is the secondary technical
    # identifier. The field is computed server-side; the
    # frontend never assembles a label from the raw
    # ``owner``/``name`` pair.
    display_name: str
    # Secondary technical identifier: ``owner/repository`` for
    # GitHub rows, ``upload/<short-key>`` for uploaded rows
    # (derived from ``canonical_url``). The frontend renders
    # this as the muted sub-line under the primary title.
    canonical_identity: str


# v2.0.5: the search-mode field is included so the frontend
# can render a search-state banner if it ever wants to. The
# actual predicate is on the server side; the response does
# not leak the literal query.
RepositorySearchMode = Literal["free_text", "scan_id"]
