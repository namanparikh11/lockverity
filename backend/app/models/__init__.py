"""ORM models package.

Every model in :mod:`lockverity.models` is exported here so Alembic
autogeneration can pick them up via ``Base.metadata``.
"""

from __future__ import annotations

from app.models.advisory import Advisory
from app.models.component import Component, ComponentVersionSource
from app.models.component_advisory import ComponentAdvisory
from app.models.dependency_edge import DependencyEdge
from app.models.finding import (
    Finding,
    FindingCategory,
    FindingConfidence,
    FindingSeverity,
    FindingStatus,
)
from app.models.manifest import Manifest, ManifestParseStatus
from app.models.provider_observation import (
    ProviderObservation,
    ProviderStatus,
)
from app.models.repository import (
    Repository,
    RepositoryProvider,
    RepositorySourceType,
    RepositoryVisibility,
)
from app.models.scan_run import ScanRun, ScanStatus, ScanTriggerType
from app.models.scan_stage import ScanStage, StageStatus, StageType

__all__ = [
    "Advisory",
    "Component",
    "ComponentAdvisory",
    "ComponentVersionSource",
    "DependencyEdge",
    "Finding",
    "FindingCategory",
    "FindingConfidence",
    "FindingSeverity",
    "FindingStatus",
    "Manifest",
    "ManifestParseStatus",
    "ProviderObservation",
    "ProviderStatus",
    "Repository",
    "RepositoryProvider",
    "RepositorySourceType",
    "RepositoryVisibility",
    "ScanRun",
    "ScanStage",
    "ScanStatus",
    "ScanTriggerType",
    "StageStatus",
    "StageType",
]
