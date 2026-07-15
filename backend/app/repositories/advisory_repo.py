"""Advisory data-access helpers.

The :class:`Advisory` table is shared between OSV (the v0.4
client) and any future vulnerability provider. The repository
hides the ``get_or_create`` shape so the provider service can
call it without re-deriving the query each time.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.advisory import Advisory


def get_by_source_id(
    session: Session,
    *,
    source: str,
    source_advisory_id: str,
) -> Advisory | None:
    """Return the advisory row identified by ``(source, source_advisory_id)``.

    The pair is unique by the table constraint. We never use
    the canonical_id (a CVE / GHSA alias) as the lookup key
    because the same canonical id can be reported by many
    sources.
    """
    return (
        session.query(Advisory)
        .filter(
            Advisory.source == source,
            Advisory.source_advisory_id == source_advisory_id,
        )
        .one_or_none()
    )


def get_or_create(
    session: Session,
    *,
    source: str,
    source_advisory_id: str,
    canonical_id: str | None = None,
    summary: str | None = None,
    details_url: str | None = None,
    published_at: datetime | None = None,
    modified_at: datetime | None = None,
    withdrawn_at: datetime | None = None,
    raw_payload_sha256: str | None = None,
) -> Advisory:
    """Return the existing advisory row or create a new one.

    Identity fields (source, source_advisory_id) are not
    overwritten on subsequent calls. Diagnostic fields
    (summary, details_url, timestamps) are refreshed on each
    call so the most recent provider call wins.
    """
    existing = get_by_source_id(session, source=source, source_advisory_id=source_advisory_id)
    if existing is not None:
        existing.canonical_id = canonical_id or existing.canonical_id
        existing.summary = summary or existing.summary
        existing.details_url = details_url or existing.details_url
        existing.published_at = published_at or existing.published_at
        existing.modified_at = modified_at or existing.modified_at
        existing.withdrawn_at = withdrawn_at or existing.withdrawn_at
        existing.raw_payload_sha256 = raw_payload_sha256 or existing.raw_payload_sha256
        return existing
    advisory = Advisory(
        source=source,
        source_advisory_id=source_advisory_id,
        canonical_id=canonical_id,
        summary=summary,
        details_url=details_url,
        published_at=published_at,
        modified_at=modified_at,
        withdrawn_at=withdrawn_at,
        raw_payload_sha256=raw_payload_sha256,
    )
    session.add(advisory)
    session.flush()
    return advisory


def list_for_scan(
    session: Session,
    scan_run_id: int,
    *,
    limit: int | None = None,
) -> list[Advisory]:
    """Return every advisory referenced by a scan (via ComponentAdvisory)."""
    from app.models.component_advisory import ComponentAdvisory

    stmt = (
        session.query(Advisory)
        .join(ComponentAdvisory, ComponentAdvisory.advisory_id == Advisory.id)
        .filter(ComponentAdvisory.scan_run_id == scan_run_id)
        .order_by(Advisory.id.asc())
        .distinct()
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(stmt.all())


__all__ = ["get_by_source_id", "get_or_create", "list_for_scan"]
