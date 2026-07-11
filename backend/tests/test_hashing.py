"""Tests for :mod:`app.utils.hashing`."""

from __future__ import annotations

import io

import pytest
from app.utils.hashing import hash_bytes, hash_stream


def test_hash_bytes_known_value() -> None:
    assert hash_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert hash_bytes(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_hash_bytes_rejects_oversized_input() -> None:
    big = b"x" * (64 * 1024 * 1024 + 1)
    with pytest.raises(ValueError):
        hash_bytes(big)


def test_hash_stream_matches_hash_bytes() -> None:
    data = b"hello lockverity"
    assert hash_stream(io.BytesIO(data)) == hash_bytes(data)


def test_hash_stream_respects_max_bytes() -> None:
    stream = io.BytesIO(b"abcdef")
    with pytest.raises(ValueError):
        hash_stream(stream, max_bytes=3)
