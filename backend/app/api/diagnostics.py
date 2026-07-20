"""v1.9 — Operational diagnostics endpoint.

The route is read-only. It composes a bounded summary
from persisted state plus the runtime database-
reachability probe already used by ``/api/v1/health``.

No external provider call is triggered. No secrets,
tokens, environment values, connection strings, or
local filesystem paths are exposed. No raw stack
traces are included in the response. The route is
mounted under ``/api/v1`` by ``app.api``.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import text

from app.api.deps import DBSession
from app.schemas.diagnostics import DiagnosticsSummaryResponse
from app.services import diagnostics_service

router = APIRouter(tags=["diagnostics"])


def _probe_database(session) -> str:
    """Run the bounded ``SELECT 1`` probe and return one of:

    - ``available``   — the probe succeeded;
    - ``unavailable`` — the probe raised a controlled
      error;
    - ``unknown``     — the probe result could not be
      interpreted.
    """
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        return "unavailable"
    return "available"


@router.get(
    "/diagnostics/summary",
    response_model=DiagnosticsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Read-only operational-diagnostics summary.",
    description=(
        "Returns the bounded operational-diagnostics "
        "summary: application reachability, executor "
        "state, per-provider persisted observations, "
        "bounded recent partial / failed / cancelled "
        "scans, and aggregated persisted stage-state "
        "counts. The endpoint never triggers an external "
        "provider request and never exposes secrets, "
        "tokens, environment values, connection "
        "strings, or local filesystem paths."
    ),
)
def diagnostics_summary(session: DBSession) -> DiagnosticsSummaryResponse:
    database_status = _probe_database(session)
    return diagnostics_service.build_summary(session, database_status=database_status)


__all__ = ["diagnostics_summary", "router"]
