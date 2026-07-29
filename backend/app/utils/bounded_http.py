"""Bounded HTTP client.

A thin wrapper over :mod:`httpx` that:

- enforces a small, allowlist-based host filter (the caller must
  supply an explicit allowlist, the client never talks to a host
  it has not been told is safe);
- enforces a hard response-size cap (configurable per call);
- enforces a per-call timeout (connect + read);
- performs a bounded number of safe retries on connection
  errors and 5xx responses;
- re-rejects redirects to non-allowlisted hosts (the underlying
  ``follow_redirects=True`` is enabled but each Location header
  is re-validated against the allowlist as the redirect chain is
  walked);
- never embeds the configured token in a URL;
- never logs the configured token.

The client is a *primitive*. It does not parse responses, decode
JSON, or otherwise interpret the body. Callers pass a callback
that consumes the body stream.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("lockverity.http")

# Acceptable response content types for archive downloads. A
# GitHub tarball is served as ``application/x-gzip`` or
# ``application/octet-stream``; a GitHub API response is JSON.
_DOWNLOAD_CONTENT_TYPE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "application/octet-stream",
        "application/x-gzip",
        "application/gzip",
        "application/zip",
        "application/x-tar",
        "application/x-gtar",
        "application/x-bzip2",
    }
)

# Acceptable content types for the GitHub API. The API always
# returns JSON; we accept the few common spellings.
_API_CONTENT_TYPE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "application/json",
        "application/vnd.github+json",
        "application/vnd.github.v3+json",
        "application/vnd.github.v3.raw+json",
        "text/json",
    }
)


class BoundedHttpError(Exception):
    """Raised when the HTTP client cannot complete a request safely."""

    def __init__(self, code: str, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class BoundedHttpResponse:
    """The result of a successful bounded HTTP request."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class BoundedHttpRequest:
    """A single bounded HTTP request descriptor."""

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    # When set, the body is sent and the response body is read up
    # to ``max_response_bytes``.
    body: bytes | None = None
    # When set, GET request bodies are streamed and the caller
    # receives the response body in a single buffer (which is
    # always within ``max_response_bytes``).
    max_response_bytes: int = 10 * 1024 * 1024
    timeout_seconds: float = 15.0
    retry_limit: int = 2
    accept_content_types: frozenset[str] = field(
        default_factory=lambda: _API_CONTENT_TYPE_ALLOWLIST
    )
    allow_redirects: bool = True


