"""Repository data-access helpers.

Pagination and ordering are baked in here so route handlers and
services have a single, stable contract. ``list_repositories`` does
not eager-load scans; callers that need scan counts can do a separate
aggregate query to avoid N+1 behavior in list endpoints.

v2.0.5: ``list_repositories`` now accepts ``search``, ``provider``,
``source_type``, and ``archived`` filter kwargs that mirror the
``GET /repositories`` query parameters. Search matches a bounded
set of persisted fields (filename, display fields, canonical URL,
canonical upload identifier, and exact repository / scan IDs). The
``get_repository_summaries`` companion function returns per-row
``scan_count`` / ``latest_scan`` / ``eligible_comparison_count``
data in a single batched query.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models.repository import (
    Repository,
    RepositoryProvider,
    RepositorySourceType,
)
from app.models.scan_run import ScanRun, ScanStatus

# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def get_repository_by_id(session: Session, repository_id: int) -> Repository | None:
    return session.get(Repository, repository_id)


def get_repository_by_canonical_url(session: Session, canonical_url: str) -> Repository | None:
    stmt = select(Repository).where(Repository.canonical_url == canonical_url)
    return session.execute(stmt).scalar_one_or_none()


def get_repository_by_identity(
    session: Session,
    *,
    provider: RepositoryProvider,
    owner: str,
    name: str,
) -> Repository | None:
    stmt = select(Repository).where(
        Repository.provider == provider,
        Repository.owner == owner,
        Repository.name == name,
    )
    return session.execute(stmt).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def create_github_repository(
    session: Session,
    *,
    owner: str,
    name: str,
    canonical_url: str,
    description: str | None = None,
    default_branch: str | None = None,
    visibility: str | None = None,
) -> Repository:
    from app.models.repository import RepositoryVisibility

    repo = Repository(
        source_type=RepositorySourceType.GITHUB,
        provider=RepositoryProvider.GITHUB,
        owner=owner,
        name=name,
        canonical_url=canonical_url,
        description=description,
        default_branch=default_branch,
        visibility=(
            RepositoryVisibility(visibility) if visibility else RepositoryVisibility.PUBLIC
        ),
    )
    session.add(repo)
    session.flush()
    return repo


# ---------------------------------------------------------------------------
# v2.0.5: bounded search predicate
# ---------------------------------------------------------------------------
#
# A repository row has many fields that could conceivably match a
# search query. We restrict the predicate to a small set of
# persisted fields that the operator is most likely to type:
#
# - GitHub ``owner`` and ``name`` (e.g. "octocat Hello-World")
# - canonical URL (the full ``https://github.com/...`` form)
# - canonical upload identifier (e.g. ``upload://<marker>``)
# - uploaded original filename (e.g. "test-09-mixed-monorepo.zip")
# - exact repository ID
# - exact scan ID (resolved to the parent repository via subquery)
#
# The predicate is always parameterised; raw SQL string
# interpolation is never used. A leading or trailing ``#`` is
# stripped from scan-ID inputs so that ``#15`` and ``15`` both
# resolve to the same numeric ID.
def _search_predicate(
    *,
    term: str,
    has_scan_id: bool,
    scan_id: int | None,
) -> Any:
    """Return a SQLAlchemy predicate that matches ``term``.

    ``has_scan_id``/``scan_id`` resolve scan-ID searches to
    the parent repository via a scalar subquery on
    ``scan_runs``. A scan-ID search returns at most one
    repository; a free-text search returns all matching
    rows. The two modes are mutually exclusive: a scan-ID
    search does not also run the free-text ``ilike``
    predicate, because a pure digit token should not also
    match every owner / name fragment that contains a
    matching digit.
    """
    if has_scan_id and scan_id is not None:
        scan_subq = select(ScanRun.repository_id).where(ScanRun.id == scan_id).scalar_subquery()
        return Repository.id == scan_subq
    pattern = f"%{term}%"
    free_text_clauses = [
        Repository.owner.ilike(pattern),
        Repository.name.ilike(pattern),
        Repository.canonical_url.ilike(pattern),
        Repository.original_filename.ilike(pattern),
    ]
    return or_(*free_text_clauses)


# ---------------------------------------------------------------------------
# Pagination and search
# ---------------------------------------------------------------------------


def list_repositories(
    session: Session,
    *,
    page: int,
    page_size: int,
    search: str | None = None,
    provider: str | None = None,
    source_type: str | None = None,
    archived: str | None = None,
) -> tuple[Sequence[Repository], int]:
    """Return a page of repositories plus the total count.

    ``search`` matches a bounded set of persisted fields
    (owner, name, canonical URL, original filename, canonical
    upload identifier, or a scan ID that resolves to the
    parent repository). ``provider``, ``source_type``, and
    ``archived`` are exact-match enum-style filters. All
    parameters are bound; raw SQL string interpolation is
    never used.
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")
    base = select(Repository)
    count_base = select(func.count()).select_from(Repository)
    conditions = []
    if provider:
        conditions.append(Repository.provider == provider)
    if source_type:
        conditions.append(Repository.source_type == source_type)
    if archived == "archived":
        conditions.append(Repository.archived.is_(True))
    elif archived == "active":
        conditions.append(Repository.archived.is_(False))
    if search:
        scan_id = _parse_scan_id_token(search)
        term = search.lstrip("#").strip()
        if scan_id is not None:
            # Pure scan-ID search: exact match on the parent
            # repository via an EXISTS subquery. We do not
            # also run the free-text ``ilike`` predicate,
            # because a pure digit token should not also
            # match owner/name fragments.
            conditions.append(_search_predicate(term="", has_scan_id=True, scan_id=scan_id))
        elif term:
            conditions.append(_search_predicate(term=term, has_scan_id=False, scan_id=None))
    if conditions:
        base = base.where(and_(*conditions))
        count_base = count_base.where(and_(*conditions))
    total = session.execute(count_base).scalar_one()
    stmt = base.order_by(Repository.id.desc()).limit(page_size).offset((page - 1) * page_size)
    items = session.execute(stmt).scalars().all()
    return items, int(total or 0)


