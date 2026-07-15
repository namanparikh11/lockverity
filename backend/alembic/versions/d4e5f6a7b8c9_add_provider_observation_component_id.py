"""add per-component binding to provider observations

Revision ID: d4e5f6a7b8c9
Revises: c3f4a89b2102
Create Date: 2026-07-15 19:50:00.000000

The v0.4 first pass added ``evidence_json`` so that successful
provider payload metadata does not leak into the
``error_summary`` column. A second correctness defect remained:
``ProviderObservation`` had no link to the component it
described. The endpoint that joins per-component enrichment
rows to ``Component`` therefore selected the *latest*
observation for the (scan_run_id, provider) pair, regardless of
which component it referred to. The visible bug was that a
component with a concrete normalised version received an
"unavailable_reason" copied from a different component in the
same scan whose deps.dev lookup failed because that other
component had no version.

This migration adds a nullable ``component_id`` foreign key on
``provider_observations`` plus a covering index, and leaves
existing rows at ``NULL`` (the API treats ``NULL`` as
"scan-level observation that has no single component", e.g. an
OpenSSF Scorecard call). The application code is updated to
populate the column on per-component observations and to filter
by it on the read path.

The migration is additive: no existing row is rewritten and no
existing index is dropped.

The implementation uses Alembic batch mode because SQLite
does not support ``ALTER TABLE ... ADD CONSTRAINT``; the
batch mode executes a copy-and-move under the hood, which
is the documented portable shape for adding a foreign key
to an existing SQLite table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3f4a89b2102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``component_id`` FK + covering index using batch mode.

    The column is nullable because per-scan observations
    (OpenSSF Scorecard, intake validation) do not refer to
    a single component. The index is a composite that
    supports the API read pattern
    ``WHERE scan_run_id = ? AND provider = ? AND component_id = ?``.
    """
    with op.batch_alter_table(
        "provider_observations",
        recreate="always",
    ) as batch_op:
        batch_op.add_column(
            sa.Column("component_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_provider_observations_component_id",
            "components",
            ["component_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_index(
        "ix_provider_observations_scan_run_id_provider_component_id",
        "provider_observations",
        ["scan_run_id", "provider", "component_id"],
    )


def downgrade() -> None:
    """Drop the FK, index, and column."""
    op.drop_index(
        "ix_provider_observations_scan_run_id_provider_component_id",
        table_name="provider_observations",
    )
    with op.batch_alter_table(
        "provider_observations",
        recreate="always",
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_provider_observations_component_id",
            type_="foreignkey",
        )
        batch_op.drop_column("component_id")
