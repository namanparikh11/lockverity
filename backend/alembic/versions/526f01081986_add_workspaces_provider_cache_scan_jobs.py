"""add workspaces, provider cache, scan jobs

Revision ID: 526f01081986
Revises: 7efc41b356da
Create Date: 2026-07-11 22:50:24.134011
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "526f01081986"
down_revision: str | Sequence[str] | None = "7efc41b356da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_run_id", sa.Integer(), nullable=False),
        sa.Column("workspace_key", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.Enum("GITHUB", "UPLOADED_ARCHIVE", name="workspace_kind"), nullable=False),
        sa.Column("state", sa.Enum(
            "QUARANTINED", "VALIDATING", "READY", "FAILED", "CLEANED_UP",
            name="workspace_state",
        ), nullable=False),
        sa.Column("archive_filename", sa.String(length=512), nullable=True),
        sa.Column("archive_sha256", sa.String(length=64), nullable=True),
        sa.Column("archive_size", sa.Integer(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("uncompressed_size", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_summary", sa.String(length=2048), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleaned_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(workspace_key) >= 16", name=op.f("ck_workspaces_workspace_key_min_length")
        ),
        sa.ForeignKeyConstraint(
            ["scan_run_id"], ["scan_runs.id"], name=op.f("fk_workspaces_scan_run_id_scan_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("workspace_key", name=op.f("uq_workspaces_workspace_key")),
    )
    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.create_index("ix_workspaces_kind", ["kind"], unique=False)
        batch_op.create_index("ix_workspaces_scan_run_id", ["scan_run_id"], unique=False)
        batch_op.create_index("ix_workspaces_state", ["state"], unique=False)

    op.create_table(
        "provider_cache_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("cache_key", sa.String(length=128), nullable=False),
        sa.Column("response_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("payload_size", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("last_modified", sa.String(length=255), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_cache_entries")),
        sa.UniqueConstraint(
            "provider", "operation", "cache_key",
            name=op.f("uq_provider_cache_key"),
        ),
    )
    with op.batch_alter_table("provider_cache_entries", schema=None) as batch_op:
        batch_op.create_index(
            "ix_provider_cache_expires_at", ["expires_at"], unique=False
        )
        batch_op.create_index(
            "ix_provider_cache_provider_operation", ["provider", "operation"], unique=False
        )

    op.create_table(
        "scan_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_run_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.Enum(
            "IDLE", "QUEUED", "RUNNING", "CANCELLED", "FAILED", name="scan_job_state",
        ), nullable=False),
        sa.Column("executor_id", sa.String(length=64), nullable=False),
        sa.Column("owner_pid", sa.Integer(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_summary", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(executor_id) >= 8", name=op.f("ck_scan_jobs_scan_job_executor_id_min_length")
        ),
        sa.ForeignKeyConstraint(
            ["scan_run_id"], ["scan_runs.id"], name=op.f("fk_scan_jobs_scan_run_id_scan_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_jobs")),
    )
    with op.batch_alter_table("scan_jobs", schema=None) as batch_op:
        batch_op.create_index("ix_scan_jobs_scan_run_id", ["scan_run_id"], unique=False)
        batch_op.create_index("ix_scan_jobs_state", ["state"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("scan_jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_scan_jobs_state")
        batch_op.drop_index("ix_scan_jobs_scan_run_id")
    op.drop_table("scan_jobs")

    with op.batch_alter_table("provider_cache_entries", schema=None) as batch_op:
        batch_op.drop_index("ix_provider_cache_provider_operation")
        batch_op.drop_index("ix_provider_cache_expires_at")
    op.drop_table("provider_cache_entries")

    with op.batch_alter_table("workspaces", schema=None) as batch_op:
        batch_op.drop_index("ix_workspaces_state")
        batch_op.drop_index("ix_workspaces_scan_run_id")
        batch_op.drop_index("ix_workspaces_kind")
    op.drop_table("workspaces")
