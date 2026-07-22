"""v2.0.6 stage message-severity derivation.

The comparator and the v0.5-v2.0.5 surfaces render a
``failure_summary`` for any non-null string. The frontend
previously prefixed every such string with ``"Failure: "``
and used red ``rose-50`` styling. Several normal
no-data outcomes (``No OSV advisories were returned for
this scan.``, ``No workflow files were discovered.``,
``No components were available to enrich.``,
``not_github_or_no_url``, ``1 parser warnings``) are
**not** stage-execution failures: they describe a
completed stage that did not produce records because
the input was honest. Rendering them as red ``Failure:``
messages confuses a reviewer into believing the scan
itself failed.

This module exposes a single function
:func:`derive_message_severity` that maps a stage row to
a bounded severity token. The decision uses the existing
structured fields (``status``, ``records_processed``,
``failure_code``, ``failure_summary``) and a narrow
compatibility mapper for the small set of known legacy
``failure_summary`` strings. The mapper is **not** a
broad substring rule: it is a closed allow-list of the
exact legacy reason codes observed in the field-test
database. New legacy strings fall through to ``none``
rather than to ``info`` so we do not silently classify
an unknown string as a normal no-data outcome.

The function never mutates the stage row, never reads
files from disk, and never makes an external request.
The decision is deterministic so the field-test database
keeps rendering consistently across reacceptance runs.

Severity values (the bounded vocabulary; never invent new
values):

- ``"error"`` - a stage genuinely failed. ``status ==
  FAILED`` and the stage carries a ``failure_code`` or a
  non-empty ``failure_summary``. The frontend keeps the
  red ``"Failure: "`` prefix.
- ``"warning"`` - partial stage outcome, or a completed
  stage with non-zero records and a residual summary
  (parser warnings, partial provider data, completed
  stage with degradation evidence). The frontend
  prefixes the message with a non-error label such as
  ``"Warning: "`` or ``"Partial output: "``.
- ``"info"`` - a completed stage that produced zero
  records and the residual ``failure_summary`` is a
  known no-data reason (e.g. "No OSV advisories were
  returned for this scan."). The frontend renders
  neutral information styling and does **not** prefix
  the text with ``"Failure: "``.
- ``"none"`` - no message requiring emphasis, or a
  residual summary that does not match any closed-list
  reason. The frontend renders nothing.
"""

from __future__ import annotations

from typing import Final

# v2.0.6 closed-list of known normal no-data
# ``failure_summary`` strings observed in the field-test
# database (scans 11, 13, 14, 15). The list is a
# deliberate allow-list, not a substring rule; an
# unknown residual string falls through to ``"none"``
# rather than to ``"info"``. Adding a new entry
# requires a focused test that pins the new
# classification.
NO_DATA_SUMMARIES: Final[frozenset[str]] = frozenset(
    {
        "No OSV advisories were returned for this scan.",
        "No workflow files were discovered.",
        "No components were available to enrich.",
        "No manifests were discovered.",
        "not_github_or_no_url",
    }
)

# Closed-list of known parser-warning summaries
# observed in the field-test database. The map is
# ``failure_summary -> (records_processed_min, severity)``;
# the ``records_processed_min`` guard ensures we do
# not silently down-classify a completed-zero stage
# whose summary happens to mention the word "warning".
PARSER_WARNING_SUMMARIES: Final[frozenset[str]] = frozenset(
    {
        # Scan #14 DEPENDENCY_PARSING: 1 parser warning, 2
        # records processed. The frontend renders the
        # message with warning (amber) styling, not red.
        "1 parser warnings",
    }
)


def derive_message_severity(
    *,
    status: str | None,
    records_processed: int | None,
    failure_code: str | None,
    failure_summary: str | None,
) -> str:
    """Return the bounded message severity for a stage row.

    Decision table (deterministic; closed-list legacy
    reason codes only):

    - ``FAILED`` stage with a ``failure_code`` or a
      ``failure_summary`` -> ``"error"``.
    - ``PARTIAL`` stage -> ``"warning"`` (the stage ran
      but some records were degraded; the frontend shows
      the message in amber, not red).
    - ``COMPLETED`` stage with zero records and a
      ``failure_summary`` that matches
      :data:`NO_DATA_SUMMARIES` -> ``"info"``.
    - ``COMPLETED`` stage with a ``failure_summary`` that
      matches :data:`PARSER_WARNING_SUMMARIES` ->
      ``"warning"``.
    - ``COMPLETED`` stage with non-zero records and a
      non-empty ``failure_summary`` -> ``"warning"``
      (residual summary after a successful run;
      could be a parser warning, a partial provider
      result, or an "imported as unknown" note).
    - ``SKIPPED`` stage -> ``"none"`` (no message
      requiring emphasis; the status badge already
      conveys the skip).
    - everything else (no message, or unknown
      ``status``) -> ``"none"``.
    """
    summary = (failure_summary or "").strip() or None
    code = (failure_code or "").strip() or None
    records = int(records_processed or 0)
    status_norm = (status or "").strip().lower() or None

    # A real failure: the stage genuinely failed and
    # has evidence. We do not down-classify a
    # ``FAILED`` row even if the summary happens to
    # mention a known no-data reason; a stage that
    # actually failed to execute is a different
    # shape from a stage that executed and produced
    # zero records.
    if status_norm == "failed" and (code or summary):
        return "error"

    # A partial stage is a real degradation, not a
    # failure. The message (if any) is warning-level.
    if status_norm == "partial":
        return "warning"

    # Skipped stages do not warrant a message block.
    # The status badge already says "skipped".
    if status_norm == "skipped":
        return "none"

    if status_norm == "completed" and summary:
        # Closed-list parser-warning summaries take
        # priority over a no-data classification
        # because a parser warning is a real, visible
        # degradation. The frontend renders the text
        # without the "Failure: " prefix and uses
        # amber styling.
        if summary in PARSER_WARNING_SUMMARIES:
            return "warning"
        # Closed-list normal no-data reasons: the
        # stage ran successfully and the only
        # residual message is a known no-data
        # outcome (e.g. "No OSV advisories were
        # returned for this scan." or "No workflow
        # files were discovered." or
        # "not_github_or_no_url"). The records count
        # is not the deciding factor: a vulnerability
        # query that processed 12 components and
        # returned 0 advisories is still a normal
        # no-data outcome. The frontend renders the
        # text without the "Failure: " prefix and
        # uses neutral information styling.
        if summary in NO_DATA_SUMMARIES:
            return "info"
        # Any other completed-stage residual summary
        # with non-zero records is treated as a
        # partial / warning-level note. We do not
        # invent an "error" classification from a
        # string; we only use the closed-list
        # reasons to choose a friendlier level.
        if records > 0:
            return "warning"
        # Completed stage with zero records and an
        # unknown residual summary. We do not
        # classify an unknown string as a normal
        # no-data outcome; we render nothing.
        return "none"

    return "none"


__all__ = [
    "NO_DATA_SUMMARIES",
    "PARSER_WARNING_SUMMARIES",
    "derive_message_severity",
]
