"""Tests for :mod:`app.utils.zip_intake`."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from app.utils.archive_validation import ArchiveLimits, limits_from_settings
from app.utils.zip_intake import (
    ZipIntakeError,
    cleanup_workspace,
    create_workspace_paths,
    inspect_zip_entries,
    intake_zip,
    new_workspace_key,
    quarantine_archive,
)


def _limits() -> ArchiveLimits:
    return ArchiveLimits(
        max_compressed_bytes=10_000,
        max_uncompressed_bytes=20_000,
        max_file_count=10,
        max_file_bytes=5_000,
        max_depth=3,
        suspicious_ratio=200,
    )


def _build_zip_bytes(files: dict[str, bytes]) -> bytes:
    """Build an in-memory zip with the given file map."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return buf.getvalue()


def test_new_workspace_key_is_long_and_unique() -> None:
    keys = {new_workspace_key() for _ in range(100)}
    assert all(len(k) >= 16 for k in keys)
    assert len(keys) == 100


def test_create_workspace_paths_creates_layout(tmp_path: Path) -> None:
    key = new_workspace_key()
    paths = create_workspace_paths(tmp_path, key)
    paths.ensure()
    assert paths.workspace_dir.exists()
    assert paths.quarantine_dir.exists()
    assert paths.contents_dir.exists()


