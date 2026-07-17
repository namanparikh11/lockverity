"""v1.0 human-readable evidence report.

The evidence report is a single authoritative backend rule
for the v1.0 read-only report surface. It is
deterministic, generated only from persisted evidence, and
never calls a provider, never downloads a repository, never
executes analyzed code, and never writes to the database.

The report reuses the v0.6 / v0.7 / v0.8 / v0.9 helpers
wherever possible so the report cannot disagree with the
detail drawer, the CycloneDX 1.7 export, or the evidence
summary:

- PURL well-formedness (``_is_purl_well_formed``);
- PURL constructibility (``_is_purl_constructible``);
- CycloneDX 1.7 export implications (the same rules the
  v0.6 exporter implements);
- CycloneDX eligibility / coverage vocabulary
  (``_inventory_coverage`` / ``_provider_coverage`` /
  ``_dependency_graph_coverage``);
- evidence summary flags (the same vocabulary the v0.9
  summary exposes).

The Markdown output is the only download surface in v1.0.
PDF, DOCX, HTML, signed attestations, and certification
exports are out of scope by design.
"""

from app.reports.evidence import (
    REPORT_FORMAT_KEY,
    REPORT_MEDIA_TYPE,
    EvidenceReportService,
    build_evidence_report,
    render_evidence_report_markdown,
)

__all__ = [
    "EVIDENCE_REPORT_OMISSIONS",
    "REPORT_FORMAT_KEY",
    "REPORT_MEDIA_TYPE",
    "EvidenceReportService",
    "build_evidence_report",
    "render_evidence_report_markdown",
]
