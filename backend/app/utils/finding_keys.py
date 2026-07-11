"""Deterministic finding key generation.

A finding's ``stable_key`` must be identical across reruns of the same
scan, so that two scans of the same commit do not surface the same
finding twice. The key is the SHA-256 hex digest of a canonical JSON
serialization of the evidence the finding is based on.

Evidence normalization is the contract. If you change how a piece of
evidence is normalized, you change the stable key, which means reruns
will not deduplicate against prior scans. That's the whole point - the
stable key is only as good as the evidence contract behind it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.utils.json_safe import dump_bounded_json


def normalize_evidence(evidence: Any) -> Any:
    """Return a JSON-serializable, order-independent copy of ``evidence``.

    - dicts are sorted by key
    - lists are preserved in order (they often encode step order)
    - ``None``, ``bool``, ``int``, ``float``, and ``str`` are preserved
    - bytes are encoded as their hex digest (so we never carry the raw
      bytes through a stable key)
    - everything else is stringified with ``repr`` for transparency
    """
    if evidence is None or isinstance(evidence, (bool, int, float, str)):
        return evidence
    if isinstance(evidence, dict):
        return {str(k): normalize_evidence(v) for k, v in sorted(evidence.items())}
    if isinstance(evidence, list):
        return [normalize_evidence(v) for v in evidence]
    if isinstance(evidence, tuple):
        return [normalize_evidence(v) for v in evidence]
    if isinstance(evidence, (bytes, bytearray)):
        return {"_bytes_sha256": hashlib.sha256(bytes(evidence)).hexdigest()}
    return {"_repr": repr(evidence)}


def stable_finding_key(rule_id: str, evidence: Any) -> str:
    """Return the deterministic stable key for a finding.

    The key includes the rule id and the normalized evidence. The
    result is a 64-character hex SHA-256 digest.
    """
    if not isinstance(rule_id, str) or not rule_id:
        raise ValueError("rule_id must be a non-empty string.")
    payload = {
        "rule_id": rule_id,
        "evidence": normalize_evidence(evidence),
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def stable_evidence_blob(evidence: Any) -> str:
    """Return a bounded JSON serialization of the evidence for storage.

    Uses :func:`lockverity.utils.json_safe.dump_bounded_json` so we
    never persist an evidence blob that exceeds the per-field bound.
    """
    return dump_bounded_json(normalize_evidence(evidence))
