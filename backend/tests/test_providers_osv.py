"""Tests for the OSV vulnerability provider."""

from __future__ import annotations

from typing import Any

from app.providers.cache import ProviderCache
from app.providers.http_client import HttpResponse
from app.providers.osv import (
    OSV_BATCH_SIZE,
    OSV_QUERYBATCH_URL,
    OsvVulnerabilityProvider,
)
from app.providers.results import (
    ProviderOutcome,
    ProviderSuccess,
    ProviderUnavailable,
)
from app.utils.datetime import utcnow

from tests.fixtures import read_fixture_json


def _http_response(status_code: int, body: dict[str, Any]) -> HttpResponse:
    import json

    return HttpResponse(
        status_code=status_code,
        headers={"content-type": "application/json"},
        body=json.dumps(body).encode("utf-8"),
        elapsed_seconds=0.01,
        attempts=1,
    )


def _provider_with_response(body: dict[str, Any], *, status_code: int = 200) -> tuple[OsvVulnerabilityProvider, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def _request(method: str, url: str, body_bytes: bytes, headers):
        import json

        calls.append(
            {
                "method": method,
                "url": url,
                "body": json.loads(body_bytes) if body_bytes else None,
                "headers": dict(headers),
            }
        )
        return _http_response(status_code, body)

    provider = OsvVulnerabilityProvider(request_fn=_request)
    return provider, calls


def test_query_batch_calls_official_endpoint() -> None:
    provider, calls = _provider_with_response({"results": [{"vulns": []}]})
    result = provider.query_batch([("npm", "lodash", "4.17.21")])
    assert isinstance(result, ProviderSuccess)
    assert calls[0]["url"] == OSV_QUERYBATCH_URL
    assert calls[0]["method"] == "POST"


def test_query_batch_normalises_advisory() -> None:
    body = read_fixture_json("providers/osv_success.json")
    provider, _ = _provider_with_response(body)
    result = provider.query_batch([("npm", "lodash", "4.17.21")])
    assert isinstance(result, ProviderSuccess)
    assert result.records_returned == 1
    advisory = result.data[0]
    assert advisory["id"] == "OSV-2023-0001"
    assert "CVE-2023-0001" in advisory["aliases"]
    assert "OSV-2023-0002" in advisory["related"]
    assert advisory["severity"][0]["score"].startswith("CVSS:3.1/")
    assert advisory["affected"][0]["ranges"][0]["events"][1]["fixed"] == "4.17.22"
    # ``fixed_versions`` is extracted as a top-level convenience.
    assert advisory["fixed_versions"] == ["4.17.22"]


def test_query_batch_handles_empty_response() -> None:
    body = read_fixture_json("providers/osv_empty.json")
    provider, _ = _provider_with_response(body)
    result = provider.query_batch([("npm", "lodash", "4.17.21")])
    assert isinstance(result, ProviderSuccess)
    assert result.records_returned == 0
    assert result.data == []


def test_query_batch_handles_withdrawn_advisory() -> None:
    body = read_fixture_json("providers/osv_withdrawn.json")
    provider, _ = _provider_with_response(body)
    result = provider.query_batch([("npm", "left-pad", "1.3.0")])
    assert isinstance(result, ProviderSuccess)
    advisory = result.data[0]
    assert advisory["withdrawn"] is not None
    assert advisory["affected"][0]["ranges"][0]["events"][1]["fixed"] == "1.3.1"


def test_query_batch_handles_missing_severity() -> None:
    body = read_fixture_json("providers/osv_missing_severity.json")
    provider, _ = _provider_with_response(body)
    result = provider.query_batch([("npm", "lodash", "4.17.21")])
    assert isinstance(result, ProviderSuccess)
    advisory = result.data[0]
    assert advisory["severity"] == []


def test_query_batch_handles_aliases() -> None:
    body = read_fixture_json("providers/osv_aliases.json")
    provider, _ = _provider_with_response(body)
    result = provider.query_batch([("npm", "minimist", "1.2.5")])
    assert isinstance(result, ProviderSuccess)
    advisory = result.data[0]
    assert set(advisory["aliases"]) == {
        "CVE-2022-0001",
        "GHSA-aaaa-bbbb-cccc",
        "GHSA-dddd-eeee-ffff",
    }
    assert advisory["related"] == ["OSV-ALIAS-002"]


def test_query_batch_partial_response_with_no_fixed() -> None:
    body = read_fixture_json("providers/osv_partial.json")
    provider, _ = _provider_with_response(body)
    result = provider.query_batch([("npm", "minimist", "1.2.5")])
    assert isinstance(result, ProviderSuccess)
    advisory = result.data[0]
    events = advisory["affected"][0]["ranges"][0]["events"]
    assert events == [{"introduced": "0"}]


def test_query_batch_returns_unavailable_on_http_error() -> None:
    provider, _ = _provider_with_response({}, status_code=500)
    result = provider.query_batch([("npm", "lodash", "4.17.21")])
    assert isinstance(result, ProviderUnavailable)
    assert result.http_status == 500
    assert result.outcome == ProviderOutcome.UNAVAILABLE


def test_query_batch_returns_unavailable_on_invalid_json() -> None:
    def _request(method, url, body, headers):
        return HttpResponse(
            status_code=200,
            headers={},
            body=b"not json",
            elapsed_seconds=0.01,
            attempts=1,
        )

    provider = OsvVulnerabilityProvider(request_fn=_request)
    result = provider.query_batch([("npm", "lodash", "4.17.21")])
    assert isinstance(result, ProviderUnavailable)


def test_query_batch_chunks_at_one_thousand() -> None:
    calls: list[dict[str, Any]] = []

    def _request(method, url, body, headers):
        import json

        body_obj = json.loads(body)
        calls.append({"n_queries": len(body_obj.get("queries", []))})
        return _http_response(200, {"results": [{"vulns": []}] * len(body_obj["queries"])})

    provider = OsvVulnerabilityProvider(request_fn=_request, batch_size=10)
    items = [("npm", f"pkg-{i}", "1.0.0") for i in range(25)]
    result = provider.query_batch(items)
    assert isinstance(result, ProviderSuccess)
    assert len(calls) == 3
    assert calls[0]["n_queries"] == 10
    assert calls[1]["n_queries"] == 10
    assert calls[2]["n_queries"] == 5


def test_query_batch_constant_documented() -> None:
    assert OSV_BATCH_SIZE == 1000


def test_query_uses_cache() -> None:
    cache = ProviderCache()
    call_count = [0]

    def _request(method, url, body, headers):

        call_count[0] += 1
        return _http_response(200, {"results": [{"vulns": []}]})

    provider = OsvVulnerabilityProvider(cache=cache, request_fn=_request)
    provider.query(ecosystem="npm", package_name="lodash", version="4.17.21")
    provider.query(ecosystem="npm", package_name="lodash", version="4.17.21")
    assert call_count[0] == 1


def test_query_returns_unavailable_on_5xx() -> None:
    provider, _ = _provider_with_response({}, status_code=503)
    result = provider.query(ecosystem="npm", package_name="x", version="1.0.0")
    assert isinstance(result, ProviderUnavailable)


def test_does_not_represent_unavailable_as_no_vulnerabilities() -> None:
    provider, _ = _provider_with_response({}, status_code=502)
    result = provider.query(ecosystem="npm", package_name="x", version="1.0.0")
    # The provider never returns a ProviderSuccess for a failure.
    assert isinstance(result, ProviderUnavailable)


def test_query_batch_empty_input_returns_success() -> None:
    provider, _ = _provider_with_response({})
    result = provider.query_batch([])
    assert isinstance(result, ProviderSuccess)
    assert result.records_returned == 0
    assert result.data == []


def test_query_batch_now_marker() -> None:
    before = utcnow()
    provider, _ = _provider_with_response({"results": [{"vulns": []}]})
    result = provider.query_batch([("npm", "lodash", "4.17.21")])
    after = utcnow()
    assert isinstance(result, ProviderSuccess)
    assert before <= result.fetched_at <= after
