"""Pytest entry for the manual migration cycle.

Wraps the :mod:`tests.manual_migration_cycle` script so it can be run
via the standard ``pytest`` command in CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = BACKEND_ROOT / "tests" / "manual_migration_cycle.py"


@pytest.mark.integration
def test_alembic_upgrade_downgrade_reupgrade() -> None:
    """Upgrade, downgrade, and re-upgrade against a fresh SQLite file."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["LOCKVERITY_DATABASE_URL"] = "sqlite:///./lockverity.sqlite"
    result = subprocess.run(
        [sys.executable, "-m", "tests.manual_migration_cycle"],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"Migration cycle failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