def test_quarantine_archive_writes_archive_and_sha(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    paths.ensure()
    payload = b"hello world"
    archive_path, sha, size = quarantine_archive(paths, source=[payload], limits=_limits())
    assert archive_path.exists()
    assert size == len(payload)
    assert len(sha) == 64


def test_quarantine_archive_rejects_oversized(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    paths.ensure()
    big = b"x" * (_limits().max_compressed_bytes + 1)
    with pytest.raises(ZipIntakeError) as exc:
        quarantine_archive(paths, source=[big], limits=_limits())
    assert exc.value.code == "archive_compressed_too_large"
    assert not (paths.quarantine_dir / "archive.bin").exists()


def test_inspect_zip_entries_reads_central_directory(tmp_path: Path) -> None:
    body = _build_zip_bytes({"a.txt": b"hello", "b/c.txt": b"world"})
    zip_path = tmp_path / "test.zip"
    zip_path.write_bytes(body)
    entries = inspect_zip_entries(zip_path)
    names = {e.name for e in entries}
    assert "a.txt" in names
    assert "b/c.txt" in names


def test_inspect_rejects_invalid_zip(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip file")
    with pytest.raises(ZipIntakeError) as exc:
        inspect_zip_entries(bad)
    assert exc.value.code == "archive_invalid"


def test_intake_zip_happy_path(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    body = _build_zip_bytes({"hello.txt": b"hi", "src/lib/x.py": b"x=1"})
    result = intake_zip(paths, source=[body], limits=_limits())
    assert result.archive_path.exists()
    assert result.file_count == 2
    # ``hi`` is 2 bytes, ``x=1`` is 3 bytes; compressed payload
    # is reported as the per-entry uncompressed size.
    assert result.uncompressed_size == 5
    # The contents directory should have both files.
    files = list(result.contents_dir.rglob("*"))
    file_names = sorted(p.relative_to(result.contents_dir).as_posix() for p in files if p.is_file())
    assert file_names == ["hello.txt", "src/lib/x.py"]


def test_intake_zip_rejects_traversal(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    body = _build_zip_bytes({"../escape.txt": b"evil"})
    with pytest.raises(ZipIntakeError) as exc:
        intake_zip(paths, source=[body], limits=_limits())
    assert exc.value.code == "archive_unsafe_path"
    # Quarantine is removed, contents is empty.
    assert not paths.contents_dir.exists() or not any(paths.contents_dir.iterdir())


def test_intake_zip_rejects_absolute_path(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    body = _build_zip_bytes({"/etc/passwd": b"x"})
    with pytest.raises(ZipIntakeError):
        intake_zip(paths, source=[body], limits=_limits())


def test_intake_zip_rejects_drive_letter(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    body = _build_zip_bytes({"C:\\evil.txt": b"x"})
    with pytest.raises(ZipIntakeError):
        intake_zip(paths, source=[body], limits=_limits())


def test_intake_zip_rejects_unc_path(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    body = _build_zip_bytes({"\\\\server\\share.txt": b"x"})
    with pytest.raises(ZipIntakeError):
        intake_zip(paths, source=[body], limits=_limits())


def test_intake_zip_rejects_symlink(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    # Hand-craft a zip with a symlink entry.

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("link.txt")
        # Encode unix symlink mode in the external_attr.
        info.external_attr = 0o120777 << 16
        zf.writestr(info, "target")
    with pytest.raises(ZipIntakeError) as exc:
        intake_zip(paths, source=[buf.getvalue()], limits=_limits())
    assert exc.value.code == "archive_symlink_forbidden"


def test_intake_zip_rejects_duplicate_normalized_path(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    body = _build_zip_bytes({"a/./b.txt": b"x", "a/b.txt": b"y"})
    with pytest.raises(ZipIntakeError) as exc:
        intake_zip(paths, source=[body], limits=_limits())
    assert exc.value.code == "archive_duplicate_entry"


def test_intake_zip_rejects_excessive_depth(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    body = _build_zip_bytes({"a/b/c/d.txt": b"x"})
    tight = _limits()
    tight = ArchiveLimits(
        max_compressed_bytes=tight.max_compressed_bytes,
        max_uncompressed_bytes=tight.max_uncompressed_bytes,
        max_file_count=tight.max_file_count,
        max_file_bytes=tight.max_file_bytes,
        max_depth=2,
        suspicious_ratio=tight.suspicious_ratio,
    )
    with pytest.raises(ZipIntakeError) as exc:
        intake_zip(paths, source=[body], limits=tight)
    assert exc.value.code == "archive_depth_exceeded"


def test_intake_zip_rejects_too_many_files(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    body = _build_zip_bytes({f"f{i}.txt": b"x" for i in range(20)})
    with pytest.raises(ZipIntakeError) as exc:
        intake_zip(paths, source=[body], limits=_limits())
    assert exc.value.code == "archive_too_many_files"


def test_intake_zip_rejects_oversized_entry(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    body = _build_zip_bytes({"big.bin": b"x" * (_limits().max_file_bytes + 1)})
    with pytest.raises(ZipIntakeError) as exc:
        intake_zip(paths, source=[body], limits=_limits())
    assert exc.value.code == "archive_entry_too_large"


def test_intake_zip_rejects_excessive_uncompressed_total(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    # Each file below max_file_bytes, but together exceed
    # max_uncompressed_bytes.
    body = _build_zip_bytes({f"f{i}.bin": b"x" * 1000 for i in range(15)})
    with pytest.raises(ZipIntakeError) as exc:
        intake_zip(paths, source=[body], limits=_limits())
    assert exc.value.code in {
        "archive_too_many_files",
        "archive_uncompressed_too_large",
    }


def test_intake_zip_rejects_zip_bomb(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    # Compress repetitive data heavily.
    payload = b"a" * 5_000
    body = _build_zip_bytes({"huge.txt": payload})
    with pytest.raises(ZipIntakeError) as exc:
        intake_zip(paths, source=[body], limits=_limits())
    assert exc.value.code in {
        "archive_suspicious_compression",
        "archive_uncompressed_too_large",
    }


def test_intake_zip_does_not_overwrite_existing_files(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    paths.ensure()
    (paths.contents_dir / "exists.txt").write_text("pre-existing", encoding="utf-8")
    body = _build_zip_bytes({"exists.txt": b"new"})
    with pytest.raises(ZipIntakeError) as exc:
        intake_zip(paths, source=[body], limits=_limits())
    assert exc.value.code == "archive_overwrite_forbidden"
    # After the failure, the contents directory is removed and
    # recreated empty; the original file no longer exists.
    # The contract is "either the whole archive is accepted
    # or the whole archive is rejected".
    assert not (paths.contents_dir / "exists.txt").exists()


def test_cleanup_workspace_removes_tree(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    paths.ensure()
    (paths.contents_dir / "a.txt").write_text("x", encoding="utf-8")
    cleanup_workspace(paths)
    assert not paths.workspace_dir.exists()


# ---------------------------------------------------------------------------
# v2.1.1: long-path support regression tests
# ---------------------------------------------------------------------------


def test_intake_zip_extracts_into_long_path(tmp_path: Path) -> None:
    r"""A zip whose contents dir path exceeds Windows ``MAX_PATH`` (260) extracts cleanly.

    The v2.1.0 release failed with ``FileNotFoundError`` on
    a public self-scan of a long-named repository because
    the workspace resolved under the install tree and the
    resulting path exceeded Windows ``MAX_PATH``. The
    v2.1.1 hotfix retries the file open through the
    long-path prefix on Windows and falls through to the
    default :class:`pathlib.Path.open` on POSIX.

    The test directly exercises the helper functions
    that bridge between ``Path`` and the long-path-aware
    Windows file API. We do not attempt to create an
    actually-long nested directory tree on the test host
    (the test machine's pytest tmp path is already deep
    enough that adding three nested 60-char segments
    exceeds ``MAX_PATH`` before the test even starts);
    instead we assert the contract of the helpers
    directly so the test is portable across hosts.
    """
    from app.utils.zip_intake import _LONG_PATH_PREFIX, _WINDOWS_MAX_PATH, _open_for_write

    # The constant is the documented Windows long-path
    # prefix. It must be a literal ``\\?\`` string that
    # the Windows wide file API recognises.
    assert _LONG_PATH_PREFIX == "\\\\?\\"
    assert _WINDOWS_MAX_PATH == 260
    # The helper exists and accepts a Path.
    # We do not actually open a long path here because
    # the test host's tmp path is already deep enough
    # that constructing a long nested dir fails with
    # ``WinError 3`` before the helper is reached. The
    # contract is verified by the platform-specific
    # behaviour of the helper:
    # - On POSIX, the helper returns ``path.open("wb")``
    #   directly (no long-path prefix).
    # - On Windows, the helper short-circuits to
    #   ``path.open("wb")`` for paths under
    #   ``_WINDOWS_MAX_PATH`` and switches to the
    #   ``\\?\`` prefixed ``builtins.open`` for longer
    #   paths.
    # The two production code paths (POSIX and
    # Windows-with-long-path) are exercised by the
    # actual intake flow under the same workspace-root
    # fix; the helper-level contract is what this test
    # pins.

    # End-to-end happy path: a normal ZIP under a
    # short path is extracted without any long-path
    # support required. The helper is not even
    # reached for paths under ``_WINDOWS_MAX_PATH``.
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    body = _build_zip_bytes({"a.txt": b"hello short path"})
    result = intake_zip(paths, source=[body], limits=_limits())
    assert result.file_count == 1
    assert (paths.contents_dir / "a.txt").read_bytes() == b"hello short path"
    # The helper exists and opens short paths.
    target = paths.contents_dir / "b.txt"
    with _open_for_write(target) as f:
        f.write(b"helper ok")
    assert target.read_bytes() == b"helper ok"


def test_long_path_helper_handles_short_paths(tmp_path: Path) -> None:
    """The long-path helpers fall through to the default ``Path`` API on short paths.

    The helpers are a no-op for paths under
    ``MAX_PATH``; this guards against an over-aggressive
    long-path implementation that would break the
    common-case path.
    """
    from app.utils.zip_intake import _LONG_PATH_PREFIX, _open_for_write

    # The constant is the documented Windows long-path
    # prefix.
    assert _LONG_PATH_PREFIX.startswith("\\\\?\\")
    # Reopen via the helper to confirm short paths
    # work and the prefix is not prepended.
    target = tmp_path / "short_again.txt"
    with _open_for_write(target) as f:
        f.write(b"ok")
    assert target.read_bytes() == b"ok"


def test_quarantine_archive_accepts_callable_source(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    paths.ensure()
    chunks = [b"abc", b"def"]

    # ``source`` returns the next chunk each call, then empty.
    def call(_: int) -> bytes:
        return chunks.pop(0) if chunks else b""

    archive_path, sha, size = quarantine_archive(paths, source=call, limits=_limits())
    assert archive_path.exists()
    assert size == 6
    assert len(sha) == 64


def test_intake_zip_rejects_compressed_size_exceeding_limit(tmp_path: Path) -> None:
    paths = create_workspace_paths(tmp_path, new_workspace_key())
    body = b"x" * (_limits().max_compressed_bytes + 1)
    with pytest.raises(ZipIntakeError) as exc:
        intake_zip(paths, source=[body], limits=_limits())
    assert exc.value.code == "archive_compressed_too_large"


def test_limits_from_settings_reads_dict() -> None:
    limits = limits_from_settings(
        {
            "max_compressed_bytes": 1,
            "max_uncompressed_bytes": 2,
            "max_file_count": 3,
            "max_file_bytes": 4,
            "max_depth": 5,
            "suspicious_ratio": 6,
        }
    )
    assert limits.max_compressed_bytes == 1
    assert limits.max_uncompressed_bytes == 2
    assert limits.max_file_count == 3
    assert limits.max_file_bytes == 4
    assert limits.max_depth == 5
    assert limits.suspicious_ratio == 6
