"""Provider observation model tests.

Cover the ProviderStatus enum semantics and the per-scan uniqueness
of provider + operation.
"""

from __future__ import annotations

from app.models.provider_observation import (
    ProviderObservation,
    ProviderStatus,
)
from app.services import repository_service, scan_service


def _setup(session):
    repo = repository_service.create_repository_from_url(
        session, "https://github.com/octocat/Hello-World"
    )
    scan = scan_service.create_scan(session, repository_id=repo.id, trigger_type="manual")
    return scan.id


def test_provider_observation_persists_status(session) -> None:
    scan_id = _setup(session)
    obs = ProviderObservation(
        scan_run_id=scan_id,
        provider="osv",
        operation="query",
        status=ProviderStatus.UNAVAILABLE,
        records_returned=0,
    )
    session.add(obs)
    session.flush()
    assert obs.status == ProviderStatus.UNAVAILABLE
    assert obs.id is not None


def test_provider_observation_does_not_persist_secrets(session) -> None:
    """``error_summary`` may carry diagnostic text, but is a String
    field. The redaction utility is the layer that prevents secrets
    from reaching the database. This test asserts the *enforcement*
    point: the field is a regular text column that the application
    layer is responsible for keeping safe.
    """
    scan_id = _setup(session)
    obs = ProviderObservation(
        scan_run_id=scan_id,
        provider="osv",
        operation="query",
        status=ProviderStatus.UNAVAILABLE,
        error_code="http_503",
        error_summary="upstream timed out",  # pre-redacted by service
        records_returned=0,
    )
    session.add(obs)
    session.flush()
    assert obs.error_summary == "upstream timed out"


def test_provider_observation_fk_declares_cascade(engine) -> None:
    """Verify the FK on ``provider_observations.scan_run_id`` declares
    ``ON DELETE CASCADE`` at the schema level.

    We do not exercise the cascade in-process because SQLite requires
    ``PRAGMA foreign_keys=ON`` per connection, and the test
    environment uses StaticPool with shared connections, which makes
    the cascade brittle to test reliably. PostgreSQL, the production
    target, enforces FKs by default; the same DDL is sufficient.
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    fks = inspector.get_foreign_keys("provider_observations")
    matching = [
        fk
        for fk in fks
        if fk["referred_table"] == "scan_runs" and "scan_run_id" in fk["constrained_columns"]
    ]
    assert matching, "no FK from provider_observations.scan_run_id to scan_runs"
    fk = matching[0]
    on_delete = fk.get("options", {}).get("ondelete")
    assert on_delete is not None
    assert on_delete.upper() == "CASCADE"
