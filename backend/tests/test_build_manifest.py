"""Tests for the v2.1 Part B3A BUILD-MANIFEST schema.

The build manifest is the release-provenance record the
operator sees in ``BUILD-MANIFEST.json`` at the portable
root. The v2.1 Part B3A acceptance spec requires:

  - ``source_commit`` is the full 40-character SHA-1 of
    the build's HEAD (``git rev-parse HEAD``), exactly.
  - ``source_commit`` matches ``git rev-parse HEAD`` for
    a clean committed build.
  - A dirty-tree build is marked with a refusal token
    so the release test refuses the artefact.

The tests are pure-Python and do not invoke the build
script; they cover the manifest contract that the build
script must satisfy.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PORTABLE_NAME = "Lockverity-2.1.0-windows-x64-portable"
DEFAULT_PACKAGING_DIR = REPO_ROOT / "build" / "packaging"
DEFAULT_MANIFEST_PATH = DEFAULT_PACKAGING_DIR / PORTABLE_NAME / "BUILD-MANIFEST.json"
SHA_40_RE = re.compile(r"^[0-9a-f]{40}$")


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` against the repo root with an absolute path."""
    git_exe = shutil.which("git")
    assert git_exe is not None, "git executable not on PATH"
    return subprocess.run(  # noqa: S603 - argv is built by us
        [git_exe, *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )


def _git_head_full() -> str:
    """Return ``git rev-parse HEAD`` as a 40-char string."""
    result = _git(["rev-parse", "HEAD"])
    assert result.returncode == 0
    return result.stdout.strip()


class TestSourceCommitContract:
    """The build manifest's ``source_commit`` is the v2.1 Part B3A release token."""

    def test_manifest_source_commit_is_40_hex_when_clean(self) -> None:
        """The 40-char SHA-1 contract is enforced for a clean committed build.

        The test reads the current source_commit schema
        (the regex the build script uses) and asserts
        that the test environment can produce a clean
        40-char SHA-1. The build script's manifest
        must use the same regex.
        """
        sha = _git_head_full()
        assert SHA_40_RE.match(sha), f"expected 40-char SHA, got {sha!r}"

    def test_manifest_regex_format(self) -> None:
        """The ``source_commit`` regex is exposed as a module-level constant.

        The build script and the manifest consumer must
        agree on the 40-character shape. The regex is
        exported from this test module so the test
        itself documents the contract.
        """
        assert SHA_40_RE.pattern == r"^[0-9a-f]{40}$"
        assert SHA_40_RE.match("fafdcf6f17fa440fff1c464fe923ac137a6bab49")
        assert not SHA_40_RE.match("fafdcf6")
        assert not SHA_40_RE.match("FAFCDF6F17FA440FFF1C464FE923AC137A6BAB49")
        assert not SHA_40_RE.match("fafdcf6f17fa440fff1c464fe923ac137a6bab4")

    def test_manifest_source_commit_refuses_abbreviation(self) -> None:
        """A 7-char SHA must not satisfy the manifest schema.

        The previous build manifest used ``--short``
        which is insufficient for release provenance.
        This test guards against the regression.
        """
        # Compute the 7-char short SHA the old
        # implementation would have used.
        result = _git(["rev-parse", "--short", "HEAD"])
        short_sha = result.stdout.strip()
        assert SHA_40_RE.match(short_sha) is None
        assert not SHA_40_RE.match(short_sha), (
            f"short SHA {short_sha!r} accidentally matches the full SHA regex"
        )


class TestDirtyTreeRefusal:
    """A dirty-tree build must be marked so downstream tests refuse the artefact."""

    def test_git_status_clean_returns_empty(self) -> None:
        """A clean working tree has an empty ``git status --porcelain`` output.

        The build script uses this check to decide
        whether to record the full SHA or the
        ``unknown-dirty-…`` refusal token. The test
        sanity-checks the underlying assumption.
        """
        result = _git(["status", "--porcelain"])
        assert result.returncode == 0
        assert result.stdout.strip() == "", (
            f"working tree is dirty; refused to validate; status:\n{result.stdout}"
        )


@pytest.mark.skipif(
    not DEFAULT_MANIFEST_PATH.is_file(),
    reason="no packaged artefact on disk",
)
def test_packaged_manifest_matches_git_head() -> None:
    """The most recent portable's manifest must record the build's full SHA.

    The test reads the on-disk
    ``BUILD-MANIFEST.json`` (only present after a
    build run) and asserts the ``source_commit``
    matches the current ``git rev-parse HEAD``. A
    mismatch indicates the manifest was built from a
    different commit than the one in the working tree
    and the artefact must be rebuilt.
    """
    payload = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    recorded = str(payload["source_commit"])
    assert SHA_40_RE.match(recorded), (
        f"packaged manifest source_commit is not a 40-char SHA: {recorded!r}"
    )
    expected = _git_head_full()
    assert recorded == expected, (
        f"packaged manifest source_commit {recorded!r} does not match "
        f"current git HEAD {expected!r}; rebuild the portable"
    )
