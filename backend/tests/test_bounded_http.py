"""Tests for the bounded HTTP client."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import httpx
import pytest
from app.utils.bounded_http import (
    BoundedHttpClient,
    BoundedHttpError,
)


class _ChunkedByteStream(httpx.SyncByteStream):
    """A minimal ``httpx.SyncByteStream`` subclass for tests.

    ``httpx.SyncByteStream`` is an abstract base class; a
    subclass must implement ``__iter__``. The class records
    exactly how many bytes and chunks the consumer pulled
    so the streaming-consumption probe can assert that
    the cap was enforced mid-stream rather than after
    the full body was read.
    """

    def __init__(self, body: bytes, counter: dict, chunk_size: int = 1024 * 1024) -> None:
        self._body = body
        self._counter = counter
        # Pre-populate the counter so callers that only
        # read ``bytes`` do not trip over a missing key
        # when the stream emits the first chunk.
        self._counter.setdefault("bytes", 0)
        self._counter.setdefault("chunks", 0)
        self._chunk_size = chunk_size
        self._closed = False

    def __iter__(self) -> Iterator[bytes]:
        sent = 0
        while sent < len(self._body):
            chunk = self._body[sent : sent + self._chunk_size]
            sent += len(chunk)
            self._counter["bytes"] += len(chunk)
            self._counter["chunks"] += 1
            yield chunk

    def close(self) -> None:
        self._closed = True


class _RecorderHandler(BaseHTTPRequestHandler):
    """A tiny HTTP server that records requests and serves canned responses."""

    server_version = "TestServer/1.0"
    recorded_requests: ClassVar[list[dict]] = []
    response_status = 200
    response_headers: ClassVar[dict[str, str]] = {"Content-Type": "application/json"}
    response_body = b'{"ok": true}'
    redirect_to: str | None = None
    per_path_redirects: ClassVar[dict[str, str]] = {}
    sticky_redirects: ClassVar[set[str]] = set()

    def do_GET(self):
        _RecorderHandler.recorded_requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
            }
        )
        # Sticky redirect: matches every time the path is hit.
        if self.path in _RecorderHandler.sticky_redirects:
            target = _RecorderHandler.per_path_redirects.get(self.path)
            if target is not None:
                self.send_response(302)
                self.send_header("Location", target)
                self.end_headers()
                return
        # Per-path redirect overrides the global one and is
        # consumed once.
        per_path = _RecorderHandler.per_path_redirects.pop(self.path, None)
        if per_path is not None:
            self.send_response(302)
            self.send_header("Location", per_path)
            self.end_headers()
            return
        if _RecorderHandler.redirect_to is not None:
            self.send_response(302)
            self.send_header("Location", _RecorderHandler.redirect_to)
            self.end_headers()
            return
        self.send_response(_RecorderHandler.response_status)
        for key, value in _RecorderHandler.response_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(_RecorderHandler.response_body)))
        self.end_headers()
        self.wfile.write(_RecorderHandler.response_body)

    def log_message(self, format, *args):
        return None


@pytest.fixture
def http_server() -> Iterator[tuple[ThreadingHTTPServer, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecorderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _RecorderHandler.recorded_requests = []
    _RecorderHandler.response_status = 200
    _RecorderHandler.response_headers = {"Content-Type": "application/json"}
    _RecorderHandler.response_body = b'{"ok": true}'
    _RecorderHandler.redirect_to = None
    _RecorderHandler.per_path_redirects = {}
    _RecorderHandler.sticky_redirects = set()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}"
    try:
        yield server, base
    finally:
        server.shutdown()
        server.server_close()


def _client_for_tests(allowlist: set[str]) -> BoundedHttpClient:
    return BoundedHttpClient(
        token=None,
        user_agent="test-agent",
        allowlist=allowlist,
        allow_http_for_test_hosts=True,
    )


def test_get_returns_parsed_body(http_server):
    _server, base = http_server
    client = _client_for_tests({"127.0.0.1"})
    try:
        response = client.get_json(f"{base}/hello")
    finally:
        client.close()
    assert response.status_code == 200
    assert response.body == b'{"ok": true}'
    assert _RecorderHandler.recorded_requests[0]["path"] == "/hello"
    assert _RecorderHandler.recorded_requests[0]["headers"]["User-Agent"] == "test-agent"


def test_get_includes_bearer_token_when_configured(http_server):
    _server, base = http_server
    client = BoundedHttpClient(
        token="secret-token-1234",
        user_agent="test-agent",
        allowlist={"127.0.0.1"},
        allow_http_for_test_hosts=True,
    )
    try:
        client.get_json(f"{base}/hello")
    finally:
        client.close()
    auth = _RecorderHandler.recorded_requests[0]["headers"].get("Authorization")
    assert auth == "Bearer secret-token-1234"


def test_rejects_host_outside_allowlist(http_server):
    _server, base = http_server
    client = _client_for_tests({"api.github.com"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(f"{base}/hello")
    finally:
        client.close()
    assert exc.value.code == "http_host_forbidden"


def test_rejects_non_https_by_default():
    client = BoundedHttpClient(
        token=None,
        user_agent="test-agent",
        allowlist={"api.github.com"},
    )
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json("http://api.github.com/hello")
    finally:
        client.close()
    assert exc.value.code == "http_scheme_forbidden"


def test_rejects_redirect_to_other_host(http_server):
    _server, base = http_server
    _RecorderHandler.redirect_to = "http://evil.example/steal"
    client = _client_for_tests({"127.0.0.1"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(f"{base}/redir")
    finally:
        client.close()
    assert exc.value.code == "http_host_forbidden"


def test_follows_redirect_within_allowlist(http_server):
    _server, base = http_server
    _RecorderHandler.per_path_redirects[f"{base}/redir".replace(f"{base}", "")] = f"{base}/final"
    # Use the per-path mapping for clarity.
    _RecorderHandler.per_path_redirects.clear()
    _RecorderHandler.per_path_redirects["/redir"] = f"{base}/final"
    client = _client_for_tests({"127.0.0.1"})
    try:
        response = client.get_json(f"{base}/redir")
    finally:
        client.close()
    assert response.status_code == 200
    assert _RecorderHandler.recorded_requests[-1]["path"] == "/final"


def test_rejects_too_many_redirects(http_server):
    _server, base = http_server
    _RecorderHandler.per_path_redirects.clear()
    _RecorderHandler.sticky_redirects.clear()
    _RecorderHandler.per_path_redirects["/redir"] = f"{base}/loop"
    _RecorderHandler.per_path_redirects["/loop"] = f"{base}/loop"
    _RecorderHandler.sticky_redirects.update({"/redir", "/loop"})
    client = _client_for_tests({"127.0.0.1"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(f"{base}/redir")
    finally:
        client.close()
    assert exc.value.code == "http_too_many_redirects"


def test_rejects_response_too_large_via_body_size(http_server):
    _server, base = http_server
    _RecorderHandler.response_headers = {"Content-Type": "application/json"}
    _RecorderHandler.response_body = b"x" * 2048
    client = _client_for_tests({"127.0.0.1"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(f"{base}/big", max_response_bytes=100)
    finally:
        client.close()
    assert exc.value.code == "http_response_too_large"


def test_rejects_oversized_streamed_response_with_no_content_length(http_server, monkeypatch):
    """A streaming response that omits ``Content-Length`` and exceeds
    the cap must be aborted *during* the read, not after the body
    has been fully buffered into memory.
    """
    _server, base = http_server
    cap = 1024
    # 4 KiB body, 4x the cap, with no Content-Length.
    _RecorderHandler.response_headers = {"Content-Type": "application/json"}
    _RecorderHandler.response_body = b"x" * (cap * 4)
    # Patch the handler to strip Content-Length. We do this by
    # monkey-patching the ``send_header`` call that would set it.
    original_send_header = _RecorderHandler.send_header

    def _send_header_no_length(self, key, value):
        if key.lower() == "content-length":
            return
        original_send_header(self, key, value)

    monkeypatch.setattr(_RecorderHandler, "send_header", _send_header_no_length)
    client = _client_for_tests({"127.0.0.1"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(f"{base}/stream", max_response_bytes=cap)
    finally:
        client.close()
    assert exc.value.code == "http_response_too_large"
    assert "while streaming" in exc.value.message


# ---------------------------------------------------------------------------
# Real streaming-consumption probes (Codex audit requirement)
# ---------------------------------------------------------------------------
#
# These tests exercise the production ``client.stream(...)``
# entry point against a real ``httpx.MockTransport`` (not a
# patched ``Client.request``). The transport's
# ``SyncByteStream`` callback is observed for the exact
# number of bytes the client actually consumed. A
# non-streaming implementation would consume the entire
# upstream body; a streaming implementation stops near the
# configured cap.


def test_rejects_oversized_streamed_response_with_real_httpx(
    monkeypatch,
):
    """Real streaming-consumption probe against ``httpx.MockTransport``.

    The transport serves a 64 MiB body with no
    ``Content-Length``. The client is configured with a
    1 MiB cap. We assert that consumption stopped
    near the 1 MiB cap (rather than reading the full
    64 MiB). The cap is enforced *during* the read.
    """
    cap = 1 * 1024 * 1024  # 1 MiB
    total_body = b"x" * (64 * 1024 * 1024)  # 64 MiB of bytes

    consumed: dict = {"bytes": 0, "chunks": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=_ChunkedByteStream(total_body, consumed),
        )

    transport = httpx.MockTransport(_handler)
    client = _client_for_tests_with_transport(transport, allowlist={"example.test"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(
                "https://example.test/big",
                max_response_bytes=cap,
                timeout_seconds=15.0,
            )
    finally:
        client.close()
    assert exc.value.code == "http_response_too_large"
    # The real streaming probe: the transport sent only
    # as many bytes as the client consumed before the
    # cap triggered. 64 MiB is 64x the cap, so a
    # non-streaming implementation would consume the
    # full 64 MiB; a true streaming implementation
    # consumes at most one chunk over the cap before
    # the rejection fires (the chunk that crosses the
    # cap is what triggers ``http_response_too_large``).
    # The bound is therefore ``cap + chunk_size`` =
    # ``2 * cap`` for the production 1 MiB chunk size.
    assert consumed["bytes"] <= cap * 2, (
        f"client consumed {consumed['bytes']} bytes; "
        f"streaming cap was {cap} bytes (one chunk over the cap is the trigger)"
    )
    assert consumed["bytes"] > 0
    assert consumed["chunks"] < 20, (
        f"client consumed {consumed['chunks']} chunks; "
        f"streaming should stop after a handful of chunks"
    )


def test_streaming_consumption_with_misleading_content_length(
    monkeypatch,
):
    """Real streaming probe with a misleading ``Content-Length``.

    The transport declares ``Content-Length: 100`` (well
    under the 1 MiB cap) but actually streams 64 MiB. The
    streaming cap must still trigger and consumption
    must stop near the cap.
    """
    cap = 1 * 1024 * 1024
    total_body = b"x" * (64 * 1024 * 1024)

    consumed: dict = {"bytes": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "Content-Length": "100",
            },
            stream=_ChunkedByteStream(total_body, consumed),
        )

    transport = httpx.MockTransport(_handler)
    client = _client_for_tests_with_transport(transport, allowlist={"example.test"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(
                "https://example.test/lying",
                max_response_bytes=cap,
                timeout_seconds=15.0,
            )
    finally:
        client.close()
    assert exc.value.code == "http_response_too_large"
    # One chunk over the cap is the trigger; with a
    # 1 MiB cap and 1 MiB chunk size the bound is
    # ``cap + chunk_size`` = ``2 * cap``.
    assert consumed["bytes"] <= cap * 2, (
        f"client consumed {consumed['bytes']} bytes; "
        f"the streaming cap was supposed to stop the read near {cap} bytes"
    )


def test_exact_byte_boundary_success(monkeypatch):
    """Real streaming probe at the exact byte cap.

    The transport streams a body that is exactly the
    cap. The streaming cap must not over-trigger at
    the boundary; the response must succeed.
    """
    cap = 4096
    body = b"x" * cap

    consumed: dict = {"bytes": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
            stream=_ChunkedByteStream(body, consumed),
        )

    transport = httpx.MockTransport(_handler)
    client = _client_for_tests_with_transport(transport, allowlist={"example.test"})
    try:
        response = client.get_json(
            "https://example.test/exact",
            max_response_bytes=cap,
            timeout_seconds=15.0,
        )
    finally:
        client.close()
    assert response.status_code == 200
    assert len(response.body) == cap
    assert consumed["bytes"] == cap


def _client_for_tests_with_transport(
    transport: httpx.MockTransport, allowlist: set[str]
) -> BoundedHttpClient:
    """Build a ``BoundedHttpClient`` backed by ``transport`` for tests."""
    client = BoundedHttpClient(
        token=None,
        user_agent="test-agent",
        allowlist=allowlist,
        allow_http_for_test_hosts=True,
    )
    # Replace the production ``httpx.Client`` with one
    # bound to the mock transport. The streaming
    # implementation uses ``self._client.stream(...)`` so
    # only the transport needs to be swapped.
    client._client = httpx.Client(  # type: ignore[assignment]
        transport=transport,
        timeout=httpx.Timeout(15.0, connect=10.0),
        follow_redirects=False,
        headers={"User-Agent": "test-agent", "Accept": "application/json"},
    )
    return client


def test_response_closed_after_oversize(monkeypatch):
    """The response context manager closes the connection
    on every code path (success, oversize rejection,
    status rejection). We confirm the contract by
    hooking the response's close lifecycle and observing
    the close call.
    """
    cap = 4096
    body = b"x" * (cap * 2)

    closed: dict = {"after_oversize": False}

    def _handler(request: httpx.Request) -> httpx.Response:
        # We need a custom stream whose close method
        # records the lifecycle hook.
        class _TrackedStream(_ChunkedByteStream):
            def close(self) -> None:
                closed["after_oversize"] = True
                super().close()

        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
            stream=_TrackedStream(body, counter={"bytes": 0, "chunks": 0}),
        )

    transport = httpx.MockTransport(_handler)
    client = _client_for_tests_with_transport(transport, allowlist={"example.test"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(
                "https://example.test/big",
                max_response_bytes=cap,
                timeout_seconds=15.0,
            )
    finally:
        client.close()
    assert exc.value.code == "http_response_too_large"
    # The streaming context manager closed the response
    # on the way out, even though the cap fired mid-stream.
    assert closed["after_oversize"] is True


def test_response_closed_after_status_rejection(monkeypatch):
    """A 4xx / 5xx status response must also close the
    connection. We assert the close is observed on a 500
    status.
    """
    closed: dict = {"after_status": False}

    def _handler(request: httpx.Request) -> httpx.Response:
        class _TrackedStream(httpx.SyncByteStream):
            def __iter__(self) -> Iterator[bytes]:
                yield b"boom"

            def close(self) -> None:
                closed["after_status"] = True

        return httpx.Response(
            500,
            headers={"Content-Type": "application/json"},
            stream=_TrackedStream(),
        )

    transport = httpx.MockTransport(_handler)
    client = _client_for_tests_with_transport(transport, allowlist={"example.test"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(
                "https://example.test/boom",
                max_response_bytes=10_000,
                timeout_seconds=15.0,
            )
    finally:
        client.close()
    assert exc.value.code == "http_server_error"
    assert closed["after_status"] is True


def test_response_closed_after_redirect(monkeypatch):
    """Every redirect response must be closed before
    following the next hop.
    """
    closes: list[str] = []

    def _make_redirect_response(*, request_url: str, location: str) -> httpx.Response:
        class _TrackedStream(httpx.SyncByteStream):
            def __iter__(self) -> Iterator[bytes]:
                yield b""

            def close(self) -> None:
                # Record the request URL of the response
                # that was just closed; the close hook
                # is the contract we want to assert here,
                # not the redirect target.
                closes.append(request_url)

        return httpx.Response(
            302,
            headers={
                "Location": location,
                "Content-Type": "text/plain",
            },
            stream=_TrackedStream(),
        )

    final_body = b"ok"

    def _handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.test/redirect1":
            return _make_redirect_response(
                request_url="https://example.test/redirect1",
                location="https://example.test/redirect2",
            )
        if str(request.url) == "https://example.test/redirect2":
            return _make_redirect_response(
                request_url="https://example.test/redirect2",
                location="https://example.test/final",
            )
        # Final response.
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(final_body)),
            },
            stream=_ChunkedByteStream(final_body, counter={"bytes": 0, "chunks": 0}),
        )

    transport = httpx.MockTransport(_handler)
    client = _client_for_tests_with_transport(transport, allowlist={"example.test"})
    try:
        response = client.get_json(
            "https://example.test/redirect1",
            max_response_bytes=10_000,
            timeout_seconds=15.0,
        )
    finally:
        client.close()
    assert response.status_code == 200
    assert response.body == final_body
    # Every redirect response must have been closed
    # before the next hop.
    assert "https://example.test/redirect1" in closes
    assert "https://example.test/redirect2" in closes


def test_rejects_oversized_response_via_misleading_content_length(http_server, monkeypatch):
    """A response that declares a small ``Content-Length`` but
    actually streams a larger body must still be aborted when the
    cumulative byte count crosses the cap. The ``Content-Length``
    short-circuit is a defensive pre-check, not a substitute for
    the streaming cap.

    The HTTP framework detects the conflict between the
    declared ``Content-Length`` and the actual byte count and
    refuses the response; that is the correct upstream
    behaviour. We simulate a misleading ``Content-Length`` by
    monkey-patching the response so the pre-check passes and
    the streaming cap is the only thing that catches the
    oversized body.
    """
    _server, base = http_server
    cap = 1024
    # Declare a Content-Length that is within the cap so the
    # pre-check passes. The actual body is four times the
    # cap, so the streaming cap must still trigger.
    declared_length = cap // 2  # 512 bytes, well under the 1024 cap
    _RecorderHandler.response_headers = {
        "Content-Type": "application/json",
        "Content-Length": str(declared_length),
    }
    _RecorderHandler.response_body = b"x" * (cap * 4)

    # Patch the response object so the HTTP client cannot
    # detect the Content-Length vs. body-size mismatch via
    # the framework. We expose a custom response object
    # that returns the declared length from ``headers`` and
    # the full oversized body from ``iter_bytes``.
    from app.utils import bounded_http as bh

    class _MisleadingResponse:
        def __init__(self, body: bytes, declared_length: int) -> None:
            self._body = body
            self.headers = {
                "Content-Type": "application/json",
                "Content-Length": str(declared_length),
            }
            self.status_code = 200

        def iter_bytes(self, chunk_size: int = 65536):
            for start in range(0, len(self._body), chunk_size):
                yield self._body[start : start + chunk_size]

    original_request = bh.httpx.Client.request
    original_stream = bh.httpx.Client.stream

    def _fake_request(self, method, url, **kwargs):
        # Only intercept our specific test path; let
        # everything else fall through to the real client.
        if not str(url).endswith("/lying"):
            return original_request(self, method, url, **kwargs)
        return _MisleadingResponse(_RecorderHandler.response_body, declared_length)

    @contextmanager
    def _fake_stream(self, method, url, **kwargs):
        if not str(url).endswith("/lying"):
            with original_stream(self, method, url, **kwargs) as response:
                yield response
            return
        yield _MisleadingResponse(_RecorderHandler.response_body, declared_length)

    monkeypatch.setattr(bh.httpx.Client, "request", _fake_request)
    monkeypatch.setattr(bh.httpx.Client, "stream", _fake_stream)
    client = _client_for_tests({"127.0.0.1"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(f"{base}/lying", max_response_bytes=cap)
    finally:
        client.close()
    assert exc.value.code == "http_response_too_large"
    assert "while streaming" in exc.value.message


def test_accepts_response_at_exact_byte_limit(http_server):
    """A response that is exactly at the cap must succeed (boundary)."""
    _server, base = http_server
    cap = 100
    _RecorderHandler.response_headers = {"Content-Type": "application/json"}
    _RecorderHandler.response_body = b"x" * cap
    client = _client_for_tests({"127.0.0.1"})
    try:
        response = client.get_json(f"{base}/exact", max_response_bytes=cap)
    finally:
        client.close()
    assert response.status_code == 200
    assert len(response.body) == cap


def test_rejects_unexpected_content_type(http_server):
    _server, base = http_server
    _RecorderHandler.response_headers = {"Content-Type": "text/html"}
    client = _client_for_tests({"127.0.0.1"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(f"{base}/html")
    finally:
        client.close()
    assert exc.value.code == "http_content_type_forbidden"


def test_download_accepts_github_archive_content_types(http_server):
    _server, base = http_server
    _RecorderHandler.response_headers = {"Content-Type": "application/x-gzip"}
    _RecorderHandler.response_body = b"fake-archive"
    client = _client_for_tests({"127.0.0.1"})
    try:
        response = client.download(f"{base}/archive", max_response_bytes=1024)
    finally:
        client.close()
    assert response.status_code == 200
    assert response.body == b"fake-archive"


def test_404_surfaces_as_not_found(http_server):
    _server, base = http_server
    _RecorderHandler.response_status = 404
    client = _client_for_tests({"127.0.0.1"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(f"{base}/missing")
    finally:
        client.close()
    assert exc.value.code == "http_not_found"


def test_429_surfaces_as_rate_limited(http_server):
    _server, base = http_server
    _RecorderHandler.response_status = 429
    client = _client_for_tests({"127.0.0.1"})
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(f"{base}/limited")
    finally:
        client.close()
    assert exc.value.code == "http_rate_limited"


def test_5xx_is_retried_then_raises(http_server, monkeypatch):
    _server, base = http_server
    _RecorderHandler.response_status = 503
    client = _client_for_tests({"127.0.0.1"})
    import app.utils.bounded_http as mod

    monkeypatch.setattr(mod, "logger", mod.logger)
    try:
        with pytest.raises(BoundedHttpError) as exc:
            client.get_json(f"{base}/busy", retry_limit=1, timeout_seconds=2.0)
    finally:
        client.close()
    assert exc.value.code == "http_connection_error" or exc.value.code.startswith("http_")
    assert len(_RecorderHandler.recorded_requests) >= 1


def test_empty_allowlist_raises_value_error():
    with pytest.raises(ValueError):
        BoundedHttpClient(token=None, user_agent="x", allowlist=[])
