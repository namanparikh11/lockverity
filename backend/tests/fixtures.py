"""Test fixture loader.

Centralises the resolution of test fixture paths and provides
small helpers for tests that need to read bytes or text from the
``backend/tests/fixtures`` directory.

Tests import from here directly rather than going through pytest
fixtures so the loader is usable from any module.
"""

from __future__ import annotations

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
