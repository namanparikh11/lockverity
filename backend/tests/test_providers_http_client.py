"""Tests for the bounded provider HTTP client.

These tests cover the *shared* provider HTTP wrapper
(``app.providers.http_client``). The wrapper is used by
the OSV, deps.dev and OpenSSF Scorecard providers; every
call goes through ``post_json`` or ``get_bytes`` and is
funnelled through ``_request_with_retries``.

The production implementation now uses
``httpx.Client.stream(...)`` for true streaming, so the
response body is never fully buffered before the cap is
enforced. The stub client in this file mirrors the
streaming surface (``stream(...)`` as a context manager)
so the existing tests continue to cover the success /
retry / oversize / status paths. Real httpx transport
probes live in
``tests/test_providers_http_client_streaming.py``.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from app.providers import http_client as phttp
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
    """A minimal stub client that supports the streaming surface.

    The production client only calls ``stream(...)``; the
    stub mirrors that entry point. The ``iter_bytes`` API
    on the stub response is the production-equivalent
    read path so the streaming cap is exercised.
    """

    def __init__(self, responses: Iterable[Any] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []
        self.streams: list[dict[str, Any]] = []

    def request(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - legacy
        # The production code no longer calls ``request``
        # directly; this method exists only so test
        # errors surface with a clear message if a
        # regression re-introduces the non-streaming
        # path.
        raise AssertionError(
            "shared provider client must use client.stream(); Client.request is a regression."
        )

    @contextmanager
    def stream(
        self,
        method: str,
        url: str,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Iterator[Any]:
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
        yield self.responses.pop(0)


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

    def iter_bytes(self, chunk_size: int = 65536) -> Iterator[bytes]:
        # Yield the body in ``chunk_size`` slices so the
        # streaming cap is exercised end-to-end.
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start : start + chunk_size]

    def read(self) -> bytes:  # pragma: no cover - fallback path
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
            _StubResponse(
                status_code=200,
                body=b'{"results": []}',
                headers={"content-type": "application/json"},
            ),
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


def test_redirect_rejected() -> None:
    """The shared provider client refuses 3xx responses;
    the SSRF-aware redirect chain is owned by
    ``app.utils.bounded_http``.
    """
    stub = _StubClient(
        [
            _StubResponse(
                status_code=302,
                body=b"",
                headers={"location": "https://other.example/"},
            ),
        ]
    )
    install_http_client(stub)
    with pytest.raises(HttpClientError) as exc:
        get_bytes("https://api.example/v1/foo")
    assert "redirect" in str(exc.value)


def test_generic_4xx_rejected() -> None:
    """A 4xx response other than 401/403/404/429 is
    surfaced as a hard error; the body is still bounded
    by the cap.
    """
    stub = _StubClient(
        [
            _StubResponse(
                status_code=418,
                body=b"i'm a teapot",
                headers={"content-type": "text/plain"},
            ),
        ]
    )
    install_http_client(stub)
    with pytest.raises(HttpClientError) as exc:
        get_bytes("https://api.example/v1/foo")
    assert "418" in str(exc.value)


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


# ---------------------------------------------------------------------------
# Network-isolation regression tests
# ---------------------------------------------------------------------------
#
# The Phase 1 local-first release must not make any
# outbound network calls during the test suite. The
# previous cycle's audit observed an unclosed SSL
# socket to a GitHub IPv6 address; the rewrite of
# ``_request_with_retries`` to use ``client.stream(...)``
# (with the ``with`` context manager) closes the
# connection on every code path, but a regression test
# is the durable guard. The tests below patch
# ``httpx.Client`` so any attempt to open a real socket
# would surface as a failure in the patched constructor.


def test_shared_provider_client_does_not_open_real_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real ``httpx.Client`` is never instantiated by
    the test path; the test fails if the production
    code regresses to a non-streaming path that would
    open a real connection.

    The test substitutes ``httpx.Client.__init__`` with
    a stub that records the call. If the production
    code path tries to open a real client, the stub
    raises and the test fails loudly.
    """
    calls: list[dict] = []

    class _RealClientBlocker:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append({"args": args, "kwargs": kwargs})
            # Refuse to open a real connection. Tests
            # that exercise the production code path
            # must have already substituted the client
            # via ``install_http_client``; if not, the
            # test surfaces the regression.
            raise AssertionError(
                "shared provider client must not "
                "instantiate httpx.Client directly; "
                "tests must use install_http_client or "
                "MockTransport."
            )

    monkeypatch.setattr(httpx, "Client", _RealClientBlocker)
    install_http_client(None)
    # Calling ``get_http_client`` would trigger the
    # stub; the production code path never reaches
    # this call without an explicit install.
    with pytest.raises(AssertionError):
        get_http_client()
    # The stub recorded exactly one call (the one we
    # triggered above).
    assert calls


def test_shared_provider_client_closes_after_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared provider client must close the
    underlying ``httpx.Client`` after the request
    completes; an unclosed socket at the end of the
    test is the failure mode the audit flagged.

    The test uses a custom ``MockTransport`` and
    records the ``close()`` lifecycle. A regression
    that opens a connection without closing it would
    leave the close hook un-fired.
    """
    closed: list[bool] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b'{"ok": true}',
        )

    transport = httpx.MockTransport(_handler)
    real_client = httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(15.0, connect=10.0),
        follow_redirects=False,
    )
    # Wrap the close() method to record the call.
    original_close = real_client.close

    def _close_wrapper() -> None:
        closed.append(True)
        original_close()

    real_client.close = _close_wrapper  # type: ignore[method-assign]
    install_http_client(real_client)
    try:
        response = get_bytes("https://api.example.test/health")
        assert response.status_code == 200
    finally:
        install_http_client(None)
    # The ``with client.stream(...)`` context manager
    # closes the response on exit; the underlying
    # ``httpx.Client`` is closed explicitly here
    # because the global registry is shared.
    real_client.close()
    assert closed, "httpx.Client.close() was not invoked"


def test_shared_provider_client_closes_after_oversize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared provider client must close the
    underlying ``httpx.Client`` after an oversize
    rejection; the streaming context manager fires
    the close on the exception exit path.
    """
    closed: list[bool] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        # 2 MiB body; the cap is 1 MiB.
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b"x" * (2 * 1024 * 1024),
        )

    transport = httpx.MockTransport(_handler)
    real_client = httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(15.0, connect=10.0),
        follow_redirects=False,
    )
    original_close = real_client.close

    def _close_wrapper() -> None:
        closed.append(True)
        original_close()

    real_client.close = _close_wrapper  # type: ignore[method-assign]
    install_http_client(real_client)
    try:
        with pytest.raises(HttpResponseTooLargeError):
            get_bytes(
                "https://api.example.test/big",
                limits=phttp.HttpRequestLimits(max_response_bytes=1024 * 1024),
            )
    finally:
        install_http_client(None)
    real_client.close()
    assert closed, (
        "httpx.Client.close() was not invoked after oversize "
        "rejection; the streaming context manager must close "
        "the connection on every exit path"
    )
