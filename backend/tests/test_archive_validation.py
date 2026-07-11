"""Tests for :mod:`app.utils.archive_validation`."""

from __future__ import annotations

import pytest
from app.utils.archive_validation import (
    ArchiveEntry,
    ArchiveLimits,
    ArchiveValidationCollector,
    ArchiveValidationError,
    validate_entries,
)


def _limits(**overrides) -> ArchiveLimits:
    base = {
        "max_compressed_bytes": 10_000,
        "max_uncompressed_bytes": 10_000,
        "max_file_count": 5,
        "max_file_bytes": 2_000,
        "max_depth": 3,
        "suspicious_ratio": 100,
    }
    base.update(overrides)
    return ArchiveLimits(**base)


def test_accepts_normal_archive() -> None:
    entries = [
        ArchiveEntry(name="a.txt", size=10, compressed_size=5),
        ArchiveEntry(name="b/c.txt", size=20, compressed_size=10),
    ]
    collector = validate_entries(entries, _limits())
    assert collector.errors == ()
    assert collector.file_count == 2
    assert collector.uncompressed_total == 30


def test_rejects_traversal() -> None:
    entries = [ArchiveEntry(name="../../etc/passwd", size=10, compressed_size=5)]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits())
    assert exc.value.code == "archive_unsafe_path"


def test_rejects_absolute_path() -> None:
    entries = [ArchiveEntry(name="/etc/passwd", size=10, compressed_size=5)]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits())
    assert exc.value.code == "archive_unsafe_path"


def test_rejects_drive_letter() -> None:
    entries = [ArchiveEntry(name="C:\\evil", size=10, compressed_size=5)]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits())
    assert exc.value.code == "archive_unsafe_path"


def test_rejects_unc_path() -> None:
    entries = [ArchiveEntry(name="\\\\server\\share", size=10, compressed_size=5)]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits())
    assert exc.value.code == "archive_unsafe_path"


def test_rejects_symlink_entry() -> None:
    entries = [ArchiveEntry(name="link", size=0, compressed_size=0, is_symlink=True)]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits())
    assert exc.value.code == "archive_symlink_forbidden"


def test_rejects_hardlink_entry() -> None:
    entries = [ArchiveEntry(name="dup", size=0, compressed_size=0, is_hardlink=True)]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits())
    assert exc.value.code == "archive_hardlink_forbidden"


def test_rejects_duplicate_normalized_entries() -> None:
    entries = [
        ArchiveEntry(name="a/b.txt", size=10, compressed_size=5),
        ArchiveEntry(name="a/./b.txt", size=10, compressed_size=5),
    ]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits())
    assert exc.value.code == "archive_duplicate_entry"


def test_rejects_excessive_depth() -> None:
    entries = [ArchiveEntry(name="a/b/c/d.txt", size=10, compressed_size=5)]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits(max_depth=2))
    assert exc.value.code == "archive_depth_exceeded"


def test_rejects_oversized_entry() -> None:
    entries = [ArchiveEntry(name="big.bin", size=10_000, compressed_size=5_000)]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits(max_file_bytes=1_000))
    assert exc.value.code == "archive_entry_too_large"


def test_rejects_too_many_files() -> None:
    entries = [ArchiveEntry(name=f"f{i}.txt", size=10, compressed_size=5) for i in range(6)]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits())
    assert exc.value.code == "archive_too_many_files"


def test_rejects_excessive_uncompressed_total() -> None:
    # Per-entry size must stay under ``max_file_bytes`` so the
    # cumulative check is the one that fires.
    entries = [
        ArchiveEntry(name="a.txt", size=1_500, compressed_size=500),
        ArchiveEntry(name="b.txt", size=1_500, compressed_size=500),
    ]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits(max_file_bytes=2_000, max_uncompressed_bytes=2_500))
    assert exc.value.code == "archive_uncompressed_too_large"


def test_rejects_excessive_compressed_total() -> None:
    entries = [
        ArchiveEntry(name="a.txt", size=5, compressed_size=6_000),
        ArchiveEntry(name="b.txt", size=5, compressed_size=6_000),
    ]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits())
    assert exc.value.code == "archive_compressed_too_large"


def test_rejects_zip_bomb_ratio() -> None:
    entries = [
        ArchiveEntry(name="a.txt", size=1_500, compressed_size=10),
    ]
    with pytest.raises(ArchiveValidationError) as exc:
        validate_entries(entries, _limits(suspicious_ratio=100, max_file_bytes=2_000))
    assert exc.value.code == "archive_suspicious_compression"


def test_zero_compression_does_not_trigger_bomb_check() -> None:
    entries = [ArchiveEntry(name="a.txt", size=0, compressed_size=0)]
    validate_entries(entries, _limits())


def test_collector_records_multiple_errors() -> None:
    collector = ArchiveValidationCollector(_limits(max_file_count=1))
    collector.check_entry(ArchiveEntry(name="a.txt", size=1, compressed_size=1))
    collector.check_entry(ArchiveEntry(name="b.txt", size=1, compressed_size=1))
    codes = [e.code for e in collector.errors]
    assert "archive_too_many_files" in codes


def test_collector_ok_raises_with_first_error() -> None:
    collector = ArchiveValidationCollector(_limits())
    # An unsafe entry is what we're after.
    collector.check_entry(ArchiveEntry(name="../bad", size=1, compressed_size=1))
    with pytest.raises(ArchiveValidationError):
        collector.ok()


def test_collector_ok_passes_when_clean() -> None:
    collector = ArchiveValidationCollector(_limits())
    collector.check_entry(ArchiveEntry(name="a.txt", size=1, compressed_size=1))
    collector.ok()  # should not raise
