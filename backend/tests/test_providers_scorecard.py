"""Tests for the OpenSSF Scorecard importer."""

from __future__ import annotations

import json
from typing import Any

from app.providers.cache import ProviderCache
from app.providers.http_client import HttpResponse
from app.providers.results import (
    ProviderSuccess,
    ProviderUnavailable,
)
from app.providers.scorecard import (
    SCORECARD_BASE,
    ScorecardImporter,
    missing_check_names,
    scorecard_check_names,
)

from tests.fixtures import read_fixture_json


def _http_response(status_code: int, body: dict[str, Any] | bytes) -> HttpResponse:
    if isinstance(body, dict):
        body = json.dumps(body).encode("utf-8")
    return HttpResponse(
        status_code=status_code,
        headers={"content-type": "application/json"},
        body=body,
        elapsed_seconds=0.01,
        attempts=1,
    )


def _provider_with_response(
    body: dict[str, Any] | bytes,
    *,
    status_code: int = 200,
) -> tuple[ScorecardImporter, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def _request(method: str, url: str, body_bytes: bytes, headers):
        calls.append({"method": method, "url": url})
        return _http_response(status_code, body)

    provider = ScorecardImporter()
    provider._request = _request  # type: ignore[attr-defined]
    return provider, calls


def test_read_uses_known_endpoint() -> None:
    provider, calls = _provider_with_response(read_fixture_json("providers/scorecard_success.json"))
    result = provider.read("https://github.com/octocat/Hello-World")
    assert isinstance(result, ProviderSuccess)
    assert calls[0]["url"] == f"{SCORECARD_BASE}/projects/github.com/octocat/Hello-World"
    assert calls[0]["method"] == "GET"


def test_read_preserves_check_names_and_scores() -> None:
    provider, _ = _provider_with_response(read_fixture_json("providers/scorecard_success.json"))
    result = provider.read("https://github.com/octocat/Hello-World")
    assert isinstance(result, ProviderSuccess)
    check_names = {c["name"] for c in result.data["checks"]}
    assert "Code-Review" in check_names
    assert "Pinned-Dependencies" in check_names
    code_review = next(c for c in result.data["checks"] if c["name"] == "Code-Review")
    assert code_review["score"] == 9
    assert "reviewed" in code_review["reason"]


def test_read_preserves_evidence() -> None:
    provider, _ = _provider_with_response(read_fixture_json("providers/scorecard_success.json"))
    result = provider.read("https://github.com/octocat/Hello-World")
    assert isinstance(result, ProviderSuccess)
    pinned = next(c for c in result.data["checks"] if c["name"] == "Pinned-Dependencies")
    assert "https://example.com/dependabot.yml" in pinned["evidence"]


def test_read_preserves_source_timestamp() -> None:
    provider, _ = _provider_with_response(read_fixture_json("providers/scorecard_success.json"))
    result = provider.read("https://github.com/octocat/Hello-World")
    assert isinstance(result, ProviderSuccess)
    code_review = next(c for c in result.data["checks"] if c["name"] == "Code-Review")
    assert code_review["source_timestamp"] == "2024-01-15T00:00:00Z"


def test_read_404_returns_unavailable() -> None:
    provider, _ = _provider_with_response({}, status_code=404)
    result = provider.read("https://github.com/octocat/Hello-World")
    assert isinstance(result, ProviderUnavailable)
    assert result.http_status == 404


def test_read_5xx_returns_unavailable() -> None:
    provider, _ = _provider_with_response({}, status_code=503)
    result = provider.read("https://github.com/octocat/Hello-World")
    assert isinstance(result, ProviderUnavailable)


def test_read_invalid_json_returns_unavailable() -> None:
    provider, _ = _provider_with_response(b"not-json")
    result = provider.read("https://github.com/octocat/Hello-World")
    assert isinstance(result, ProviderUnavailable)


def test_read_invalid_canonical_returns_unavailable() -> None:
    provider, _ = _provider_with_response({})
    result = provider.read("not-a-url")
    assert isinstance(result, ProviderUnavailable)


def test_read_uses_cache() -> None:
    cache = ProviderCache()
    call_count = [0]

    def _request(method, url, body, headers):
        call_count[0] += 1
        return _http_response(200, read_fixture_json("providers/scorecard_success.json"))

    provider = ScorecardImporter(cache=cache)
    provider._request = _request  # type: ignore[attr-defined]
    provider.read("https://github.com/octocat/Hello-World")
    provider.read("https://github.com/octocat/Hello-World")
    assert call_count[0] == 1


def test_scorecard_check_names_constant() -> None:
    names = scorecard_check_names()
    assert "Code-Review" in names
    assert "Pinned-Dependencies" in names
    assert "Dangerous-Workflow" in names


def test_missing_check_names_helper() -> None:
    payload = read_fixture_json("providers/scorecard_success.json")
    missing = missing_check_names(payload)
    # The fixture has Code-Review, Pinned-Dependencies, Dangerous-Workflow
    # so a non-empty set of canonical checks is missing.
    assert "Binary-Artifacts" in missing
    assert "Branch-Protection" in missing


def test_missing_does_not_count_missing_results_as_zero() -> None:
    """Missing checks are surfaced explicitly, not silently as zero."""
    payload = {
        "score": 0,
        "checks": [],
    }
    missing = missing_check_names(payload)
    # All canonical checks are missing.
    assert len(missing) == len(scorecard_check_names())


def test_does_not_run_scorecard_binary() -> None:
    """The provider never invokes a subprocess.

    This test does not actually exercise a binary call; it
    documents the contract: the importer only consumes JSON.
    """
    provider, _ = _provider_with_response(read_fixture_json("providers/scorecard_success.json"))
    result = provider.read("https://github.com/octocat/Hello-World")
    assert isinstance(result, ProviderSuccess)
    # The data shape carries a source provenance marker so the
    # UI can surface "imported result" rather than "computed here".
    assert result.data.get("source_provenance") == "openssf_scorecard"
