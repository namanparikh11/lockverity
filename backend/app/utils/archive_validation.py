"""Archive-entry validation contract.

Lockverity v0.1 does **not** extract archives. It validates the entries
inside a zip / tar stream up front so a malicious upload cannot reach
the filesystem layer. The validation is intentionally aggressive: the
default behavior is to reject anything that does not pass every check.

Validation performed on each archive entry:

1. Path traversal (``../``, ``..\\``)
2. Absolute POSIX paths (``/etc/passwd``)
3. Windows drive-letter paths (``C:\\evil``)
4. UNC paths (``\\\\server\\share``)
5. Symbolic-link and hard-link entries when the format exposes the
   metadata
6. Duplicate normalized entries (zip slip variants that bypass the path
   check via encodings)
7. Excessive directory depth
8. Oversized individual entries
9. Excessive cumulative uncompressed size
10. Suspicious compression ratios (zip bomb heuristic)
11. Excessive file count
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.utils.paths import PathNormalizationError, normalize_relative_path


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Configurable limits for archive-entry validation."""

    max_compressed_bytes: int
    max_uncompressed_bytes: int
    max_file_count: int
    max_file_bytes: int
    max_depth: int
    suspicious_ratio: int


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    """A single archive entry, decoupled from any specific archive format.

    The scanner layer is responsible for converting the library-specific
    entry (zipfile.ZipInfo, tarfile.TarInfo) into this neutral record.
    """

    name: str
    size: int
    compressed_size: int
    is_symlink: bool = False
    is_hardlink: bool = False
    # Link target for symlink/hardlink entries. Only inspected when
    # ``is_symlink`` or ``is_hardlink`` is true.
    link_target: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveValidationError(ValueError):
    """Raised when an archive fails validation."""

    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.code}] {self.message}"


class ArchiveValidationCollector:
    """Stateful collector for archive-entry validation.

    Use this when you want to collect every violation rather than fail
    fast. The collector is intentionally explicit - you call
    :meth:`ok` once the iteration completes to assert the archive is
    safe.
    """

    def __init__(self, limits: ArchiveLimits) -> None:
        self.limits = limits
        self._errors: list[ArchiveValidationError] = []
        self._seen_paths: set[str] = set()
        self._file_count = 0
        self._uncompressed_total = 0
        self._compressed_total = 0

    @property
    def errors(self) -> tuple[ArchiveValidationError, ...]:
        return tuple(self._errors)

    @property
    def file_count(self) -> int:
        return self._file_count

    @property
    def uncompressed_total(self) -> int:
        return self._uncompressed_total

    @property
    def compressed_total(self) -> int:
        return self._compressed_total

    def check_entry(self, entry: ArchiveEntry) -> None:
        """Validate ``entry`` and record any violations."""
        # 1. Path normalization handles traversal, absolute paths, drive
        # letters, and UNC paths in one go.
        try:
            normalized = normalize_relative_path(entry.name)
        except PathNormalizationError as exc:
            self._errors.append(ArchiveValidationError("archive_unsafe_path", str(exc)))
            return

        depth = normalized.count("/") + 1
        if depth > self.limits.max_depth:
            self._errors.append(
                ArchiveValidationError(
                    "archive_depth_exceeded",
                    f"Entry {entry.name!r} depth {depth} exceeds "
                    f"max_depth={self.limits.max_depth}.",
                )
            )
            return

        # 2. Symlink / hardlink detection. We refuse to even *read* the
        # target so a malicious archive cannot tempt us into evaluating
        # one.
        if entry.is_symlink:
            self._errors.append(
                ArchiveValidationError(
                    "archive_symlink_forbidden",
                    f"Entry {entry.name!r} is a symbolic link; not accepted.",
                )
            )
            return
        if entry.is_hardlink:
            self._errors.append(
                ArchiveValidationError(
                    "archive_hardlink_forbidden",
                    f"Entry {entry.name!r} is a hard link; not accepted.",
                )
            )
            return

        # 3. Duplicate normalized entries.
        if normalized in self._seen_paths:
            self._errors.append(
                ArchiveValidationError(
                    "archive_duplicate_entry",
                    f"Duplicate normalized path {normalized!r}.",
                )
            )
            return
        self._seen_paths.add(normalized)

        # 4. Individual entry size.
        if entry.size < 0:
            self._errors.append(
                ArchiveValidationError(
                    "archive_negative_size",
                    f"Entry {entry.name!r} has negative size.",
                )
            )
            return
        if entry.size > self.limits.max_file_bytes:
            self._errors.append(
                ArchiveValidationError(
                    "archive_entry_too_large",
                    f"Entry {entry.name!r} is {entry.size} bytes; "
                    f"max is {self.limits.max_file_bytes}.",
                )
            )
            return

        # 5. File count limit.
        self._file_count += 1
        if self._file_count > self.limits.max_file_count:
            self._errors.append(
                ArchiveValidationError(
                    "archive_too_many_files",
                    f"Archive exceeds max_file_count={self.limits.max_file_count}.",
                )
            )
            return

        # 6. Uncompressed cumulative size.
        self._uncompressed_total += entry.size
        if self._uncompressed_total > self.limits.max_uncompressed_bytes:
            self._errors.append(
                ArchiveValidationError(
                    "archive_uncompressed_too_large",
                    "Cumulative uncompressed size exceeds limit.",
                )
            )
            return

        # 7. Compressed cumulative size.
        self._compressed_total += max(0, entry.compressed_size)
        if self._compressed_total > self.limits.max_compressed_bytes:
            self._errors.append(
                ArchiveValidationError(
                    "archive_compressed_too_large",
                    "Cumulative compressed size exceeds limit.",
                )
            )
            return

        # 8. Compression-ratio heuristic. We only flag a ratio when both
        # numerator and denominator are non-zero, so a single zero-byte
        # entry does not produce a divide-by-zero or a false positive.
        if (
            entry.compressed_size > 0
            and entry.size > 0
            and entry.size >= self.limits.suspicious_ratio * entry.compressed_size
        ):
            self._errors.append(
                ArchiveValidationError(
                    "archive_suspicious_compression",
                    f"Entry {entry.name!r} compresses "
                    f"{entry.size // entry.compressed_size}x; "
                    f"ratio above {self.limits.suspicious_ratio}x is suspicious.",
                )
            )

    def ok(self) -> None:
        """Raise :class:`ArchiveValidationError` if any errors are pending."""
        if self._errors:
            first = self._errors[0]
            raise ArchiveValidationError(first.code, first.message)


def validate_entries(
    entries: Iterable[ArchiveEntry],
    limits: ArchiveLimits,
) -> ArchiveValidationCollector:
    """Validate every entry in ``entries`` and return the collector."""
    collector = ArchiveValidationCollector(limits)
    for entry in entries:
        collector.check_entry(entry)
    collector.ok()
    return collector


def limits_from_settings(values: Mapping[str, int]) -> ArchiveLimits:
    """Build an :class:`ArchiveLimits` from a settings-like mapping."""
    return ArchiveLimits(
        max_compressed_bytes=int(values["max_compressed_bytes"]),
        max_uncompressed_bytes=int(values["max_uncompressed_bytes"]),
        max_file_count=int(values["max_file_count"]),
        max_file_bytes=int(values["max_file_bytes"]),
        max_depth=int(values["max_depth"]),
        suspicious_ratio=int(values["suspicious_ratio"]),
    )
