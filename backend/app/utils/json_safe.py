"""Bounded JSON validation and serialization.

Lockverity never trusts incoming JSON to be small, shallow, or free of
non-serializable types. This module wraps :mod:`json` with the limits
required to keep JSON-related bugs off the security-relevant path:

- size limit on input
- depth limit on parsed structures
- width limit on lists/dicts
- string-length limit on string values
- deterministic key ordering on dump
- safe fallback for non-serializable values
"""

from __future__ import annotations

import json
from typing import Any

DEFAULT_MAX_BYTES = 8 * 1024 * 1024  # 8 MiB
DEFAULT_MAX_DEPTH = 32
DEFAULT_MAX_COLLECTION_ITEMS = 50_000
DEFAULT_MAX_STRING_LENGTH = 1_000_000  # 1 MB per string


class BoundedJsonError(ValueError):
    """Raised when JSON cannot be parsed under the configured limits."""


def parse_bounded_json(
    data: bytes | str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_collection_items: int = DEFAULT_MAX_COLLECTION_ITEMS,
    max_string_length: int = DEFAULT_MAX_STRING_LENGTH,
) -> Any:
    """Parse JSON with explicit size, depth, and width limits.

    Raises :class:`BoundedJsonError` if any limit would be exceeded.
    """
    data_bytes = data.encode("utf-8") if isinstance(data, str) else data
    if len(data_bytes) > max_bytes:
        raise BoundedJsonError(f"JSON input exceeds max_bytes={max_bytes}.")
    try:
        parsed = json.loads(data_bytes)
    except json.JSONDecodeError as exc:
        raise BoundedJsonError(f"Invalid JSON: {exc.msg}") from exc
    _check_depth(parsed, depth=0, max_depth=max_depth)
    _check_collection_sizes(
        parsed,
        max_collection_items=max_collection_items,
        max_string_length=max_string_length,
    )
    return parsed


def _check_depth(value: Any, *, depth: int, max_depth: int) -> None:
    if depth > max_depth:
        raise BoundedJsonError(f"JSON depth exceeds max_depth={max_depth}.")
    if isinstance(value, dict):
        for v in value.values():
            _check_depth(v, depth=depth + 1, max_depth=max_depth)
    elif isinstance(value, list):
        for v in value:
            _check_depth(v, depth=depth + 1, max_depth=max_depth)


def _check_collection_sizes(
    value: Any,
    *,
    max_collection_items: int,
    max_string_length: int,
) -> None:
    if isinstance(value, dict):
        if len(value) > max_collection_items:
            raise BoundedJsonError(
                f"JSON object has {len(value)} items; max is {max_collection_items}."
            )
        for k, v in value.items():
            if not isinstance(k, str):
                raise BoundedJsonError("JSON object keys must be strings.")
            if len(k) > max_string_length:
                raise BoundedJsonError(f"JSON key exceeds max_string_length={max_string_length}.")
            _check_collection_sizes(
                v,
                max_collection_items=max_collection_items,
                max_string_length=max_string_length,
            )
    elif isinstance(value, list):
        if len(value) > max_collection_items:
            raise BoundedJsonError(
                f"JSON array has {len(value)} items; max is {max_collection_items}."
            )
        for v in value:
            _check_collection_sizes(
                v,
                max_collection_items=max_collection_items,
                max_string_length=max_string_length,
            )
    elif isinstance(value, str):
        if len(value) > max_string_length:
            raise BoundedJsonError(f"JSON string exceeds max_string_length={max_string_length}.")


def dump_bounded_json(
    value: Any,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    sort_keys: bool = True,
    default: Any = None,
) -> str:
    """Serialize ``value`` to JSON, rejecting output above ``max_bytes``.

    A custom ``default`` callable can be supplied to coerce
    non-serializable values. The result is deterministic when
    ``sort_keys`` is true.
    """
    serialized = json.dumps(
        value,
        sort_keys=sort_keys,
        separators=(",", ":"),
        ensure_ascii=False,
        default=default,
    )
    if len(serialized.encode("utf-8")) > max_bytes:
        raise BoundedJsonError(f"Serialized JSON exceeds max_bytes={max_bytes}.")
    return serialized