def _parse_scan_id_token(raw: str) -> int | None:
    """Return the integer scan ID for a pure ``#N``/``N`` token, else None.

    A token that contains any non-digit character (other than a
    leading ``#``) is treated as a free-text query, not a scan
    ID. This is conservative: a stray letter never resolves
    to a scan.
    """
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned.startswith("#"):
        cleaned = cleaned[1:]
    if not cleaned:
        return None
    if not cleaned.isdigit():
        return None
    return int(cleaned)


# ---------------------------------------------------------------------------
# v2.0.5: per-row summary (scan_count, latest_scan, eligible_comparison_count)
# ---------------------------------------------------------------------------
#
# This companion query is invoked once per request after the
# paginated list query. It returns a dict keyed by
# ``repository_id`` with the per-row data, so the route handler
# can render the row without making a per-row request (no N+1).
#
# ``eligible_comparison_count`` counts completed and partial
# scans (the same set the comparator accepts). ``latest_scan``
# is the scan with the largest ``id``; tie-breaking on
# ``created_at`` is not necessary because ``id`` is a
# monotonically-incrementing primary key in SQLite.
@dataclass(slots=True, frozen=True)
class RepositorySummary:
    repository_id: int
    scan_count: int
    latest_scan_id: int | None
    latest_scan_status: str | None
    latest_scan_created_at: Any  # datetime | None
    latest_scan_completed_at: Any  # datetime | None
    latest_scan_trigger_type: str | None
    eligible_comparison_scan_count: int


def get_repository_summaries(
    session: Session,
    repository_ids: Sequence[int],
) -> dict[int, RepositorySummary]:
    """Return per-row summary data for the given repository ids.

    The query is a single batched read; it does not issue a
    per-repository sub-query. A repository that has no scans
    appears in the result with ``scan_count=0`` and
    ``latest_scan_id=None``.
    """
    if not repository_ids:
        return {}
    rid_list = list(repository_ids)
    count_subq = (
        select(
            ScanRun.repository_id.label("rid"),
            func.count(ScanRun.id).label("scan_count"),
            func.sum(
                case(
                    (
                        ScanRun.status.in_([ScanStatus.COMPLETED, ScanStatus.PARTIAL]),
                        1,
                    ),
                    else_=0,
                )
            ).label("eligible_count"),
        )
        .where(ScanRun.repository_id.in_(rid_list))
        .group_by(ScanRun.repository_id)
        .subquery()
    )
    # Latest scan: pick the max ``id`` per repository. ``id`` is
    # monotonic; this avoids a window function and keeps the
    # query trivial on SQLite.
    latest_subq = (
        select(
            ScanRun.repository_id.label("rid"),
            func.max(ScanRun.id).label("latest_id"),
        )
        .where(ScanRun.repository_id.in_(rid_list))
        .group_by(ScanRun.repository_id)
        .subquery()
    )
    rows = session.execute(
        select(
            count_subq.c.rid,
            count_subq.c.scan_count,
            count_subq.c.eligible_count,
            ScanRun.id,
            ScanRun.status,
            ScanRun.created_at,
            ScanRun.completed_at,
            ScanRun.trigger_type,
        )
        .select_from(count_subq)
        .join(latest_subq, latest_subq.c.rid == count_subq.c.rid)
        .join(ScanRun, ScanRun.id == latest_subq.c.latest_id)
    ).all()
    out: dict[int, RepositorySummary] = {}
    for r in rows:
        out[r.rid] = RepositorySummary(
            repository_id=r.rid,
            scan_count=int(r.scan_count or 0),
            latest_scan_id=int(r.id) if r.id is not None else None,
            latest_scan_status=str(r.status.value) if r.status is not None else None,
            latest_scan_created_at=r.created_at,
            latest_scan_completed_at=r.completed_at,
            latest_scan_trigger_type=str(r.trigger_type.value)
            if r.trigger_type is not None
            else None,
            eligible_comparison_scan_count=int(r.eligible_count or 0),
        )
    # Fill in zero-summary rows for repositories that have no
    # scans at all.
    for rid in rid_list:
        if rid not in out:
            out[rid] = RepositorySummary(
                repository_id=rid,
                scan_count=0,
                latest_scan_id=None,
                latest_scan_status=None,
                latest_scan_created_at=None,
                latest_scan_completed_at=None,
                latest_scan_trigger_type=None,
                eligible_comparison_scan_count=0,
            )
    return out
