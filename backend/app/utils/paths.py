"""Relative path normalization and validation.

The scanner only ever speaks in terms of *normalized relative paths*
inside an extracted archive or repository tree. Absolute paths, Windows
drive paths, UNC paths, parent traversal, and null bytes are never
acceptable in this representation. The normalization is deliberately
strict: any rejection is a defensive boundary, not a UX choice.
"""

from __future__ import annotations

import os
import re
import unicodedata

# Windows drive-letter prefix: e.g. ``C:`` or ``C:\``.
_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:[\\/]?")
# UNC path prefix on either platform spelling: ``\\server\share`` or
# ``//server/share``.
_UNC_RE = re.compile(r"^[/\\\\]{2}[^/\\\\]")


class PathNormalizationError(ValueError):
    """Raised when a path cannot be normalized safely."""


def normalize_relative_path(raw: str) -> str:
    """Return the canonical relative path for ``raw``.

    The returned value always uses forward slashes, never starts with a
    slash, never contains a parent-traversal segment, never contains a
    null byte, and never represents an absolute, drive-letter, or UNC
    path. Empty input is rejected.

    Raises :class:`PathNormalizationError` for any input that does not
    represent a safe relative path.
    """
    if not isinstance(raw, str):
        raise PathNormalizationError("Path must be a string.")
    if not raw:
        raise PathNormalizationError("Path is empty.")

    # Reject any embedded NUL byte - they have no legitimate use in a
    # path and are a classic truncation vector.
    if "\x00" in raw:
        raise PathNormalizationError("Path contains a NUL byte.")

    # Normalize unicode to NFC. Some operating systems are case-
    # insensitive over certain code points; NFC keeps the on-disk
    # representation consistent.
    candidate = unicodedata.normalize("NFC", raw)

    # Reject absolute POSIX paths up front.
    if candidate.startswith("/"):
        raise PathNormalizationError("Absolute paths are not accepted.")

    # Reject Windows drive-letter paths.
    if _DRIVE_LETTER_RE.match(candidate):
        raise PathNormalizationError("Drive-letter paths are not accepted.")

    # Reject UNC paths.
    if _UNC_RE.match(candidate):
        raise PathNormalizationError("UNC paths are not accepted.")

    # Split on any slash, normalize, drop empties. This collapses
    # consecutive separators, which our contract disallows in their raw
    # form.
    parts = re.split(r"[\\/]+", candidate)
    cleaned: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise PathNormalizationError("Parent traversal is not accepted.")
        cleaned.append(part)

    if not cleaned:
        raise PathNormalizationError("Path is empty after normalization.")

    # Reject paths that contain a null byte in any segment. The check
    # above already covers this but is repeated after splitting for
    # defence in depth.
    for segment in cleaned:
        if "\x00" in segment:
            raise PathNormalizationError("Path contains a NUL byte.")
        if os.path.basename(segment) in (".", ".."):
            raise PathNormalizationError("Path contains forbidden segments.")

    return "/".join(cleaned)


def join_relative(*parts: str) -> str:
    """Join several path fragments and return the normalized result.

    Convenience helper for analyzers that build a path from multiple
    pieces. All fragments are validated and combined.
    """
    combined = "/".join(p.lstrip("/").rstrip("/") for p in parts if p)
    return normalize_relative_path(combined or "/")
