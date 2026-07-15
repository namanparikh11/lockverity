"""add structured provider observation evidence

Revision ID: c3f4a89b2102
Revises: 526f01081986
Create Date: 2026-07-15 14:40:00.000000

The v0.4 provider service records successful provider payload
metadata (licence observations, dependency counts, package
identity, fetched_at) for every successful provider call. The
v0.4 first pass stored this data inside the bounded
``error_summary`` column with a ``trace=`` prefix; that was a
workaround that mixed successful evidence with redacted error
strings. This migration adds a dedicated bounded JSON column
``evidence_json`` on ``provider_observations`` so the success
and error paths use distinct, well-named persistence fields.

The new column is bounded at 8 KiB (the same cap the SQLite
TEXT size limit lets us enforce cheaply) and is nullable. No
existing row is touched; the column starts empty for every
observation and is populated only for successful provider
calls from this migration forward.

Security: ``evidence_json`` carries the redacted JSON
envelope. Secrets are stripped by the redaction utility
before the value is written.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c3f4a89b2102"
down_revision: str | Sequence[str] | None = "526f01081986"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 8 KiB cap on the evidence JSON payload. Bounded so a
# misconfigured upstream cannot bloat the database with a
# giant response. The application-side validator rejects
# payloads above this limit and falls back to a trimmed
# representation.
EVIDENCE_JSON_MAX_BYTES = 8 * 1024


def upgrade() -> None:
    op.add_column(
        "provider_observations",
        sa.Column(
            "evidence_json",
            sa.Text(length=EVIDENCE_JSON_MAX_BYTES),
            nullable=True,
        ),
    )
    # No data migration is needed: existing rows have null
    # evidence. The endpoint reconstructs the licence / dep
    # count from the trace prefix on legacy rows, then writes
    # the structured column on the next refresh.


def downgrade() -> None:
    op.drop_column("provider_observations", "evidence_json")
