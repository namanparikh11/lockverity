"""Typed result objects for provider / parser / analyzer interactions.

Lockverity never represents an expected provider failure with an
exception. Callers receive one of the explicit result types below
and decide how to persist it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ProviderOutcome(str, Enum):
    """Coarse-grained outcome of a provider call."""

    SUCCESS = "success"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ProviderSuccess[T]:
    """Provider returned the requested data."""

    data: T
    fetched_at: datetime
    records_returned: int = 0


@dataclass(frozen=True, slots=True)
class ProviderPartialResult[T]:
    """Provider returned *some* data but signaled an error.

    ``data`` is safe to use; ``error_code`` and ``error_summary`` are
    diagnostic only. ``records_returned`` is the number of records
    successfully obtained.
    """

    data: T
    fetched_at: datetime
    records_returned: int
    error_code: str
    error_summary: str


@dataclass(frozen=True, slots=True)
class ProviderUnavailable:
    """Provider could not be reached or refused the request.

    The application must persist this outcome. Reporting
    "no vulnerabilities found" because the provider was unavailable
    is a correctness bug.
    """

    error_code: str
    error_summary: str
    attempted_at: datetime
    retry_after: datetime | None = None
    http_status: int | None = None
    outcome: ProviderOutcome = ProviderOutcome.UNAVAILABLE


@dataclass(frozen=True, slots=True)
class ParserWarning:
    """A single non-fatal warning raised by a parser."""

    code: str
    message: str
    location: str | None = None


@dataclass(frozen=True, slots=True)
class ParserResult[T]:
    """Outcome of a manifest parser run."""

    data: T
    warnings: tuple[ParserWarning, ...] = ()
    records_processed: int = 0


@dataclass(frozen=True, slots=True)
class FindingEvidence:
    """Structured evidence backing a finding."""

    rule_id: str
    location_path: str | None = None
    location_start_line: int | None = None
    location_end_line: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnalyzerResult:
    """Outcome of a static analyzer or rule evaluation."""

    findings: tuple[FindingEvidence, ...]
    warnings: tuple[ParserWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Outcome of a report export run."""

    artifact_path: str
    artifact_size: int
    content_sha256: str
    format: str
