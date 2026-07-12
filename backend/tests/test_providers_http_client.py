"""Tests for the bounded HTTP client."""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from typing import Any

import pytest
from app.providers.http_client import (
    DEFAULT_MAX_RESPONSE_BYTES,
    HttpClientError,
    HttpRequestLimits,
    HttpResponse,
    HttpResponseTooLargeError,
    HttpUrlError,
    get_bytes,
    get_http_client,
    install_http_client,
    post_json,
    reset_http_client_for_tests,
    validate_url,
)


class _StubClient:
    def __init__(self, responses: Iterable[Mapping[str, Any]] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "content": content,
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise RuntimeError("No stub response queued.")
        return self.responses.pop(0)


class _StubResponse:
    def __init__(
        self,
        *,
        status_code: int,
        body: bytes,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = dict(headers or {})

    def read(self) -> bytes:
        return self._body


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    install_http_client(None)
    yield
    install_http_client(None)


def test_validate_url_accepts_https() -> None:
    assert validate_url("https://example.com/path") == "https://example.com/path"


def test_validate_url_accepts_http() -> None:
    assert validate_url("http://example.com/path") == "http://example.com/path"


def test_validate_url_rejects_ftp() -> None:
    with pytest.raises(HttpUrlError):
        validate_url("ftp://example.com")


def test_validate_url_rejects_empty() -> None:
    with pytest.raises(HttpUrlError):
        validate_url("")


def test_validate_url_rejects_non_string() -> None:
    with pytest.raises(HttpUrlError):
        validate_url(123)  # type: ignore[arg-type]


def test_post_json_with_stub() -> None:
    stub = _StubClient(
        [
            _StubResponse(status_code=200, body=b'{"results": []}', headers={"content-type": "application/json"}),
        ]
    )
    install_http_client(stub)
    response = post_json("https://api.example/v1/query", {"queries": []})
    assert response.status_code == 200
    assert response.body == b'{"results": []}'
    assert stub.calls[0]["method"] == "POST"
    assert stub.calls[0]["content"] is not None


def test_get_bytes_with_stub() -> None:
    stub = _StubClient(
        [_StubResponse(status_code=200, body=b"hello", headers={"content-type": "text/plain"})]
    )
    install_http_client(stub)
    response = get_bytes("https://api.example/v1/foo")
    assert response.status_code == 200
    assert response.body == b"hello"


def test_retry_on_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    # First two calls return 503, third returns 200.
    responses = [
        _StubResponse(status_code=503, body=b"", headers={"Retry-After": "0"}),
        _StubResponse(status_code=503, body=b"", headers={"Retry-After": "0"}),
        _StubResponse(status_code=200, body=b"ok"),
    ]
    stub = _StubClient(responses)
    install_http_client(stub)
    # Skip the actual sleep.
    monkeypatch.setattr(time, "sleep", lambda _: None)
    response = get_bytes("https://api.example/v1/foo", limits=HttpRequestLimits(retry_limit=2))
    assert response.status_code == 200
    assert stub.calls and len(stub.calls) == 3


def test_retry_limit_exhausted() -> None:
    responses = [
        _StubResponse(status_code=503, body=b"", headers={}),
        _StubResponse(status_code=503, body=b"", headers={}),
        _StubResponse(status_code=503, body=b"", headers={}),
    ]
    stub = _StubClient(responses)
    install_http_client(stub)
    with pytest.raises(HttpClientError):
        get_bytes("https://api.example/v1/foo", limits=HttpRequestLimits(retry_limit=2))


def test_response_too_large_raises() -> None:
    big = b"x" * (DEFAULT_MAX_RESPONSE_BYTES + 1)
    stub = _StubClient([_StubResponse(status_code=200, body=big)])
    install_http_client(stub)
    with pytest.raises(HttpResponseTooLargeError):
        get_bytes("https://api.example/v1/foo")


def test_redacted_headers_strip_sensitive() -> None:
    response = HttpResponse(
        status_code=200,
        headers={"Authorization": "Bearer abc", "Content-Type": "application/json"},
        body=b"{}",
        elapsed_seconds=0.01,
        attempts=1,
    )
    safe = response.redacted_headers()
    assert "Authorization" not in safe
    assert safe.get("Content-Type") == "application/json"


def test_redacted_body_summary_truncates() -> None:
    body = b"x" * 1000
    response = HttpResponse(
        status_code=200,
        headers={},
        body=body,
        elapsed_seconds=0.01,
        attempts=1,
    )
    summary = response.redacted_body_summary()
    assert len(summary) <= 500


def test_reset_for_tests() -> None:
    reset_http_client_for_tests()
    client = get_http_client()
    assert client is not None


def test_url_rejected_after_install() -> None:
    install_http_client(_StubClient())
    with pytest.raises(HttpUrlError):
        get_bytes("ftp://example.com")
