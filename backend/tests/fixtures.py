"""Test fixture loader.

Centralises the resolution of test fixture paths and provides
small helpers for tests that need to read bytes or text from the
``backend/tests/fixtures`` directory.

Tests import from here directly rather than going through pytest
fixtures so the loader is usable from any module.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def fixture_path(relative: str) -> Path:
    """Return the absolute path of a fixture file."""
    candidate = (FIXTURES_DIR / relative).resolve()
    fixtures_resolved = FIXTURES_DIR.resolve()
    try:
        candidate.relative_to(fixtures_resolved)
    except ValueError as exc:
        raise ValueError(f"Fixture path {relative!r} escapes the fixtures directory.") from exc
    return candidate


def read_fixture_bytes(relative: str) -> bytes:
    return fixture_path(relative).read_bytes()


def read_fixture_text(relative: str, *, encoding: str = "utf-8") -> str:
    return fixture_path(relative).read_text(encoding=encoding)


def read_fixture_json(relative: str) -> Any:
    import json

    return json.loads(read_fixture_bytes(relative))


def list_fixtures(relative: str = "") -> list[Path]:
    root = fixture_path(relative) if relative else FIXTURES_DIR
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file())


def build_deepseek_harness_zip() -> Path:
    """Build a deterministic local ZIP fixture mirroring the
    DeepSeek-Harness symlink pattern.

    The fixture is a minimal but realistic snapshot of
    the failing production archive: an ordinary
    ``README.md`` file plus a single relative
    symbolic-link entry under
    ``.agents/notes/implemented/CLAUDE.md``. The
    fixture lives entirely in-memory and is written
    to the on-disk fixtures directory so a future
    test can reuse the same bytes for end-to-end
    intake checks.

    The function never depends on a live GitHub
    mirror. The permanent test suite uses this
    fixture; an offline developer can re-run the
    regression without network access.

    The on-disk bytes are written with a fixed
    ``date_time`` (1980-01-01 00:00:00) so the
    fixture is byte-stable across runs and the
    ``git status --porcelain`` check stays clean
    after a test run.
    """
    target = FIXTURES_DIR / "deepseek_harness_symlink.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    # The ZIP ``date_time`` is the only source of
    # non-determinism for a constant payload; pin
    # it so the on-disk bytes are byte-stable.
    fixed_date_time = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        # The repository root file is an ordinary
        # text payload. The bytes are deterministic
        # so a future test can assert the exact
        # archive contents.
        zf.writestr(
            zipfile.ZipInfo("deepseek-harness/README.md", fixed_date_time),
            b"# deepseek-harness\n",
        )
        # The failing entry is a relative symbolic
        # link whose target points at the parent
        # directory's README. ``zipfile`` records
        # the link target via the
        # ``create_system=3`` (``UNIX``) attribute
        # and the external_attr bits. The
        # constructed ZIP entry is intentionally
        # not dereferenced; the intake layer
        # inspects the metadata.
        info = zipfile.ZipInfo(
            "deepseek-harness/.agents/notes/implemented/CLAUDE.md",
            fixed_date_time,
        )
        info.create_system = 3  # UNIX
        # ``S_IFLNK = 0o120000`` shifted into the
        # upper 16 bits of ``external_attr``.
        info.external_attr = (0o120000 & 0xFFFF) << 16
        zf.writestr(info, b"../../README.md")
    return target


def list_files_in_tree(root_path: str) -> list[tuple[str, bytes]]:
    """Return ``(relative_path, bytes)`` for every file under ``root_path``.

    The ``relative_path`` is a forward-slash, normalized path
    relative to :data:`FIXTURES_DIR` and is safe to pass to the
    manifest scanner or the workflow analyzer.
    """
    root = fixture_path(root_path)
    if not root.exists():
        return []
    out: list[tuple[str, bytes]] = []
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(FIXTURES_DIR).as_posix()
        out.append((relative, file_path.read_bytes()))
    return out


def write_temp_fixture(
    tmp_path: Path,
    relative: str,
    content: bytes,
) -> Path:
    """Write a temp fixture under ``tmp_path`` and return the file path."""
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


__all__ = [
    "FIXTURES_DIR",
    "build_deepseek_harness_zip",
    "fixture_path",
    "list_files_in_tree",
    "list_fixtures",
    "read_fixture_bytes",
    "read_fixture_json",
    "read_fixture_text",
    "write_temp_fixture",
]


def iter_files(filenames: Iterable[str]) -> list[tuple[str, bytes]]:
    """Convenience wrapper for tests that want a list of (name, bytes)."""
    return [(name, read_fixture_bytes(name)) for name in filenames]
