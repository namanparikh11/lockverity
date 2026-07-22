"""add repository original_filename (v2.0.5)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-22 15:00:00.000000

The v2.0.4 repository list surfaces an opaque canonical upload
identifier (e.g. ``upload/2ed7b06ed7d3d967``) as the primary row
label. The operator cannot tell which uploaded ZIP the row
refers to without opening the repository detail page. The v2.0.5
field-test repro required operators to navigate two clicks to
identify each row when several uploaded archives were present.

This migration adds a nullable ``original_filename`` column on
``repositories`` and an index that supports the new
``display_name`` / filename search path. The column is nullable
because v0.x-v2.0.4 historical rows were created before this
column existed; the upload-intake service populates it for new
uploads with the basename of the client-supplied filename (so
an absolute path never reaches the database). No historical row
is rewritten; the migration is purely additive.

The implementation uses Alembic batch mode because SQLite does
not support ``ALTER TABLE ... ADD CONSTRAINT`` for adding a
non-null column to an existing table; the batch mode executes
a copy-and-move under the hood, which is the documented portable
shape for SQLite schema changes.

The migration is reversible: ``downgrade()`` drops both the
index and the column, restoring the v2.0.4 schema.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``original_filename`` (nullable) + covering index.

    The column is nullable because historical rows are left
    untouched. The intake service populates it for new
    uploads. The index supports the new search by filename
    query path.
    """
    with op.batch_alter_table(
        "repositories",
        recreate="always",
    ) as batch_op:
        batch_op.add_column(
            sa.Column("original_filename", sa.String(length=512), nullable=True)
        )
    op.create_index(
        "ix_repositories_original_filename",
        "repositories",
        ["original_filename"],
    )


def downgrade() -> None:
    """Drop the index and the column."""
    op.drop_index(
        "ix_repositories_original_filename",
        table_name="repositories",
    )
    with op.batch_alter_table(
        "repositories",
        recreate="always",
    ) as batch_op:
        batch_op.drop_column("original_filename")
