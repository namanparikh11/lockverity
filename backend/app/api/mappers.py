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


def repository_to_read(repo) -> RepositoryRead:
    return RepositoryRead.model_validate(repo)


def scan_to_read(scan) -> ScanRead:
    return ScanRead.model_validate(scan)


def stage_to_read(stage) -> ScanStageRead:
    return ScanStageRead.model_validate(stage)


def finding_to_read(finding) -> FindingRead:
    return FindingRead.model_validate(finding)


def observation_to_read(observation) -> ProviderObservationRead:
    return ProviderObservationRead.model_validate(observation)


def pagination(*, page: int, page_size: int, total: int) -> PageMeta:
    return page_meta(page=page, page_size=page_size, total=total)
