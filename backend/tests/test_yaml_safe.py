"""Tests for :mod:`app.utils.yaml_safe`."""

from __future__ import annotations

import pytest
from app.utils.yaml_safe import BoundedYamlError, safe_load_yaml_bytes


def test_parses_basic_mapping() -> None:
    out = safe_load_yaml_bytes(b"a: 1\nb: 2\n")
    assert out == {"a": 1, "b": 2}


def test_parses_nested_sequence() -> None:
    out = safe_load_yaml_bytes(b"- 1\n- 2\n- [3, 4]\n")
    assert out == [1, 2, [3, 4]]


def test_rejects_oversize_input() -> None:
    big = b"a: 1\n" * 200_000
    with pytest.raises(BoundedYamlError):
        safe_load_yaml_bytes(big, max_bytes=8 * 192)


def test_rejects_oversize_default_input() -> None:
    big = b"a: 1\n" * 1_000_000  # > 4 MiB
    with pytest.raises(BoundedYamlError):
        safe_load_yaml_bytes(big)


def test_rejects_alias_bomb() -> None:
    payload = b"a: &x ['x','x','x','x','x','x','x','x','x','x']\n" * 200
    with pytest.raises(BoundedYamlError):
        safe_load_yaml_bytes(payload, max_aliases=10)


def test_rejects_excessive_depth() -> None:
    deep = b"a: " * 200 + b"1\n"
    with pytest.raises(BoundedYamlError):
        safe_load_yaml_bytes(deep, max_depth=10)


def test_rejects_huge_collection() -> None:
    items = ",".join(f'"{i}"' for i in range(500))
    with pytest.raises(BoundedYamlError):
        safe_load_yaml_bytes(f"[{items}]", max_collection_items=100)


def test_rejects_non_bytes() -> None:
    with pytest.raises(BoundedYamlError):
        safe_load_yaml_bytes("a: 1")  # type: ignore[arg-type]


def test_yaml_1_1_bool_literals_preserved_as_strings() -> None:
    out = safe_load_yaml_bytes(b"flag_yes: yes\nflag_no: no\nflag_on: on\n")
    assert out == {"flag_yes": "yes", "flag_no": "no", "flag_on": "on"}


def test_yaml_unfamiliar_construct_raises() -> None:
    bad = b"!!python/object/apply:os.system ['echo hi']\n"
    with pytest.raises(BoundedYamlError):
        safe_load_yaml_bytes(bad)
