"""Common API utilities."""

from __future__ import annotations

from app.schemas.common import PageMeta, page_meta
from app.schemas.repository import RepositoryRead
from app.schemas.scan import (
    FindingRead,
    ProviderObservationRead,
    ScanRead,
    ScanStageRead,
)
from app.utils.stage_severity import derive_message_severity


def repository_to_read(repo) -> RepositoryRead:
    return RepositoryRead.model_validate(repo)


def scan_to_read(scan) -> ScanRead:
    return ScanRead.model_validate(scan)


def stage_to_read(stage) -> ScanStageRead:
    """Map a ``ScanStage`` row to its read schema.

    v2.0.6: the ``message_severity`` field is computed
    at this boundary from the existing structured
    fields (``status``, ``records_processed``,
    ``failure_code``, ``failure_summary``). The decision
    uses the closed-list :func:`derive_message_severity`
    helper. The field is never persisted and never
    read back; it is a derived API-shape concern only.
    """
    payload = ScanStageRead.model_validate(stage).model_dump()
    payload["message_severity"] = derive_message_severity(
        status=getattr(stage, "status", None)
        and (stage.status.value if hasattr(stage.status, "value") else str(stage.status)),
        records_processed=getattr(stage, "records_processed", None),
        failure_code=getattr(stage, "failure_code", None),
        failure_summary=getattr(stage, "failure_summary", None),
    )
    return ScanStageRead(**payload)


def finding_to_read(finding) -> FindingRead:
    return FindingRead.model_validate(finding)


def observation_to_read(observation) -> ProviderObservationRead:
    return ProviderObservationRead.model_validate(observation)


def pagination(*, page: int, page_size: int, total: int) -> PageMeta:
    return page_meta(page=page, page_size=page_size, total=total)
