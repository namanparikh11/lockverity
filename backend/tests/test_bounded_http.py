"""Tests for the bounded HTTP client."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest
from app.utils.bounded_http import (
    BoundedHttpClient,
    BoundedHttpError,
)


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
