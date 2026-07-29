"""Add workspaces.safe_archive_filename.

v2.0.6 public-release closure (cycle 7 final):

* The search predicate no longer matches against the raw
  ``Workspace.archive_filename`` value (which may carry
  parent-directory path components or trusted GitHub
  provenance). The query-time basename is now stored in a
  separate column ``safe_archive_filename`` and the search
  predicate matches against that column only.
* The display value (``archive_filename``) is preserved
  unchanged so trusted GitHub provenance
  (``github/{owner}/{name}@{sha}.tar.gz``) continues to
  surface in the API response.

The migration is additive: a new nullable column is added
and backfilled from the existing ``archive_filename`` value
via the migration-local :func:`_safe_basename` helper
below. The helper is intentionally embedded in this
revision file rather than imported from
:mod:`app.utils.paths` so the migration does not depend on
mutable application code: a future change to the
``basename_safely`` helper would not retroactively alter
the backfill semantics of this historical migration.

The embedded algorithm mirrors the snapshot of
:func:`app.utils.paths.basename_safely` that was in effect
at the time this migration was authored. It is
deterministic, dependency-light (only the Python standard
library), and produces the same output as the
application-level helper for every input the helper
accepts. The migration's tests pin the exact backfill
output for representative inputs; if a future migration
ever needs to diverge, a new migration must be added rather
than modifying this revision in place.
"""

from __future__ import annotations

import re
import unicodedata

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Migration-local sanitiser
# ---------------------------------------------------------------------------
#
# The algorithm below is a frozen copy of the basename
# extraction logic that was in
# :func:`app.utils.paths.basename_safely` at the time this
# migration was authored. It is intentionally inlined so the
# migration is self-contained: a future change to the
# application helper cannot retroactively alter the backfill
# semantics of this historical migration.
#
# The algorithm (matching the v2.0.6 cycle-7-final snapshot):
# 1. Reject ``None`` and non-string inputs (return ``None``).
# 2. Strip leading / trailing whitespace; if the result is
#    empty, return ``None``.
# 3. Replace every backslash with a forward slash.
# 4. Strip any leading ``/`` characters (UNC share prefix).
# 5. Strip a single trailing ``/`` and check for emptiness
#    (a path that is just ``/`` or ``\\`` returns ``None``).
# 6. If the path starts with a Windows drive-letter prefix
#    (``C:`` / ``C:/`` / ``C:\\``), strip the prefix; if
#    nothing remains the path was a bare drive-letter form
#    and we return ``None``. ``C:foo`` (drive-relative) keeps
#    ``foo`` as the candidate basename.
# 7. Take the last path component (after the final ``/``).
# 8. If the last component is empty / ``.`` / ``..``, return
#    ``None``.
# 9. NFC-normalise the basename.
# 10. If longer than 512 characters, truncate while
#     preserving the trailing extension (the operator-facing
#     label is still recognisable).

_DRIVE_LETTER_RE = re.compile(r"^([A-Za-z]):")
_BASENAME_MAX = 512


def _safe_basename(raw: object) -> str | None:
    """Return the migration-local safe basename for ``raw``.

    Frozen copy of the v2.0.6 cycle-7-final
    :func:`app.utils.paths.basename_safely` semantics. See
    the module docstring for the contract.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    # Normalise backslashes to forward slashes so the
    # rest of the algorithm operates on a single
    # separator.
    cleaned = cleaned.replace("\\", "/")
    # Strip UNC leading slashes (the host share component
    # is treated as a directory).
    cleaned = re.sub(r"^/+", "", cleaned)
    trimmed = cleaned.strip("/")
    if not trimmed:
        return None
    # Windows drive-letter prefix. The bare drive-letter
    # form (``C:`` / ``C:/`` / ``C:\\``) is not a valid
    # filename. The drive-relative form (``C:foo``) keeps
    # ``foo`` as the basename.
    if _DRIVE_LETTER_RE.match(trimmed) is not None:
        after_prefix = _DRIVE_LETTER_RE.sub("", trimmed, count=1)
        if not after_prefix:
            return None
        trimmed = after_prefix
    # Take the last path component.
    base = trimmed.rsplit("/", 1)[-1]
    if not base:
        return None
    if base in (".", ".."):
        return None
    base = unicodedata.normalize("NFC", base)
    if len(base) > _BASENAME_MAX:
        if "." in base:
            stem, dot, ext = base.rpartition(".")
            if dot and ext:
                keep = _BASENAME_MAX - len(dot) - len(ext) - 1
                base = stem[:keep] + "." + ext if keep > 0 else base[:_BASENAME_MAX]
            else:
                base = base[:_BASENAME_MAX]
        else:
            base = base[:_BASENAME_MAX]
    return base


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "safe_archive_filename",
            sa.String(length=512),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_workspaces_safe_archive_filename",
        "workspaces",
        ["safe_archive_filename"],
    )
    # Backfill from the existing ``archive_filename``
    # value. For pre-cycle-7 rows the existing value was
    # already sanitised (the previous ``workspace_service``
    # implementation called :func:`basename_safely`
    # unconditionally), so the safe basename equals the
    # displayed value. The backfill uses the migration-
    # local :func:`_safe_basename` helper rather than the
    # application-level helper so the backfill semantics
    # are pinned to this historical revision.
    bind = op.get_bind()
    workspace_table = sa.table(
        "workspaces",
        sa.column("id", sa.Integer),
        sa.column("archive_filename", sa.String),
        sa.column("safe_archive_filename", sa.String),
    )
    rows = bind.execute(
        sa.select(
            workspace_table.c.id,
            workspace_table.c.archive_filename,
        ).where(workspace_table.c.archive_filename.is_not(None))
    ).all()
    for row_id, archive_filename in rows:
        safe = _safe_basename(archive_filename)
        bind.execute(
            workspace_table.update()
            .where(workspace_table.c.id == row_id)
            .values(safe_archive_filename=safe)
        )


def downgrade() -> None:
    op.drop_index("ix_workspaces_safe_archive_filename", table_name="workspaces")
    op.drop_column("workspaces", "safe_archive_filename")
