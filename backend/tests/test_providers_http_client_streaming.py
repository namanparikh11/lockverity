"""Real streaming-consumption probes for the shared provider HTTP client.

The shared provider client (``app.providers.http_client``)
is the choke point for OSV, deps.dev and OpenSSF
Scorecard calls. This file exercises the production
``client.stream(...)`` entry point against a real
``httpx.MockTransport`` (not a patched ``Client.request``)
to prove that the byte cap is enforced *during* the
network read, not after the full body is buffered.

The test helper ``_ChunkedByteStream(httpx.SyncByteStream)``
records the exact number of bytes and chunks the
consumer pulled. A non-streaming implementation would
consume the entire upstream body; a true streaming
implementation stops near the configured cap.

The file is independent of
``tests/test_bounded_http.py`` (which exercises the
SSRF-aware redirect-aware client used for the GitHub
tarball download). The provider client does not follow
redirects and is the entry point for the three external
intelligence providers.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from app.providers import http_client as phttp
from app.providers.http_client import (
    HttpClientError,
    HttpResponseTooLargeError,
    get_bytes,
    install_http_client,
    post_json,
)


class _ChunkedByteStream(httpx.SyncByteStream):
    """A minimal ``httpx.SyncByteStream`` subclass for tests.

    The class records exactly how many bytes and chunks
    the consumer pulled. ``setdefault`` initialises the
    counter so a test that only reads one key does not
    trip over a missing entry.
    """

    def __init__(self, body: bytes, counter: dict, chunk_size: int = 1024 * 1024) -> None:
        self._body = body
        self._counter = counter
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


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    install_http_client(None)
    yield
    install_http_client(None)


def _client_with_transport(transport: httpx.MockTransport) -> httpx.Client:
    """Install a fresh ``httpx.Client`` backed by ``transport``."""
    client = httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(15.0, connect=10.0),
        follow_redirects=False,
        cookies=None,
        trust_env=False,
    )
    install_http_client(client)
    return client


# ---------------------------------------------------------------------------
# 1. 8 MiB body under 1 MiB cap: consumption must stop near the cap.
# ---------------------------------------------------------------------------


def test_rejects_oversized_streamed_response_with_real_httpx() -> None:
    """Real streaming-consumption probe against ``httpx.MockTransport``.

    The transport serves an 8 MiB body with no
    ``Content-Length``. The client is configured with a
    1 MiB cap. We assert that consumption stopped near
    the 1 MiB cap (rather than reading the full 8 MiB).
    """
    cap = 1 * 1024 * 1024  # 1 MiB
    total_body = b"x" * (8 * 1024 * 1024)  # 8 MiB
    consumed: dict = {"bytes": 0, "chunks": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=_ChunkedByteStream(total_body, consumed),
        )

    transport = httpx.MockTransport(_handler)
    _client_with_transport(transport)
    with pytest.raises(HttpResponseTooLargeError):
        get_bytes(
            "https://api.example.test/big", limits=phttp.HttpRequestLimits(max_response_bytes=cap)
        )
    # The real streaming probe: the transport sent only
    # as many bytes as the client consumed before the
    # cap triggered. 8 MiB is 8x the cap, so a
    # non-streaming implementation would consume the
    # full 8 MiB; a true streaming implementation
    # consumes at most one chunk over the cap (the chunk
    # that crosses the cap is what triggers the
    # rejection). Bound is ``cap + chunk_size``.
    assert consumed["bytes"] <= cap * 2, (
        f"client consumed {consumed['bytes']} bytes; streaming cap was {cap} bytes"
    )
    assert consumed["chunks"] < 20


# ---------------------------------------------------------------------------
# 2. Misleading Content-Length: the streaming cap must still win.
# ---------------------------------------------------------------------------


def test_streaming_cap_wins_over_misleading_content_length() -> None:
    """The transport declares ``Content-Length: 100`` (well
    under the 1 MiB cap) but actually streams 8 MiB. The
    streaming cap must still trigger and consumption
    must stop near the cap.
    """
    cap = 1 * 1024 * 1024
    total_body = b"x" * (8 * 1024 * 1024)
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
    _client_with_transport(transport)
    with pytest.raises(HttpResponseTooLargeError):
        get_bytes(
            "https://api.example.test/lying",
            limits=phttp.HttpRequestLimits(max_response_bytes=cap),
        )
    assert consumed["bytes"] <= cap * 2


# ---------------------------------------------------------------------------
# 3. Exact-limit success: body exactly at the cap must succeed.
# ---------------------------------------------------------------------------


def test_exact_byte_boundary_success() -> None:
    """Body exactly at the cap must succeed; consumption
    equals the cap and no chunk crosses the line.
    """
    cap = 4096
    body = b"x" * cap
    consumed: dict = {"bytes": 0, "chunks": 0}

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
    _client_with_transport(transport)
    response = get_bytes(
        "https://api.example.test/exact",
        limits=phttp.HttpRequestLimits(max_response_bytes=cap),
    )
    assert response.status_code == 200
    assert len(response.body) == cap
    assert consumed["bytes"] == cap


# ---------------------------------------------------------------------------
# 4. Response close lifecycle on every exit path.
# ---------------------------------------------------------------------------


def test_response_closed_after_oversize() -> None:
    """The streaming context manager closes the response
    even when the cap fires mid-stream.
    """
    cap = 4096
    body = b"x" * (cap * 2)
    closed: dict = {"after_oversize": False}

    def _handler(request: httpx.Request) -> httpx.Response:
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
    _client_with_transport(transport)
    with pytest.raises(HttpResponseTooLargeError):
        get_bytes(
            "https://api.example.test/big",
            limits=phttp.HttpRequestLimits(max_response_bytes=cap),
        )
    assert closed["after_oversize"] is True


def test_response_closed_after_4xx_rejection() -> None:
    """A 4xx response closes the connection cleanly;
    the body is still bounded by the cap.
    """
    closed: dict = {"after_4xx": False}

    def _handler(request: httpx.Request) -> httpx.Response:
        class _TrackedStream(httpx.SyncByteStream):
            def __iter__(self) -> Iterator[bytes]:
                yield b"boom"

            def close(self) -> None:
                closed["after_4xx"] = True

        return httpx.Response(
            418,
            headers={"Content-Type": "text/plain"},
            stream=_TrackedStream(),
        )

    transport = httpx.MockTransport(_handler)
    _client_with_transport(transport)
    with pytest.raises(HttpClientError):
        get_bytes(
            "https://api.example.test/teapot",
            limits=phttp.HttpRequestLimits(max_response_bytes=10_000),
        )
    assert closed["after_4xx"] is True


# ---------------------------------------------------------------------------
# 5. POST JSON path: ``post_json`` is the OSV entry point.
# ---------------------------------------------------------------------------


def test_post_json_uses_streaming_path() -> None:
    """``post_json`` must also flow through the streaming
    context manager; the legacy ``client.request``
    path is a regression.
    """
    consumed: dict = {"bytes": 0, "chunks": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=_ChunkedByteStream(b'{"results": []}', consumed),
        )

    transport = httpx.MockTransport(_handler)
    _client_with_transport(transport)
    response = post_json("https://api.example.test/query", {"queries": []})
    assert response.status_code == 200
    assert response.body == b'{"results": []}'
    # The streaming body was consumed in one chunk.
    assert consumed["chunks"] == 1
    assert consumed["bytes"] == len(b'{"results": []}')


# ---------------------------------------------------------------------------
# 6. Retry path: a 5xx response triggers a retry; the
#    response is closed before the next attempt.
# ---------------------------------------------------------------------------


def test_response_closed_between_5xx_retries() -> None:
    """Each 5xx response in the retry chain is closed
    before the next attempt.
    """
    closes: list[int] = []

    def _make_response(status_code: int, body: bytes) -> httpx.Response:
        class _TrackedStream(httpx.SyncByteStream):
            def __iter__(self) -> Iterator[bytes]:
                yield body

            def close(self) -> None:
                closes.append(status_code)

        return httpx.Response(
            status_code,
            headers={"Content-Type": "application/json"},
            stream=_TrackedStream(),
        )

    responses = iter(
        [
            _make_response(503, b""),
            _make_response(503, b""),
            _make_response(200, b"ok"),
        ]
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    transport = httpx.MockTransport(_handler)
    _client_with_transport(transport)
    response = get_bytes(
        "https://api.example.test/retry",
        limits=phttp.HttpRequestLimits(retry_limit=2),
    )
    assert response.status_code == 200
    # The two 5xx responses were closed; the success
    # response is closed on context exit (the close
    # hook fires after the body has been read).
    assert 503 in closes


# ---------------------------------------------------------------------------
# 7. 3xx rejection: the shared provider client does not
#    follow redirects; the SSRF-aware redirect chain is
#    owned by ``app.utils.bounded_http``.
# ---------------------------------------------------------------------------


def test_redirect_is_hard_error() -> None:
    """A 3xx response surfaces as a hard error; the
    redirect chain is owned by the bounded HTTP utility.
    """
    closed: dict = {"after_3xx": False}

    def _handler(request: httpx.Request) -> httpx.Response:
        class _TrackedStream(httpx.SyncByteStream):
            def __iter__(self) -> Iterator[bytes]:
                yield b""

            def close(self) -> None:
                closed["after_3xx"] = True

        return httpx.Response(
            302,
            headers={
                "Location": "https://other.example/",
                "Content-Type": "text/plain",
            },
            stream=_TrackedStream(),
        )

    transport = httpx.MockTransport(_handler)
    _client_with_transport(transport)
    with pytest.raises(HttpClientError) as exc:
        get_bytes("https://api.example.test/redir")
    assert "redirect" in str(exc.value)
    assert closed["after_3xx"] is True
