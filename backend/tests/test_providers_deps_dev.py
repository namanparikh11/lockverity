"""Tests for the deps.dev enrichment provider."""

from __future__ import annotations

import json
from typing import Any

from app.providers.cache import ProviderCache
from app.providers.deps_dev import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_NODES,
    DEFAULT_MAX_REQUESTS,
    DepsDevEnrichmentProvider,
)
from app.providers.http_client import HttpResponse
from app.providers.results import (
    ProviderPartialResult,
    ProviderSuccess,
    ProviderUnavailable,
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
) -> tuple[DepsDevEnrichmentProvider, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def _request(method: str, url: str, body_bytes: bytes, headers):
        calls.append({"method": method, "url": url})
        return _http_response(status_code, body)

    provider = DepsDevEnrichmentProvider()
    provider._request = _request  # type: ignore[attr-defined]
    return provider, calls


def test_enrich_uses_known_endpoint() -> None:
    provider, calls = _provider_with_response(read_fixture_json("providers/deps_dev_success.json"))
    result = provider.enrich(ecosystem="npm", package_name="lodash", version="4.17.21")
    assert isinstance(result, ProviderSuccess)
    assert calls[0]["url"] == (
        "https://api.deps.dev/v3/systems/npm/packages/lodash/versions/4.17.21"
    )
    assert calls[0]["method"] == "GET"


def test_enrich_returns_licence_assertion() -> None:
    provider, _ = _provider_with_response(read_fixture_json("providers/deps_dev_success.json"))
    result = provider.enrich(ecosystem="npm", package_name="lodash", version="4.17.21")
    assert isinstance(result, ProviderSuccess)
    assert result.data["licenses"] == ["MIT"]


def test_enrich_handles_multiple_licences() -> None:
    provider, _ = _provider_with_response(
        read_fixture_json("providers/deps_dev_multiple_licences.json")
    )
    result = provider.enrich(ecosystem="npm", package_name="lodash", version="4.17.21")
    assert isinstance(result, ProviderSuccess)
    assert set(result.data["licenses"]) == {"MIT", "CC0-1.0"}


def test_enrich_handles_no_licence() -> None:
    provider, _ = _provider_with_response(
        read_fixture_json("providers/deps_dev_no_licence.json")
    )
    result = provider.enrich(ecosystem="npm", package_name="internal-pkg", version="1.0.0")
    assert isinstance(result, ProviderSuccess)
    assert result.data["licenses"] == []


def test_enrich_404_returns_unavailable() -> None:
    provider, _ = _provider_with_response({}, status_code=404)
    result = provider.enrich(ecosystem="npm", package_name="missing", version="1.0.0")
    assert isinstance(result, ProviderUnavailable)
    assert result.http_status == 404


def test_enrich_5xx_returns_unavailable() -> None:
    provider, _ = _provider_with_response({}, status_code=500)
    result = provider.enrich(ecosystem="npm", package_name="x", version="1.0.0")
    assert isinstance(result, ProviderUnavailable)


def test_enrich_invalid_json_returns_unavailable() -> None:
    provider, _ = _provider_with_response(b"not-json")
    result = provider.enrich(ecosystem="npm", package_name="x", version="1.0.0")
    assert isinstance(result, ProviderUnavailable)


def test_enrich_requires_version() -> None:
    provider, _ = _provider_with_response({})
    result = provider.enrich(ecosystem="npm", package_name="x", version=None)
    assert isinstance(result, ProviderUnavailable)


def test_enrich_uses_cache() -> None:
    cache = ProviderCache()
    call_count = [0]

    def _request(method, url, body, headers):
        call_count[0] += 1
        return _http_response(200, read_fixture_json("providers/deps_dev_success.json"))

    provider = DepsDevEnrichmentProvider(cache=cache)
    provider._request = _request  # type: ignore[attr-defined]
    provider.enrich(ecosystem="npm", package_name="lodash", version="4.17.21")
    provider.enrich(ecosystem="npm", package_name="lodash", version="4.17.21")
    assert call_count[0] == 1


def test_enrich_with_tree_returns_bounded_graph() -> None:
    responses = [
        _http_response(200, read_fixture_json("providers/deps_dev_success.json")),
    ]
    call_count = [0]

    def _request(method, url, body, headers):
        call_count[0] += 1
        return responses[0]

    provider = DepsDevEnrichmentProvider(max_depth=1, max_nodes=10, max_requests=3)
    provider._request = _request  # type: ignore[attr-defined]
    result = provider.enrich_with_tree(
        ecosystem="npm", package_name="lodash", version="4.17.21"
    )
    # No children in the fixture, so the tree contains only the
    # root node and the result is a ProviderSuccess.
    assert isinstance(result, ProviderSuccess)
    assert result.data["nodes"][0]["name"] == "lodash"


def test_enrich_with_tree_detects_truncation() -> None:
    # Build a synthetic graph that forces truncation at the
    # request cap. The first call returns a node with one
    # child; subsequent calls return a different child each
    # time so the BFS keeps discovering new nodes until the
    # request cap is hit.
    state = {"call": 0}

    def _request(method, url, body, headers):
        state["call"] += 1
        child_name = f"child-{state['call']}"
        payload = {
            "name": "x",
            "version": "1.0.0",
            "licenses": [],
            "dependencies": [{"name": child_name, "version": "1.0.0"}],
        }
        return _http_response(200, payload)

    provider = DepsDevEnrichmentProvider(max_depth=4, max_nodes=100, max_requests=1)
    provider._request = _request  # type: ignore[attr-defined]
    result = provider.enrich_with_tree(
        ecosystem="npm", package_name="root", version="1.0.0"
    )
    assert isinstance(result, ProviderPartialResult)
    assert "max_requests_reached" in result.error_summary


def test_enrich_does_not_replace_lockfile_evidence() -> None:
    """deps.dev enrichment is metadata; the lockfile is authoritative."""
    provider, _ = _provider_with_response(read_fixture_json("providers/deps_dev_success.json"))
    result = provider.enrich(ecosystem="npm", package_name="lodash", version="4.17.21")
    assert isinstance(result, ProviderSuccess)
    # The data shape carries a source_provenance marker; the
    # orchestrator (or the rule) is expected to read this and
    # not silently overwrite the lockfile's version.
    assert result.data.get("source_provenance") == "deps.dev"


def test_default_constants_documented() -> None:
    assert DEFAULT_MAX_DEPTH > 0
    assert DEFAULT_MAX_NODES > 0
    assert DEFAULT_MAX_REQUESTS > 0


def test_enrich_invalid_ecosystem_returns_unavailable() -> None:
    provider, _ = _provider_with_response({})
    result = provider.enrich(ecosystem="", package_name="x", version="1.0.0")
    assert isinstance(result, ProviderUnavailable)


def test_enrich_uses_deterministic_source_marker() -> None:
    provider, _ = _provider_with_response(read_fixture_json("providers/deps_dev_success.json"))
    result = provider.enrich(ecosystem="npm", package_name="lodash", version="4.17.21")
    assert isinstance(result, ProviderSuccess)
    assert result.data["source_provenance"] == "deps.dev"
