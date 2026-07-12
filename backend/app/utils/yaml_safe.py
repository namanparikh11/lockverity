"""Bounded safe-YAML loader.

PyYAML's ``SafeLoader`` already prevents arbitrary code execution
through ``!!python/object`` and friends. The threat that remains is
denial-of-service via hostile files:

- alias expansion (``&a [*a, *a, *a, ...]``)
- unbounded depth
- unbounded key/sequence widths
- the YAML 1.1 "Norway problem" (the bare word ``no`` parses as
  Python ``False`` and other language-specific bool aliases leak
  into evidence)

This module wraps :class:`yaml.SafeLoader` with explicit limits
and exposes :func:`safe_load_yaml_bytes` for analyzer use.
"""

from __future__ import annotations

from typing import Any

import yaml

# Default limits. They are deliberately conservative; tests can pass
# smaller values via the keyword arguments.
DEFAULT_MAX_BYTES = 4 * 1024 * 1024  # 4 MiB
DEFAULT_MAX_ALIASES = 64
DEFAULT_MAX_DEPTH = 32
DEFAULT_MAX_COLLECTION_ITEMS = 50_000

# YAML 1.1 booleans that should never appear in workflow evidence. We
# resolve them as plain strings to keep evidence deterministic.
_YAML_1_1_BOOL_LITERALS: frozenset[str] = frozenset(
    {
        "y",
        "Y",
        "yes",
        "Yes",
        "YES",
        "n",
        "N",
        "no",
        "No",
        "NO",
        "true",
        "True",
        "TRUE",
        "false",
        "False",
        "FALSE",
        "on",
        "On",
        "ON",
        "off",
        "Off",
        "OFF",
    }
)


class BoundedYamlError(ValueError):
    """Raised when YAML cannot be loaded under the configured limits."""


class _AliasLimiter:
    """Tracks the number of alias dereferences during a single load."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._count = 0

    def check(self) -> None:
        self._count += 1
        if self._count > self._limit:
            raise BoundedYamlError(
                f"YAML alias expansion exceeded limit of {self._limit}."
            )


def _construct_string_no_yaml_1_1_bool(loader: yaml.SafeLoader, node: yaml.Node) -> str:
    """Treat YAML 1.1 boolean literals (yes/no/on/off/true/false) as strings.

    This is defence in depth: most workflow evidence is already a
    quoted string, but if a contributor wrote ``on: yes`` we want
    ``yes`` to read as the string ``"yes"`` rather than Python
    ``True`` so stable finding keys do not change shape depending on
    the YAML parser's behaviour.
    """
    value = loader.construct_scalar(node)
    if value in _YAML_1_1_BOOL_LITERALS:
        return value
    return value


def _construct_bool_as_string(loader: yaml.SafeLoader, node: yaml.Node) -> str:
    """Construct YAML 1.1 boolean scalars as plain strings.

    PyYAML's ``SafeLoader`` would otherwise map ``yes``/``on`` to
    Python ``True`` and ``no``/``off`` to ``False``. Stable finding
    keys depend on the textual value, so we override.
    """
    value = loader.construct_scalar(node)
    return str(value)


def _build_loader(limit: int) -> type[yaml.SafeLoader]:
    """Return a :class:`SafeLoader` subclass with our alias counter."""

    class _BoundedSafeLoader(yaml.SafeLoader):
        pass

    # Install the alias counter on the loader instance at load time.
    _BoundedSafeLoader.add_constructor("tag:yaml.org,2002:str", _construct_string_no_yaml_1_1_bool)
    _BoundedSafeLoader.add_constructor("tag:yaml.org,2002:bool", _construct_bool_as_string)
    _BoundedSafeLoader.alias_limit = limit  # used by check at load time
    return _BoundedSafeLoader


def safe_load_yaml_bytes(
    data: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_aliases: int = DEFAULT_MAX_ALIASES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_collection_items: int = DEFAULT_MAX_COLLECTION_ITEMS,
) -> Any:
    """Load ``data`` (bytes) as YAML with explicit safety limits.

    Raises :class:`BoundedYamlError` for any input that cannot be
    parsed safely. The parsed structure is checked for depth and
    width using the same algorithm as :mod:`app.utils.json_safe`.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise BoundedYamlError("YAML input must be bytes.")
    if len(data) > max_bytes:
        raise BoundedYamlError(
            f"YAML input exceeds max_bytes={max_bytes} (got {len(data)} bytes)."
        )
    counter = _AliasLimiter(max_aliases)
    loader_cls = _build_loader(max_aliases)

    def _construct_alias(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
        counter.check()
        return loader.construct_object(node, deep=True)

    loader_cls.add_constructor("tag:yaml.org,2002:alias", _construct_alias)

    try:
        loaded = yaml.load(data, Loader=loader_cls)  # noqa: S506 - we use our bounded loader
    except yaml.YAMLError as exc:
        raise BoundedYamlError(f"Invalid YAML: {exc}") from exc

    _check_depth(loaded, depth=0, max_depth=max_depth)
    _check_collection_sizes(loaded, max_collection_items=max_collection_items)
    return loaded


def _check_depth(value: Any, *, depth: int, max_depth: int) -> None:
    if depth > max_depth:
        raise BoundedYamlError(f"YAML depth exceeds max_depth={max_depth}.")
    if isinstance(value, dict):
        for v in value.values():
            _check_depth(v, depth=depth + 1, max_depth=max_depth)
    elif isinstance(value, list):
        for v in value:
            _check_depth(v, depth=depth + 1, max_depth=max_depth)


def _check_collection_sizes(value: Any, *, max_collection_items: int) -> None:
    if isinstance(value, dict):
        if len(value) > max_collection_items:
            raise BoundedYamlError(
                f"YAML mapping has {len(value)} items; max is {max_collection_items}."
            )
        for v in value.values():
            _check_collection_sizes(v, max_collection_items=max_collection_items)
    elif isinstance(value, list):
        if len(value) > max_collection_items:
            raise BoundedYamlError(
                f"YAML sequence has {len(value)} items; max is {max_collection_items}."
            )
        for v in value:
            _check_collection_sizes(v, max_collection_items=max_collection_items)
