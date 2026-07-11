"""SHA-256 hashing helpers for bytes and bounded file streams."""

from __future__ import annotations

import hashlib
from typing import BinaryIO

# A single buffer size for streaming hashing. 1 MiB balances syscall
# overhead and memory footprint. Tests can override the limit by
# monkey-patching this constant.
DEFAULT_CHUNK_SIZE = 1024 * 1024

# Hard cap on bytes hashed by :func:`hash_bytes` so the API cannot be
# coerced into hashing arbitrarily large blobs in memory.
MAX_INLINE_HASH_BYTES = 64 * 1024 * 1024  # 64 MiB


def hash_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of ``data``.

    Raises :class:`ValueError` if the input exceeds
    :data:`MAX_INLINE_HASH_BYTES`. For larger inputs, stream from a file
    using :func:`hash_stream` or :func:`hash_file`.
    """
    if len(data) > MAX_INLINE_HASH_BYTES:
        raise ValueError(
            f"Refusing to hash {len(data)} bytes in memory; "
            f"limit is {MAX_INLINE_HASH_BYTES}. Use hash_stream() instead."
        )
    return hashlib.sha256(data).hexdigest()


def hash_stream(stream: BinaryIO, *, max_bytes: int | None = None) -> str:
    """Hash a binary stream and return the hex SHA-256 digest.

    If ``max_bytes`` is set, the stream is read up to that many bytes.
    A :class:`ValueError` is raised when the cap would be exceeded.
    """
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = stream.read(DEFAULT_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            raise ValueError(f"Stream exceeded max_bytes={max_bytes} while hashing.")
        digest.update(chunk)
    return digest.hexdigest()


def hash_file(path: str, *, max_bytes: int | None = None) -> str:
    """Open ``path`` and return the hex SHA-256 of its contents."""
    with open(path, "rb") as fh:
        return hash_stream(fh, max_bytes=max_bytes)
