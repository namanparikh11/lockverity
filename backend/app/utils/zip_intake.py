"""Safe ZIP intake and extraction.

The intake pipeline is:

1. Stream the request body to a quarantine file under the
   workspace's quarantine directory, computing the SHA-256 on the
   fly. If the stream exceeds the configured compressed-byte
   cap, the partial quarantine file is deleted and an
   :class:`ArchiveValidationError` is raised.
2. Inspect the central directory with the standard library
   ``zipfile`` module. Build a list of :class:`ArchiveEntry`
   records. The inspection is bounded: we never read the file
   body, only the metadata.
3. Feed the records to :func:`app.utils.archive_validation
   .validate_entries`. If any entry fails, delete the
   quarantine and return the first error.
4. Open the archive and extract every validated entry into the
   workspace's ``contents`` directory. Re-validate the
   destination path on each iteration. Refuse to overwrite an
   existing file.

The implementation deliberately uses only the standard library;
no extra dependencies are introduced.

A :class:`ZipIntakeError` is raised for any failure that
prevents the archive from being accepted. The on-disk state is
always cleaned up on failure.
"""

from __future__ import annotations

import io
import os
import secrets
import shutil
import sys
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from app.utils.archive_validation import (
    ArchiveEntry,
    ArchiveLimits,
    ArchiveValidationCollector,
    ArchiveValidationError,
    SkippedSymlink,
    validate_entries,
)
from app.utils.hashing import DEFAULT_CHUNK_SIZE
from app.utils.paths import (
    PathNormalizationError,
    normalize_relative_path,
)

# ZipInfo constants that we treat as indicating a symlink or
# hardlink on POSIX systems. Windows-created zips do not encode
# symlinks in the same way; this is the only portable signal.
_S_IFLNK = 0o120000
_S_IFMT = 0o170000

# Windows ``MAX_PATH`` (260) is the legacy ceiling for the
# Win32 ANSI file API. The wide (UTF-16) API accepts paths
# longer than 260 characters when the caller opts in with
# the Windows long-path prefix (a literal ``\\?\`` at the
# start of the path). A long-named repository plus a deep
# workspace tree (e.g. ``<home>\\var\\workspace\\
# workspaces\\<key>\\contents\\<repo>-<sha>\\<deeper>\\<file>``)
# can exceed 260 characters; the ``Path.open("wb")`` call
# on such a path raises ``FileNotFoundError`` on Windows
# even when the parent directory exists and is writable.
# The v2.1.1 hotfix detects the over-limit path and writes
# through the long-path prefix so the extraction is
# invariant of the operator's home directory depth. The
# prefix is a no-op on POSIX.
_LONG_PATH_PREFIX = "\\\\?\\"
_WINDOWS_MAX_PATH = 260


def _open_for_write(path: Path):
    r"""Return a writable file handle for ``path``, supporting long Windows paths.

    On Windows the ``Path.open("wb")`` call uses the Win32
    ANSI file API which is bounded by ``MAX_PATH`` (260).
    When the resolved path is longer than that, the call
    fails with ``FileNotFoundError`` even when the parent
    directory exists. The Windows wide file API accepts
    paths longer than 260 characters when the caller uses
    the Windows long-path prefix (a literal backslash
    backslash question mark backslash at the start of the
    path); the same approach works in Python by passing the
    prefixed string to :func:`builtins.open`. The prefix is
    rejected on POSIX so this helper falls through to the
    default ``Path.open`` on every non-Windows host.
    """
    if sys.platform != "win32":
        return path.open("wb")
    text = str(path)
    if len(text) < _WINDOWS_MAX_PATH:
        return path.open("wb")
    return open(_LONG_PATH_PREFIX + text, "wb")


