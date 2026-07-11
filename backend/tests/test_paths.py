"""Tests for :mod:`app.utils.paths`."""

from __future__ import annotations

import pytest
from app.utils.paths import PathNormalizationError, join_relative, normalize_relative_path


def test_basic_normalization() -> None:
    assert normalize_relative_path("src/lib/index.js") == "src/lib/index.js"


def test_collapses_separators() -> None:
    assert normalize_relative_path("src//lib///index.js") == "src/lib/index.js"


def test_rejects_absolute_unix() -> None:
    with pytest.raises(PathNormalizationError):
        normalize_relative_path("/etc/passwd")


def test_rejects_drive_letter() -> None:
    with pytest.raises(PathNormalizationError):
        normalize_relative_path("C:\\evil")
    with pytest.raises(PathNormalizationError):
        normalize_relative_path("C:evil")


def test_rejects_drive_letter_with_forward_slash() -> None:
    with pytest.raises(PathNormalizationError):
        normalize_relative_path("D:/malicious")


def test_rejects_unc_path() -> None:
    with pytest.raises(PathNormalizationError):
        normalize_relative_path("\\\\server\\share")
    with pytest.raises(PathNormalizationError):
        normalize_relative_path("//server/share")


def test_rejects_parent_traversal() -> None:
    with pytest.raises(PathNormalizationError):
        normalize_relative_path("../etc/passwd")
    with pytest.raises(PathNormalizationError):
        normalize_relative_path("src/../../etc/passwd")


def test_rejects_null_bytes() -> None:
    with pytest.raises(PathNormalizationError):
        normalize_relative_path("src/\x00evil")


def test_rejects_empty() -> None:
    with pytest.raises(PathNormalizationError):
        normalize_relative_path("")
    with pytest.raises(PathNormalizationError):
        normalize_relative_path("///")


def test_normalizes_unicode() -> None:
    # No-op for ASCII, but the call should not raise.
    assert normalize_relative_path("docs/notice.txt") == "docs/notice.txt"


def test_join_relative_combines_fragments() -> None:
    assert join_relative("src", "lib", "index.js") == "src/lib/index.js"


def test_join_relative_rejects_traversal() -> None:
    with pytest.raises(PathNormalizationError):
        join_relative("src", "..", "etc")
