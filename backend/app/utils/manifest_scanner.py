"""Manifest discovery for a parsed repository tree.

The scanner receives a list of ``(relative_path, content_bytes)``
tuples (typically produced by the archive or GitHub provider in
later milestones) and returns a *deterministic, deduplicated* list
of :class:`DiscoveredManifest` records.

Hard guarantees:

- No file is opened or executed - only the bytes the caller
  already holds are inspected.
- Every path is normalized via :func:`app.utils.paths.normalize_relative_path`
  before any decision is made.
- A small, explicit set of ignored directories is never inspected
  even if the caller accidentally forwards a path inside one.
- A per-file size limit stops the scanner from hashing unbounded
  blobs in memory.
- An overall manifest count cap stops the scanner from materializing
  an unbounded list.
- A SHA-256 content hash is computed for every kept manifest.
- The returned list is sorted by ``path`` so callers can rely on
  deterministic ordering.
- Files that *look* like a manifest but are skipped get a structured
  :class:`SkippedManifest` so the caller can record an honest
  observation in the database.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from app.utils.paths import PathNormalizationError, normalize_relative_path

# Default caps. The caps are chosen to be safe by default for any
# real repository; the analyzer layer may tighten them.
DEFAULT_MAX_MANIFEST_BYTES = 4 * 1024 * 1024  # 4 MiB per file
DEFAULT_MAX_MANIFEST_COUNT = 5_000

# Directories that are never inspected, even when the caller passes a
# path inside one. All names are matched case-insensitively and on
# path segments, not substrings.
IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".next",
        "target",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "vendor",
    }
)

# Map of basename to the parser ``manifest_type`` string and ecosystem.
# The keys are lowercased; lookups in :func:`classify_manifest` are
# case-insensitive.
_MANIFEST_KIND: dict[str, tuple[str, str | None]] = {
    "package.json": ("package_json", "npm"),
    "package-lock.json": ("package_lock", "npm"),
    "pnpm-lock.yaml": ("pnpm_lock", "npm"),
    "yarn.lock": ("yarn_lock", "npm"),
    "requirements.txt": ("requirements_txt", "pypi"),
    "pyproject.toml": ("pyproject_toml", "pypi"),
    "poetry.lock": ("poetry_lock", "pypi"),
}


class SkipReason(str, Enum):
    """Reason a candidate path was rejected by the scanner."""

    UNSAFE_PATH = "unsafe_path"
    IGNORED_DIRECTORY = "ignored_directory"
    UNKNOWN_MANIFEST = "unknown_manifest"
    TOO_LARGE = "too_large"
    TOO_MANY = "too_many"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class DiscoveredManifest:
    """A manifest the analyzer should parse."""

    path: str
    manifest_type: str
    ecosystem: str | None
    content: bytes
    content_sha256: str


@dataclass(frozen=True, slots=True)
class SkippedManifest:
    """A path the scanner deliberately ignored."""

    path: str
    reason: SkipReason
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Outcome of a :func:`discover_manifests` call."""

    manifests: tuple[DiscoveredManifest, ...]
    skipped: tuple[SkippedManifest, ...]


def _segment_names(path: str) -> list[str]:
    """Return the lowercased segments of ``path``."""
    return [segment.lower() for segment in path.split("/") if segment]


def classify_manifest(path: str) -> tuple[str, str | None] | None:
    """Return the ``(manifest_type, ecosystem)`` for ``path`` or ``None``.

    The lookup is by basename and is case-insensitive.
    """
    if not path:
        return None
    normalized = path.replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1].lower()
    return _MANIFEST_KIND.get(basename)


def _is_in_ignored_directory(path: str) -> bool:
    return any(segment in IGNORED_DIRS for segment in _segment_names(path))


def _hash_bytes_bounded(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def discover_manifests(
    files: Iterable[tuple[str, bytes]],
    *,
    max_manifest_bytes: int = DEFAULT_MAX_MANIFEST_BYTES,
    max_manifest_count: int = DEFAULT_MAX_MANIFEST_COUNT,
) -> DiscoveryResult:
    """Return a deterministic, deduplicated list of discovered manifests.

    Iterates ``files`` exactly once. Every input is classified as
    either a :class:`DiscoveredManifest` (kept) or a
    :class:`SkippedManifest` (rejected with reason).
    """
    kept: dict[str, DiscoveredManifest] = {}
    skipped: list[SkippedManifest] = []

    for raw_path, content in files:
        try:
            normalized = normalize_relative_path(raw_path)
        except PathNormalizationError as exc:
            skipped.append(
                SkippedManifest(path=raw_path, reason=SkipReason.UNSAFE_PATH, detail=str(exc))
            )
            continue

        if _is_in_ignored_directory(normalized):
            skipped.append(
                SkippedManifest(
                    path=normalized,
                    reason=SkipReason.IGNORED_DIRECTORY,
                    detail="path is inside a scanner-ignored directory",
                )
            )
            continue

        kind = classify_manifest(normalized)
        if kind is None:
            # Not a manifest we recognize. We deliberately do not
            # record a ``SkippedManifest`` for every unrelated file
            # because that would explode the database for large
            # repositories.
            continue

        if not isinstance(content, (bytes, bytearray)):
            skipped.append(
                SkippedManifest(
                    path=normalized,
                    reason=SkipReason.UNSAFE_PATH,
                    detail="content is not bytes",
                )
            )
            continue

        if len(content) > max_manifest_bytes:
            skipped.append(
                SkippedManifest(
                    path=normalized,
                    reason=SkipReason.TOO_LARGE,
                    detail=f"content is {len(content)} bytes; max is {max_manifest_bytes}",
                )
            )
            continue

        if normalized in kept:
            skipped.append(
                SkippedManifest(
                    path=normalized,
                    reason=SkipReason.DUPLICATE,
                    detail="path already discovered from an earlier entry",
                )
            )
            continue

        if len(kept) >= max_manifest_count:
            skipped.append(
                SkippedManifest(
                    path=normalized,
                    reason=SkipReason.TOO_MANY,
                    detail=f"manifest count limit of {max_manifest_count} reached",
                )
            )
            continue

        manifest_type, ecosystem = kind
        digest = _hash_bytes_bounded(bytes(content))
        kept[normalized] = DiscoveredManifest(
            path=normalized,
            manifest_type=manifest_type,
            ecosystem=ecosystem,
            content=bytes(content),
            content_sha256=digest,
        )

    ordered = tuple(sorted(kept.values(), key=lambda m: m.path))
    return DiscoveryResult(manifests=ordered, skipped=tuple(skipped))