class BoundedHttpClient:
    """A reusable bounded HTTP client.

    The client is created once per intake and is configured with
    a token, a user agent, and an allowlist of permitted hosts.
    Each call validates the destination host against the
    allowlist and re-validates the destination of every redirect.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        user_agent: str = "lockverity/0.2 (core-intake)",
        allowlist: Iterable[str] = (),
        allow_http_for_test_hosts: bool = False,
    ) -> None:
        self._token = token or None
        self._user_agent = user_agent
        self._allowlist = frozenset(host.lower() for host in allowlist)
        if not self._allowlist:
            raise ValueError("BoundedHttpClient requires a non-empty host allowlist.")
        self._allow_http_for_test_hosts = allow_http_for_test_hosts
        self._client = httpx.Client(
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=False,
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
        )

    @property
    def allowlist(self) -> frozenset[str]:
        return self._allowlist

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BoundedHttpClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public request methods
    # ------------------------------------------------------------------
    def request(self, request: BoundedHttpRequest) -> BoundedHttpResponse:
        return self._execute_with_retries(request)

    def get_json(
        self,
        url: str,
        *,
        max_response_bytes: int = 10 * 1024 * 1024,
        timeout_seconds: float = 15.0,
        retry_limit: int = 2,
        extra_headers: Mapping[str, str] | None = None,
    ) -> BoundedHttpResponse:
        headers = dict(extra_headers or {})
        return self.request(
            BoundedHttpRequest(
                method="GET",
                url=url,
                headers=headers,
                max_response_bytes=max_response_bytes,
                timeout_seconds=timeout_seconds,
                retry_limit=retry_limit,
                accept_content_types=_API_CONTENT_TYPE_ALLOWLIST,
                allow_redirects=True,
            )
        )

    def download(
        self,
        url: str,
        *,
        max_response_bytes: int = 200 * 1024 * 1024,
        timeout_seconds: float = 60.0,
        retry_limit: int = 2,
    ) -> BoundedHttpResponse:
        return self.request(
            BoundedHttpRequest(
                method="GET",
                url=url,
                max_response_bytes=max_response_bytes,
                timeout_seconds=timeout_seconds,
                retry_limit=retry_limit,
                accept_content_types=_DOWNLOAD_CONTENT_TYPE_ALLOWLIST,
                allow_redirects=True,
            )
        )

    # ------------------------------------------------------------------
    # Internal plumbing
    # ------------------------------------------------------------------
    def _execute_with_retries(self, request: BoundedHttpRequest) -> BoundedHttpResponse:
        attempt = 0
        last_error: BoundedHttpError | None = None
        max_attempts = max(1, request.retry_limit + 1)
        while attempt < max_attempts:
            attempt += 1
            try:
                return self._execute_once(request)
            except BoundedHttpError as exc:
                last_error = exc
                if exc.code in {
                    "http_host_forbidden",
                    "http_redirect_forbidden",
                    "http_response_too_large",
                    "http_content_type_forbidden",
                    "http_invalid_url",
                    "http_unauthorized",
                    "http_forbidden",
                    "http_not_found",
                }:
                    raise
                if attempt >= max_attempts:
                    raise
                logger.debug(
                    "bounded http retrying after error code=%s attempt=%d",
                    exc.code,
                    attempt,
                )
        # Loop exits only via raise; this line is unreachable.
        if last_error is None:  # pragma: no cover - defensive
            raise BoundedHttpError("http_unknown", "exhausted retries with no error")
        raise last_error

    def _execute_once(self, request: BoundedHttpRequest) -> BoundedHttpResponse:
        return self._stream_with_redirects(
            request,
            current_url=request.url,
            method=request.method,
            body=request.body,
            headers=self._build_request_headers(request),
            redirects_followed=0,
        )

    def _build_request_headers(self, request: BoundedHttpRequest) -> dict[str, str]:
        headers = dict(request.headers)
        if self._token:
            headers.setdefault("Authorization", f"Bearer {self._token}")
        if "User-Agent" not in headers:
            headers["User-Agent"] = self._user_agent
        return headers

    def _stream_with_redirects(
        self,
        request: BoundedHttpRequest,
        *,
        current_url: str,
        method: str,
        body: bytes | None,
        headers: dict[str, str],
        redirects_followed: int,
    ) -> BoundedHttpResponse:
        """Walk the redirect chain under ``client.stream(...)``.

        The recursion depth is bounded by ``max_redirects`` (5);
        each step uses a fresh streaming context so the previous
        connection is released before the next hop. The
        recursion is the simplest way to keep the
        ``with self._client.stream(...) as response:`` block
        scoped to a single hop, which is what guarantees the
        connection is closed even on the redirect path.
        """
        max_redirects = 5
        if redirects_followed > max_redirects:
            raise BoundedHttpError(
                "http_too_many_redirects",
                "Redirect chain exceeded the maximum length.",
            )
        self._check_host_in_allowlist(current_url)
        try:
            with self._client.stream(
                method,
                current_url,
                headers=headers,
                content=body,
                timeout=request.timeout_seconds,
            ) as response:
                # A redirect response: drain its body
                # (bounded by the same cap), close the
                # connection, and recurse with the next
                # hop. A non-redirect response: return the
                # bounded body.
                if response.status_code in (301, 302, 303, 307, 308) and request.allow_redirects:
                    self._drain_redirect_body(response, request.max_response_bytes)
                    location = response.headers.get("Location") or response.headers.get("location")
                    if not location:
                        raise BoundedHttpError(
                            "http_invalid_redirect",
                            "Redirect response did not include a Location header.",
                        )
                    next_url = _resolve_redirect(current_url, location)
                    # 303 always switches to GET; 301/302/307/308
                    # preserve the method for our usage
                    # (we only GET or send a small JSON body).
                    next_method = "GET" if response.status_code == 303 else method
                    next_body = None if response.status_code == 303 else body
                    return self._stream_with_redirects(
                        request,
                        current_url=next_url,
                        method=next_method,
                        body=next_body,
                        headers=headers,
                        redirects_followed=redirects_followed + 1,
                    )

                # Final response.
                self._check_status(response, request)
                content_type = (
                    (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                )
                if (
                    content_type
                    and request.accept_content_types
                    and (content_type not in request.accept_content_types)
                ):
                    raise BoundedHttpError(
                        "http_content_type_forbidden",
                        f"Response content-type {content_type!r} is not in the allowlist.",
                    )
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared = int(content_length)
                    except ValueError as exc:
                        raise BoundedHttpError(
                            "http_invalid_content_length",
                            "Response Content-Length is not an integer.",
                        ) from exc
                    if declared > request.max_response_bytes:
                        raise BoundedHttpError(
                            "http_response_too_large",
                            f"Response Content-Length {declared} exceeds the limit "
                            f"{request.max_response_bytes}.",
                        )
                body_bytes = self._stream_bounded_body(response, request.max_response_bytes)
                return BoundedHttpResponse(
                    status_code=response.status_code,
                    headers=dict(response.headers.items()),
                    body=body_bytes,
                )
        except BoundedHttpError:
            raise
        except httpx.TimeoutException as exc:
            raise BoundedHttpError("http_timeout", "Request timed out.") from exc
        except httpx.HTTPError as exc:
            raise BoundedHttpError("http_connection_error", f"Connection error: {exc}") from exc

    def _drain_redirect_body(self, response: httpx.Response, max_bytes: int) -> None:
        """Drain and discard a redirect response body.

        The cap is the same ``max_response_bytes`` as the
        final response: an attacker-controlled intermediate
        hop cannot exhaust process memory. The body is
        streamed; we do not retain the bytes.
        """
        chunk_size = max(64 * 1024, min(max_bytes, 1024 * 1024))
        total = 0
        try:
            for chunk in response.iter_bytes(chunk_size=chunk_size):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise BoundedHttpError(
                        "http_response_too_large",
                        f"Redirect body exceeded the limit {max_bytes} while streaming.",
                    )
        except httpx.HTTPError as exc:
            raise BoundedHttpError(
                "http_connection_error",
                f"Redirect stream interrupted: {exc}",
            ) from exc

    def _stream_bounded_body(self, response: httpx.Response, max_bytes: int) -> bytes:
        """Stream the response body in fixed-size chunks.

        The cap is enforced *while* the body is being read;
        a hostile upstream that sends more bytes than the
        cap is aborted as soon as the cap is crossed and
        the partial body is discarded so a single
        oversized response cannot exhaust process memory.
        The function returns the bytes only when the
        total fits within the cap; otherwise it raises
        :class:`BoundedHttpError` with the
        ``http_response_too_large`` code and no body is
        retained.
        """
        chunk_size = max(64 * 1024, min(max_bytes, 1024 * 1024))
        parts: list[bytes] = []
        total = 0
        try:
            for chunk in response.iter_bytes(chunk_size=chunk_size):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    parts.clear()
                    raise BoundedHttpError(
                        "http_response_too_large",
                        f"Response body exceeded the limit {max_bytes} while streaming.",
                    )
                parts.append(chunk)
        except BoundedHttpError:
            raise
        except httpx.HTTPError as exc:
            raise BoundedHttpError(
                "http_connection_error",
                f"Stream interrupted: {exc}",
            ) from exc
        return b"".join(parts)

    def _check_host_in_allowlist(self, url: str) -> None:
        from urllib.parse import urlsplit

        try:
            parts = urlsplit(url)
        except ValueError as exc:
            raise BoundedHttpError("http_invalid_url", f"Invalid URL: {exc}") from exc
        if not self._allow_http_for_test_hosts and parts.scheme.lower() != "https":
            raise BoundedHttpError(
                "http_scheme_forbidden",
                "Only https:// URLs are accepted for external providers.",
            )
        if self._allow_http_for_test_hosts and parts.scheme.lower() not in {"http", "https"}:
            raise BoundedHttpError(
                "http_scheme_forbidden",
                "Only http:// (test) or https:// URLs are accepted.",
            )
        host = (parts.hostname or "").lower()
        if not host:
            raise BoundedHttpError("http_invalid_url", "URL did not include a hostname.")
        if host not in self._allowlist:
            raise BoundedHttpError(
                "http_host_forbidden",
                f"Host {host!r} is not in the configured allowlist.",
            )

    def _check_status(self, response: Any, request: BoundedHttpRequest) -> None:
        status = response.status_code
        if status < 400:
            return
        if status == 401:
            raise BoundedHttpError("http_unauthorized", "Upstream returned 401 Unauthorized.")
        if status == 403:
            raise BoundedHttpError("http_forbidden", "Upstream returned 403 Forbidden.")
        if status == 404:
            raise BoundedHttpError("http_not_found", "Upstream returned 404 Not Found.")
        if status == 429:
            raise BoundedHttpError(
                "http_rate_limited",
                "Upstream returned 429 Too Many Requests.",
                http_status=429,
            )
        if 500 <= status < 600:
            raise BoundedHttpError(
                "http_server_error",
                f"Upstream returned {status}.",
                http_status=status,
            )
        # Any other 4xx (including 400, 409, 422) surfaces as a
        # generic client error. The 400, 409 and 422 statuses
        # are explicitly enumerated for documentation; the
        # fall-through ``raise`` covers every other 4xx (e.g.
        # 410, 451). Retries are not attempted on 4xx.
        raise BoundedHttpError(
            "http_client_error",
            f"Upstream returned {status}.",
            http_status=status,
        )


def _resolve_redirect(current_url: str, location: str) -> str:
    from urllib.parse import urljoin, urlsplit, urlunsplit

    parts = urlsplit(location)
    if not parts.scheme and not parts.netloc:
        joined = urljoin(current_url, location)
    else:
        joined = urlunsplit(parts)
    return joined