def _mkdir_parents(path: Path) -> None:
    """Create the parent directory of ``path`` (and all missing ancestors).

    On Windows the ``Path.mkdir(parents=True, exist_ok=True)``
    call fails for the same ``MAX_PATH`` reason as the
    ``Path.open`` call above. This helper retries the
    long-path-prefixed form on the same condition.
    """
    parent = path.parent
    if parent.exists():
        return
    if sys.platform != "win32":
        parent.mkdir(parents=True, exist_ok=True)
        return
    text = str(parent)
    if len(text) < _WINDOWS_MAX_PATH:
        parent.mkdir(parents=True, exist_ok=True)
        return
    # The long-path prefix is documented for ``CreateDirectoryW``
    # as well. We bypass the strict-prefix check by passing the
    # prefixed string through ``os.makedirs``; the function
    # supports arbitrary paths when the prefix is supplied.
    os.makedirs(_LONG_PATH_PREFIX + text, exist_ok=True)


class ZipIntakeError(Exception):
    """Raised when a ZIP archive cannot be safely ingested."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.code}] {self.message}"


@dataclass(frozen=True, slots=True)
class ZipIntakeResult:
    """The result of a successful ZIP intake."""

    archive_path: Path
    archive_sha256: str
    archive_size: int
    file_count: int
    uncompressed_size: int
    contents_dir: Path
    # The list of symbolic links the validator
    # intentionally skipped for safety. The list is
    # empty for archives that contain no symbolic
    # links. The scan evidence layer uses the list
    # to mark the analysis ``partial`` when the
    # omitted content materially affects coverage.
    skipped_symlinks: tuple[SkippedSymlink, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """The on-disk layout for one workspace."""

    workspace_dir: Path
    quarantine_dir: Path
    contents_dir: Path

    def ensure(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.contents_dir.mkdir(parents=True, exist_ok=True)


def create_workspace_paths(root: Path, workspace_key: str) -> WorkspacePaths:
    """Build the on-disk layout for a new workspace."""
    if not workspace_key or len(workspace_key) < 16:
        raise ValueError("workspace_key must be at least 16 characters long.")
    base = root / "workspaces" / workspace_key
    return WorkspacePaths(
        workspace_dir=base,
        quarantine_dir=base / "quarantine",
        contents_dir=base / "contents",
    )


def new_workspace_key() -> str:
    """Return a fresh, unguessable workspace key."""
    return secrets.token_urlsafe(24)


def quarantine_archive(
    paths: WorkspacePaths,
    *,
    source: Callable[[int], bytes] | Iterable[bytes],
    limits: ArchiveLimits,
) -> tuple[Path, str, int]:
    """Stream ``source`` into the quarantine directory.

    ``source`` is either an iterable of byte chunks (any object
    that yields ``bytes`` when iterated) or a callable that
    returns a single chunk (used to fetch a fixed size from a
    buffer or ``SpooledTemporaryFile.read``). The total bytes
    written are bounded by ``limits.max_compressed_bytes``; the
    function raises :class:`ZipIntakeError` if the cap is
    exceeded.

    Returns ``(archive_path, sha256_hex, size)`` on success.
    """
    paths.ensure()
    archive_path = paths.quarantine_dir / "archive.bin"
    sha256_path = paths.quarantine_dir / "archive.sha256"
    if archive_path.exists():
        archive_path.unlink()
    if sha256_path.exists():
        sha256_path.unlink()

    import hashlib

    digest = hashlib.sha256()
    size = 0
    try:
        with archive_path.open("wb") as fh:
            if callable(source):
                chunk = source(DEFAULT_CHUNK_SIZE)
                while chunk:
                    size += len(chunk)
                    if size > limits.max_compressed_bytes:
                        raise ZipIntakeError(
                            "archive_compressed_too_large",
                            f"Archive exceeds max_compressed_bytes={limits.max_compressed_bytes}.",
                        )
                    digest.update(chunk)
                    fh.write(chunk)
                    chunk = source(DEFAULT_CHUNK_SIZE)
            else:
                for chunk in source:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > limits.max_compressed_bytes:
                        raise ZipIntakeError(
                            "archive_compressed_too_large",
                            f"Archive exceeds max_compressed_bytes={limits.max_compressed_bytes}.",
                        )
                    digest.update(chunk)
                    fh.write(chunk)
    except ZipIntakeError:
        archive_path.unlink(missing_ok=True)
        raise

    sha_hex = digest.hexdigest()
    sha256_path.write_text(sha_hex + "\n", encoding="ascii")
    return archive_path, sha_hex, size


def inspect_zip_entries(archive_path: Path) -> list[ArchiveEntry]:
    """Open ``archive_path`` and return one :class:`ArchiveEntry` per member.

    The function does not extract the archive; it only reads the
    central directory. A :class:`ZipIntakeError` is raised if
    the central directory is missing or unreadable.
    """
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            entries: list[ArchiveEntry] = []
            for info in zf.infolist():
                # Detect symlinks: zipfile stores unix mode in
                # ``external_attr`` shifted 16 bits. We only need
                # to know the file type; the entry is rejected
                # by the validator either way.
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                is_symlink = (unix_mode & _S_IFMT) == _S_IFLNK
                is_dir = info.is_dir()
                # v2.1.3: capture the literal link
                # target for symlink entries. The ZIP
                # format stores the target as the
                # entry's data, so we read it from the
                # handle. The validator never
                # dereferences the link; the target is
                # only inspected as a string.
                link_target: str | None = None
                if is_symlink and not is_dir:
                    try:
                        with zf.open(info, "r") as handle:
                            link_target = handle.read().decode(
                                "utf-8", errors="replace"
                            ) or None
                    except (KeyError, OSError, zipfile.BadZipFile):
                        link_target = None
                if is_dir:
                    # Directories are not counted as files. The
                    # path is still validated for safety.
                    entries.append(
                        ArchiveEntry(
                            name=info.filename,
                            size=0,
                            compressed_size=0,
                            is_symlink=is_symlink,
                        )
                    )
                    continue
                entries.append(
                    ArchiveEntry(
                        name=info.filename,
                        size=info.file_size,
                        compressed_size=info.compress_size,
                        is_symlink=is_symlink,
                        link_target=link_target,
                    )
                )
            return entries
    except zipfile.BadZipFile as exc:
        raise ZipIntakeError(
            "archive_invalid",
            f"Archive is not a valid ZIP file: {exc}",
        ) from exc


def validate_zip(
    entries: list[ArchiveEntry], limits: ArchiveLimits
) -> ArchiveValidationCollector:
    """Run the validator and surface both errors and skipped symlinks.

    The function returns the populated
    :class:`ArchiveValidationCollector` so the
    caller can read the ``skipped_symlinks``
    collection and persist it through the intake
    result. The function raises a
    :class:`ZipIntakeError` with the first
    :class:`ArchiveValidationError`'s code so the
    historical hard-fail semantics are preserved.
    Skipped symlinks are *not* an error.
    """
    collector = validate_entries(entries, limits)
    try:
        collector.ok()
    except ArchiveValidationError as exc:
        # Surface the same code under a
        # :class:`ZipIntakeError` so callers can
        # handle intake failures uniformly.
        raise ZipIntakeError(exc.code, exc.message) from exc
    return collector


def extract_zip(
    archive_path: Path,
    paths: WorkspacePaths,
    entries: list[ArchiveEntry],
    *,
    limits: ArchiveLimits,
) -> None:
    """Extract ``archive_path`` into ``paths.contents_dir``.

    The function re-validates every destination path while
    extracting and refuses to overwrite an existing file. The
    running totals (file count, uncompressed size) are kept in
    sync with ``limits`` so extraction stops as soon as the
    configured cap is hit.
    """
    paths.ensure()
    if not paths.contents_dir.exists():
        paths.contents_dir.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    file_count = 0
    uncompressed_total = 0
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                name = info.filename
                try:
                    normalized = normalize_relative_path(name)
                except PathNormalizationError as exc:
                    raise ZipIntakeError("archive_unsafe_path", str(exc)) from exc
                if info.is_dir():
                    target = paths.contents_dir / normalized.replace("/", os.sep)
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                # v2.1.3: the validator may have
                # recorded-and-skipped a symbolic
                # link. The extractor never materialises
                # the link; it simply moves on. Hardlinks
                # are not present here because the
                # validator rejected them with
                # ``archive_hardlink_forbidden``.
                if any(
                    e.is_symlink and normalize_relative_path(e.name) == normalized
                    for e in entries
                ):
                    continue
                if normalized in seen:
                    raise ZipIntakeError(
                        "archive_duplicate_entry",
                        f"Duplicate normalized path {normalized!r}.",
                    )
                seen.add(normalized)
                dest = paths.contents_dir / normalized.replace("/", os.sep)
                # Re-validate destination. The dest must stay
                # under ``contents_dir``.
                try:
                    dest_resolved = dest.resolve(strict=False)
                    contents_resolved = paths.contents_dir.resolve(strict=False)
                except OSError as exc:
                    raise ZipIntakeError(
                        "archive_path_resolve_failed",
                        f"Could not resolve destination path: {exc}",
                    ) from exc
                if not _is_within(dest_resolved, contents_resolved):
                    raise ZipIntakeError(
                        "archive_path_escape",
                        f"Destination {dest_resolved} is outside the workspace contents.",
                    )
                # v2.1.1: ``_mkdir_parents`` retries the call through
                # the long-path prefix on Windows when the
                # resolved path exceeds ``MAX_PATH`` (260). Same
                # rationale as in the tarball path above.
                _mkdir_parents(dest)
                if dest.exists() or dest.is_symlink():
                    raise ZipIntakeError(
                        "archive_overwrite_forbidden",
                        f"Destination {dest} already exists.",
                    )
                # Stream-extract with a hard cap on bytes read.
                file_count += 1
                if file_count > limits.max_file_count:
                    raise ZipIntakeError(
                        "archive_too_many_files",
                        f"Archive exceeds max_file_count={limits.max_file_count}.",
                    )
                if info.file_size > limits.max_file_bytes:
                    raise ZipIntakeError(
                        "archive_entry_too_large",
                        f"Entry {normalized!r} is {info.file_size} bytes; "
                        f"max is {limits.max_file_bytes}.",
                    )
                uncompressed_total += info.file_size
                if uncompressed_total > limits.max_uncompressed_bytes:
                    raise ZipIntakeError(
                        "archive_uncompressed_too_large",
                        "Cumulative uncompressed size exceeds limit.",
                    )
                with zf.open(info, "r") as src, _open_for_write(dest) as out:
                    _copy_capped(src, out, max_bytes=info.file_size + 1)
                # Update mtime / perms to match the archive entry
                # when reasonable.
                try:
                    mode = (info.external_attr >> 16) & 0o7777
                    if mode:
                        dest.chmod(mode)
                except OSError:  # pragma: no cover - non-fatal
                    pass
    except ZipIntakeError:
        # Clean up the partial contents directory.
        if paths.contents_dir.exists():
            shutil.rmtree(paths.contents_dir, ignore_errors=True)
            paths.contents_dir.mkdir(parents=True, exist_ok=True)
        raise


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _copy_capped(src: io.BufferedIOBase, dst: io.BufferedIOBase, *, max_bytes: int) -> int:
    written = 0
    while True:
        chunk = src.read(DEFAULT_CHUNK_SIZE)
        if not chunk:
            break
        written += len(chunk)
        if written > max_bytes:
            raise ZipIntakeError(
                "archive_entry_too_large",
                "Streamed entry exceeded the expected size.",
            )
        dst.write(chunk)
    return written


def intake_zip(
    paths: WorkspacePaths,
    *,
    source: Callable[[int], bytes] | Iterable[bytes],
    limits: ArchiveLimits,
) -> ZipIntakeResult:
    """Run the full intake pipeline (quarantine -> validate -> extract)."""
    archive_path, sha_hex, size = quarantine_archive(paths, source=source, limits=limits)
    entries = inspect_zip_entries(archive_path)
    # ``validate_zip`` returns the populated
    # collector; the skipped symlinks are surfaced
    # through the intake result so the scan evidence
    # layer can mark the analysis ``partial`` when
    # the omission matters.
    collector = validate_zip(entries, limits)
    extract_zip(archive_path, paths, entries, limits=limits)
    file_count = sum(1 for e in entries if not e.is_symlink and e.size >= 0)
    uncompressed_size = sum(max(0, e.size) for e in entries if not e.is_symlink)
    return ZipIntakeResult(
        archive_path=archive_path,
        archive_sha256=sha_hex,
        archive_size=size,
        file_count=file_count,
        uncompressed_size=uncompressed_size,
        contents_dir=paths.contents_dir,
        skipped_symlinks=tuple(collector.skipped_symlinks),
    )


def cleanup_workspace(paths: WorkspacePaths) -> None:
    """Remove a workspace from disk. No-op if it does not exist."""
    if paths.workspace_dir.exists():
        shutil.rmtree(paths.workspace_dir, ignore_errors=True)


def intake_tar_gz(
    paths: WorkspacePaths,
    *,
    source: Callable[[int], bytes] | Iterable[bytes],
    limits: ArchiveLimits,
) -> ZipIntakeResult:
    """Run the full intake pipeline for a gzip-compressed tar archive.

    The function is symmetrical with :func:`intake_zip` but uses
    :mod:`tarfile` to read the archive. Each member is validated
    against the same safety contract as ZIP entries; the
    v2.1.3 symlink policy classifies links into
    ``skip`` (safe relative symlinks) or ``reject``
    (anything unsafe). Hardlinks remain a hard
    fail; device files and unsafe paths continue to
    raise.
    """
    import gzip
    import tarfile

    paths.ensure()
    archive_path, sha_hex, size = quarantine_archive(paths, source=source, limits=limits)
    # Inspect the archive before extracting.
    entries: list[ArchiveEntry] = []
    seen_paths: set[str] = set()
    try:
        with gzip.open(archive_path, "rb") as gz, tarfile.open(fileobj=gz, mode="r:") as tf:
            for member in tf:
                if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise ZipIntakeError(
                        "archive_unsafe_entry",
                        f"Entry {member.name!r} is not a regular file, directory, or link.",
                    )
                name = member.name
                try:
                    normalized = normalize_relative_path(name)
                except PathNormalizationError as exc:
                    raise ZipIntakeError("archive_unsafe_path", str(exc)) from exc
                # v2.1.3: defer the symlink / hardlink
                # classification to the shared
                # ``validate_entries`` helper. The
                # tarball layer only records the
                # ``is_symlink`` / ``is_hardlink`` flag
                # and the literal link target so the
                # validator can decide whether the link
                # is safe to record and skip or whether
                # the link is unsafe and must be
                # rejected.
                if member.isdir():
                    entries.append(
                        ArchiveEntry(
                            name=name,
                            size=0,
                            compressed_size=0,
                            is_symlink=False,
                        )
                    )
                    continue
                if member.issym() or member.islnk():
                    entries.append(
                        ArchiveEntry(
                            name=name,
                            size=0,
                            compressed_size=0,
                            is_symlink=bool(member.issym()),
                            is_hardlink=bool(member.islnk()),
                            link_target=member.linkname or None,
                        )
                    )
                    continue
                if normalized in seen_paths:
                    raise ZipIntakeError(
                        "archive_duplicate_entry",
                        f"Duplicate normalized path {normalized!r}.",
                    )
                seen_paths.add(normalized)
                entries.append(
                    ArchiveEntry(
                        name=name,
                        size=member.size,
                        compressed_size=member.size,
                        is_symlink=False,
                    )
                )
    except ZipIntakeError:
        cleanup_workspace(paths)
        paths.ensure()
        raise
    except (gzip.BadGzipFile, tarfile.TarError, OSError) as exc:
        cleanup_workspace(paths)
        paths.ensure()
        raise ZipIntakeError(
            "archive_invalid",
            f"Archive is not a valid tar.gz file: {exc}",
        ) from exc

    try:
        collector = validate_zip(entries, limits)
    except Exception as exc:
        code = getattr(exc, "code", "archive_invalid")
        message = getattr(exc, "message", str(exc))
        cleanup_workspace(paths)
        paths.ensure()
        raise ZipIntakeError(code, message) from exc

    # Build the set of normalised entry paths the
    # validator recorded-and-skipped. The extractor
    # never materialises these entries in the workspace
    # because the validator's contract is "skip + do
    # not follow".
    skipped_paths = {record.path for record in collector.skipped_symlinks}

    # Extract validated entries.
    if not paths.contents_dir.exists():
        paths.contents_dir.mkdir(parents=True, exist_ok=True)
    file_count = 0
    uncompressed_total = 0
    try:
        with gzip.open(archive_path, "rb") as gz, tarfile.open(fileobj=gz, mode="r:") as tf:
            for member in tf:
                name = member.name
                try:
                    normalized = normalize_relative_path(name)
                except PathNormalizationError as exc:
                    raise ZipIntakeError("archive_unsafe_path", str(exc)) from exc
                if member.isdir():
                    target = paths.contents_dir / normalized.replace("/", os.sep)
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if member.issym() or member.islnk():
                    # Skipped symbolic links are
                    # intentionally not extracted.
                    # Hardlinks are not present here
                    # because the validator rejected
                    # them. The double-check below is a
                    # safety net.
                    if normalized in skipped_paths or member.issym():
                        continue
                    raise ZipIntakeError(
                        "archive_symlink_forbidden",
                        f"Entry {name!r} is a link; not accepted.",
                    )
                file_count += 1
                if file_count > limits.max_file_count:
                    raise ZipIntakeError(
                        "archive_too_many_files",
                        f"Archive exceeds max_file_count={limits.max_file_count}.",
                    )
                if member.size > limits.max_file_bytes:
                    raise ZipIntakeError(
                        "archive_entry_too_large",
                        f"Entry {name!r} is {member.size} bytes; max is {limits.max_file_bytes}.",
                    )
                uncompressed_total += member.size
                if uncompressed_total > limits.max_uncompressed_bytes:
                    raise ZipIntakeError(
                        "archive_uncompressed_too_large",
                        "Cumulative uncompressed size exceeds limit.",
                    )
                dest = paths.contents_dir / normalized.replace("/", os.sep)
                try:
                    dest_resolved = dest.resolve(strict=False)
                    contents_resolved = paths.contents_dir.resolve(strict=False)
                except OSError as exc:
                    raise ZipIntakeError(
                        "archive_path_resolve_failed",
                        f"Could not resolve destination path: {exc}",
                    ) from exc
                if not _is_within(dest_resolved, contents_resolved):
                    raise ZipIntakeError(
                        "archive_path_escape",
                        f"Destination {dest_resolved} is outside the workspace contents.",
                    )
                # v2.1.1: ``dest.parent.mkdir(parents=True, exist_ok=True)``
                # is the historical mkdir call, but on Windows
                # the resulting path can exceed ``MAX_PATH``
                # (260) for a long-named repository + full
                # SHA + deep tree. ``_mkdir_parents`` retries
                # the call through the long-path prefix in
                # that case so the extraction does not abort
                # with a confusing ``FileNotFoundError`` on a
                # valid workspace root. ``_open_for_write``
                # applies the same fix to the file handle.
                _mkdir_parents(dest)
                if dest.exists() or dest.is_symlink():
                    raise ZipIntakeError(
                        "archive_overwrite_forbidden",
                        f"Destination {dest} already exists.",
                    )
                src = tf.extractfile(member)
                if src is None:
                    raise ZipIntakeError(
                        "archive_extract_failed",
                        f"Could not extract {name!r}.",
                    )
                with _open_for_write(dest) as out:
                    while True:
                        chunk = src.read(DEFAULT_CHUNK_SIZE)
                        if not chunk:
                            break
                        out.write(chunk)
    except ZipIntakeError:
        if paths.contents_dir.exists():
            shutil.rmtree(paths.contents_dir, ignore_errors=True)
            paths.contents_dir.mkdir(parents=True, exist_ok=True)
        raise

    file_count_final = sum(
        1
        for e in entries
        if not e.is_symlink and not e.is_hardlink and e.size >= 0
    )
    uncompressed_size_final = sum(
        max(0, e.size)
        for e in entries
        if not e.is_symlink and not e.is_hardlink
    )
    return ZipIntakeResult(
        archive_path=archive_path,
        archive_sha256=sha_hex,
        archive_size=size,
        file_count=file_count_final,
        uncompressed_size=uncompressed_size_final,
        contents_dir=paths.contents_dir,
        skipped_symlinks=tuple(collector.skipped_symlinks),
    )
