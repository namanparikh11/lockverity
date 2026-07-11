"""Tests for :mod:`app.utils.json_safe`."""

from __future__ import annotations

import pytest
from app.utils.json_safe import (
    BoundedJsonError,
    dump_bounded_json,
    parse_bounded_json,
)


def test_parse_basic() -> None:
    assert parse_bounded_json('{"a": 1, "b": [1,2,3]}') == {"a": 1, "b": [1, 2, 3]}


def test_parse_rejects_oversize() -> None:
    big = '{"x": "' + ("a" * (8 * 1024 * 1024 + 1)) + '"}'
    with pytest.raises(BoundedJsonError):
        parse_bounded_json(big, max_bytes=8 * 1024 * 1024)


def test_parse_rejects_deep() -> None:
    payload = '{"a":' * 50 + "1" + "}" * 50
    with pytest.raises(BoundedJsonError):
        parse_bounded_json(payload, max_depth=10)


def test_parse_rejects_huge_collection() -> None:
    items = ",".join(f'"{i}"' for i in range(200))
    with pytest.raises(BoundedJsonError):
        parse_bounded_json(f"[{items}]", max_collection_items=100)


def test_parse_rejects_long_string() -> None:
    payload = '{"k":"' + ("a" * 200) + '"}'
    with pytest.raises(BoundedJsonError):
        parse_bounded_json(payload, max_string_length=100)


def test_parse_rejects_invalid_json() -> None:
    with pytest.raises(BoundedJsonError):
        parse_bounded_json("not json")


def test_parse_does_not_call_default() -> None:
    # ``default`` is not used in ``parse_bounded_json``; this just
    # documents the contract.
    out = parse_bounded_json("1")
    assert out == 1


def test_dump_deterministic() -> None:
    a = dump_bounded_json({"b": 1, "a": 2})
    b = dump_bounded_json({"a": 2, "b": 1})
    assert a == b == '{"a":2,"b":1}'


def test_dump_rejects_oversize() -> None:
    big = {"x": "a" * (8 * 1024 * 1024 + 1)}
    with pytest.raises(BoundedJsonError):
        dump_bounded_json(big, max_bytes=8 * 1024 * 1024)
