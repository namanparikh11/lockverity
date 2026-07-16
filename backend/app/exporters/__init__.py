"""Exporters package.

Exporters implement the :class:`app.providers.contracts.ReportExporter`
protocol. Each exporter is a class with a ``format`` attribute and
an ``export`` method that takes a ``scan_run_id`` and returns
either a :class:`ProviderSuccess[bytes]` or a
:class:`ProviderUnavailable`.
"""

from __future__ import annotations

from app.exporters.cyclonedx import CycloneDxExporter
from app.exporters.cyclonedx_v17 import (
    CYCLONEDX_FORMAT_KEY,
    CYCLONEDX_MEDIA_TYPE,
    CYCLONEDX_SCHEMA_URI,
    CYCLONEDX_SPEC_VERSION,
    CycloneDxV17Exporter,
)
from app.exporters.findings_csv import FindingsCsvExporter
from app.exporters.findings_json import FindingsJsonExporter
from app.exporters.sarif import SarifStaticFindingsExporter

__all__ = [
    "CYCLONEDX_FORMAT_KEY",
    "CYCLONEDX_MEDIA_TYPE",
    "CYCLONEDX_SCHEMA_URI",
    "CYCLONEDX_SPEC_VERSION",
    "CycloneDxExporter",
    "CycloneDxV17Exporter",
    "FindingsCsvExporter",
    "FindingsJsonExporter",
    "SarifStaticFindingsExporter",
]
