"""Tests for :mod:`app.utils.finding_keys`."""

from __future__ import annotations

import pytest
from app.utils.finding_keys import (
    normalize_evidence,
    stable_evidence_blob,
    stable_finding_key,
)


def test_stable_finding_key_is_deterministic() -> None:
    evidence = {"path": "src/x.py", "line": 12, "rule_args": ["a", "b"]}
    a = stable_finding_key("R001", evidence)
    b = stable_finding_key("R001", evidence)
    assert a == b
    assert len(a) == 64


def test_stable_finding_key_ignores_dict_order() -> None:
    a = stable_finding_key("R001", {"x": 1, "y": 2})
    b = stable_finding_key("R001", {"y": 2, "x": 1})
    assert a == b


def test_stable_finding_key_differs_by_rule() -> None:
    evidence = {"x": 1}
    assert stable_finding_key("R001", evidence) != stable_finding_key("R002", evidence)


def test_stable_finding_key_differs_by_evidence() -> None:
    a = stable_finding_key("R001", {"x": 1})
    b = stable_finding_key("R001", {"x": 2})
    assert a != b


def test_stable_finding_key_preserves_list_order() -> None:
    a = stable_finding_key("R001", {"list": [1, 2, 3]})
    b = stable_finding_key("R001", {"list": [3, 2, 1]})
    assert a != b


def test_stable_finding_key_normalizes_bytes() -> None:
    a = stable_finding_key("R001", {"digest": b"abc"})
    b = stable_finding_key("R001", {"digest": b"abc"})
    c = stable_finding_key("R001", {"digest": b"abd"})
    assert a == b
    assert a != c


def test_stable_finding_key_rejects_empty_rule_id() -> None:
    with pytest.raises(ValueError):
        stable_finding_key("", {"x": 1})


def test_normalize_evidence_handles_arbitrary_types() -> None:
    out = normalize_evidence({"obj": object()})
    assert "_repr" in out["obj"]


def test_stable_evidence_blob_is_bounded_json() -> None:
    blob = stable_evidence_blob({"a": 1, "b": [1, 2, 3]})
    assert blob.startswith("{")
    assert blob.endswith("}")
