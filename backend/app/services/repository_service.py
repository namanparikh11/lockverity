"""Repository service.

Wraps the GitHub URL normalization, uniqueness checks, and the small
amount of default-state the application holds per repository.

This service does *not* call any external provider - in v0.1 there is
no GitHub authentication, no metadata fetch, and no archive
introspection. Creating a repository is a pure database operation
that records the user's intent to analyze a given public URL.
"""

from __future__ import annotations

import contextlib
import logging
import secrets
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.repository import (
    Repository,
)
from app.repositories import repository_repo
from app.utils.errors import ApiError, ApiErrorCode
from app.utils.repo_url import (
    NormalizedRepositoryUrl,
    RepositoryUrlError,
    normalize_github_url,
)

logger = logging.getLogger("lockverity.repository_service")


def normalize_input_url(url: str) -> NormalizedRepositoryUrl:
    """Normalize a user-supplied GitHub URL.

    Raises :class:`ApiError` with code ``validation_error`` for any
    input that does not match the accepted public-GitHub shape.
    """
    try:
        return normalize_github_url(url)
    except RepositoryUrlError as exc:
        raise ApiError(
            ApiErrorCode.VALIDATION_ERROR,
            "Repository URL is not a valid public GitHub URL.",
            details={"reason": str(exc)},
        ) from exc


def create_repository_from_url(session: Session, url: str) -> Repository:
    """Create a repository record from a GitHub URL.

    The function is idempotent on the canonical URL: if a repository
    with the same normalized URL already exists, that record is
    returned. Otherwise a new repository is created and committed.
    """
    normalized = normalize_input_url(url)
    existing = repository_repo.get_repository_by_canonical_url(session, normalized.canonical_url)
    if existing is not None:
        return existing

    repo = repository_repo.create_github_repository(
        session,
        owner=normalized.owner,
        name=normalized.name,
        canonical_url=normalized.canonical_url,
    )
    try:
        session.commit()
    except IntegrityError as exc:
        # A concurrent insert won the race; fall back to the
        # canonical-URL lookup so the API is still idempotent.
        session.rollback()
        existing = repository_repo.get_repository_by_canonical_url(
            session, normalized.canonical_url
        )
        if existing is not None:
            return existing
        raise ApiError(
            ApiErrorCode.DUPLICATE,
            "Repository already exists with conflicting identity.",
            details={"canonical_url": normalized.canonical_url},
        ) from exc
    return repo


def safe_create_repository_from_url(session: Session, url: str) -> Repository:
    """Defence-in-depth safe wrapper around :func:`create_repository_from_url`.

    v2.1.1: the legacy ``POST /repositories`` endpoint remains
    reachable for backwards compatibility (other clients, scripts,
    curl, the prior ``/repositories/new`` form, etc.). The v1.5
    guided-intake page submits through
    ``POST /repositories/github`` instead, so the legacy endpoint
    is not the primary bundled-UI path; this wrapper exists to
    keep the legacy endpoint safe in case an unhandled exception
    ever escapes the inner service call.

    Contract mirrors :meth:`IntakeService.intake_github`:

    - classified ``ApiError`` instances are re-raised as-is
      (``validation_error``, ``duplicate``, etc.);
    - any other ``Exception`` is sanitised into the documented
      ``INTERNAL_UNEXPECTED`` envelope with a non-PII
      16-character lowercase hex ``correlation_id``;
    - the full traceback is logged with the same id so an
      operator can cross-reference the response and the log;
    - the response carries no path, token, raw exception, or
      upstream body;
    - the SQLAlchemy session is rolled back best-effort so
      a half-written row does not survive a failed write.
    """
    try:
        return create_repository_from_url(session, url)
    except ApiError:
        # Classified: ``validation_error`` from URL
        # normalisation, ``duplicate`` from the concurrent
        # insert race. Re-raise without modification so the
        # inner handler owns the message and the
        # ``details`` envelope.
        raise
    except Exception as exc:
        correlation_id = secrets.token_hex(8)
        logger.exception(
            "repository_create internal error (correlation_id=%s, kind=%s)",
            correlation_id,
            "repository",
        )
        with contextlib.suppress(Exception):
            session.rollback()
        raise ApiError(
            ApiErrorCode.INTERNAL_UNEXPECTED,
            "An internal error occurred. See Diagnostics for the "
            "correlation id and the runtime log for the full trace.",
            details={
                "correlation_id": correlation_id,
                "kind": "repository",
            },
        ) from exc


def get_repository_or_404(session: Session, repository_id: int) -> Repository:
    repo = repository_repo.get_repository_by_id(session, repository_id)
    if repo is None:
        raise ApiError(
            ApiErrorCode.NOT_FOUND,
            "Repository not found.",
            details={"repository_id": repository_id},
        )
    return repo


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

    v2.0.5: accepts bounded search and filter kwargs that
    mirror the ``GET /repositories`` query parameters. The
    underlying ``repository_repo.list_repositories`` keeps
    the SQLAlchemy predicate logic; this service layer is a
    thin pass-through.
    """
    return repository_repo.list_repositories(
        session,
        page=page,
        page_size=page_size,
        search=search,
        provider=provider,
        source_type=source_type,
        archived=archived,
    )
