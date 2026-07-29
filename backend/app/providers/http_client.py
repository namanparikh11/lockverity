"""HTTP client wrapper for outbound provider calls.

Lockverity is a *defensive* product. Every outbound HTTP call is
mediated by this module so a hostile or simply slow provider
cannot DoS the analyzer pipeline.

Guarantees:

- A bounded timeout per request (default 15s).
- A bounded response body size (default 10 MiB), enforced
  *during* the network read so a hostile upstream cannot
  exhaust process memory.
- Bounded retries with exponential backoff and Retry-After
  respect.
- Strict URL validation (only ``http://`` and ``https://``).
- Bounded request body size.
- Automatic redirect following is **off** at the
  ``httpx.Client`` level; the bounded HTTP utility
  (``app.utils.bounded_http``) is the SSRF-aware
  redirect-aware path. The shared provider client
  rejects 3xx responses explicitly so the operator
  never sees a silent ``Location`` follow.
- The streaming ``client.stream(...)`` context manager
  is used for every bounded response read; the response
  is closed on success, oversize, status rejection,
  HTTP error, and timeout paths.
- Headers and bodies are run through :mod:`app.utils.redaction`
  before being returned for diagnostic logging.

The module depends on :mod:`httpx` because the project already
pins it, but every other module imports through
:func:`get_http_client` so we can swap the transport in tests.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.utils.redaction import redact_headers, redact_provider_summary

DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MiB
DEFAULT_MAX_REQUEST_BYTES = 2 * 1024 * 1024  # 2 MiB
DEFAULT_RETRY_LIMIT = 2
DEFAULT_BACKOFF_BASE_SECONDS = 0.5
DEFAULT_BACKOFF_CAP_SECONDS = 8.0

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Status codes the wrapper retries on. A 3xx is not in this
# list: the shared provider client does not follow redirects
# (the SSRF-aware redirect chain is owned by
# ``app.utils.bounded_http``; the provider client is invoked
# only with allow-listed URLs).
_RETRY_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class HttpClientError(Exception):
    """Raised for any unrecoverable error in the HTTP wrapper."""


class HttpResponseTooLargeError(HttpClientError):
    """Raised when the response body exceeds the configured cap."""


class HttpUrlError(HttpClientError):
    """Raised for any URL that does not pass the safety checks."""


@dataclass(frozen=True, slots=True)
class HttpRequestLimits:
    """The safety limits applied to every request."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    retry_limit: int = DEFAULT_RETRY_LIMIT
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS
    backoff_cap_seconds: float = DEFAULT_BACKOFF_CAP_SECONDS


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """A successful HTTP response with redacted diagnostic fields."""

    status_code: int
    headers: dict[str, str]
    body: bytes
    elapsed_seconds: float
    attempts: int

    def redacted_headers(self) -> dict[str, str]:
        return redact_headers(self.headers)

    def redacted_body_summary(self) -> str:
        # We only return a short, redaction-safe summary of the body.
        # The full body is available on ``self.body``; this is for
        # logging only.
        text = self.body[:512].decode("utf-8", errors="replace")
        return redact_provider_summary(text, max_length=500) or ""


def validate_url(url: str) -> str:
    """Return ``url`` after validating the scheme and host shape.

    Raises :class:`HttpUrlError` for any URL that is not a clean
    ``http://`` or ``https://`` absolute URL with a host.
    """
    if not isinstance(url, str) or not url:
        raise HttpUrlError("URL must be a non-empty string.")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise HttpUrlError(f"Could not parse URL: {exc}") from exc
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise HttpUrlError(
            f"URL scheme {parts.scheme!r} is not allowed; only http and https are accepted."
        )
    if not parts.netloc:
        raise HttpUrlError("URL must include a host.")
    return url


def get_http_client() -> httpx.Client:
    """Return a process-wide :class:`httpx.Client` for outbound calls.

    The client uses HTTP/1.1 with connection pooling, no cookies,
    and no automatic redirects. Tests can call
    :func:`install_http_client` to substitute a mock.
    """
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(
            http2=False,
            follow_redirects=False,
            cookies=None,
            trust_env=False,
        )
    return _CLIENT


def install_http_client(client: httpx.Client | None) -> None:
    """Replace the process-wide client (used by tests).

    The previous client, if any, is closed before the
    substitution. ``httpx.Client.close()`` releases the
    underlying connection pool, which prevents an
    ``ResourceWarning`` for an unclosed SSL socket in
    long-running test suites.
    """
    global _CLIENT
    previous = _CLIENT
    _CLIENT = client
    if previous is not None and previous is not client:
        with contextlib.suppress(Exception):
            previous.close()


_CLIENT: httpx.Client | None = None


def reset_http_client_for_tests() -> None:
    install_http_client(None)


def post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    limits: HttpRequestLimits | None = None,
    headers: Mapping[str, str] | None = None,
) -> HttpResponse:
    """POST ``payload`` (JSON) to ``url`` with bounded retries."""
    serialized = _serialize_json(payload, limits=limits)
    return _request_with_retries(
        "POST",
        url,
        body=serialized,
        headers={"content-type": "application/json", **(headers or {})},
        limits=limits,
    )


def get_bytes(
    url: str,
    *,
    limits: HttpRequestLimits | None = None,
    headers: Mapping[str, str] | None = None,
) -> HttpResponse:
    """GET ``url`` with bounded retries."""
    return _request_with_retries(
        "GET",
        url,
        body=b"",
        headers=dict(headers or {}),
        limits=limits,
    )


def _serialize_json(
    payload: Mapping[str, Any],
    *,
    limits: HttpRequestLimits | None,
) -> bytes:
    import json

    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    body = serialized.encode("utf-8")
    max_bytes = limits.max_request_bytes if limits else DEFAULT_MAX_REQUEST_BYTES
    if len(body) > max_bytes:
        raise HttpClientError(f"Request body is {len(body)} bytes; max is {max_bytes}.")
    return body


def _sleep_seconds(
    attempt: int,
    *,
    backoff_base: float,
    backoff_cap: float,
    retry_after: float | None,
) -> float:
    if retry_after is not None:
        return min(backoff_cap, max(0.0, retry_after))
    return min(backoff_cap, backoff_base * (2 ** (attempt - 1)))


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return max(0.0, seconds)


def _request_with_retries(
    method: str,
    url: str,
    *,
    body: bytes,
    headers: Mapping[str, str],
    limits: HttpRequestLimits | None,
) -> HttpResponse:
    """Run a single HTTP request with bounded retries.

    The implementation uses the streaming
    :meth:`httpx.Client.stream` context manager so the
    response body is *never* fully buffered before the
    byte cap is enforced. The cap is checked during
    ``iter_bytes``; a hostile upstream that sends more
    bytes than the cap triggers a streaming rejection
    and the partial body is discarded. The response is
    closed on every exit path (success, oversize,
    status, HTTP error, timeout) by the
    ``with client.stream(...)`` context manager.
    """
    limits = limits or HttpRequestLimits()
    validate_url(url)
    client = get_http_client()
    last_error: Exception | None = None
    for attempt in range(1, limits.retry_limit + 2):
        started = time.monotonic()
        try:
            # ``client.stream(...)`` returns a context
            # manager that opens the connection lazily and
            # closes it on exit. The body is *not* read
            # until ``iter_bytes`` is called. The cap is
            # enforced inside the ``with`` block so a
            # successful run reaches the close path via
            # the normal exit and a streaming rejection
            # closes the response via the exception exit
            # path; both are handled by the context
            # manager.
            with client.stream(
                method,
                url,
                content=body,
                headers=dict(headers),
                timeout=limits.timeout_seconds,
            ) as response:
                elapsed = time.monotonic() - started
                # 3xx is a hard error here: the shared
                # provider client does not follow
                # redirects (the SSRF-aware redirect
                # chain is owned by
                # ``app.utils.bounded_http``; provider
                # calls go through an allow-listed URL).
                if response.status_code in (301, 302, 303, 307, 308):
                    raise HttpClientError(
                        f"HTTP {method} {url} returned a redirect "
                        f"({response.status_code}); the shared provider "
                        f"client does not follow redirects."
                    )
                if response.status_code in _RETRY_STATUS_CODES and attempt <= limits.retry_limit:
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    time.sleep(
                        _sleep_seconds(
                            attempt,
                            backoff_base=limits.backoff_base_seconds,
                            backoff_cap=limits.backoff_cap_seconds,
                            retry_after=retry_after,
                        )
                    )
                    continue
                if response.status_code in _RETRY_STATUS_CODES:
                    # Retries exhausted for a server-side failure.
                    raise HttpClientError(
                        f"HTTP {method} {url} returned "
                        f"{response.status_code} after "
                        f"{limits.retry_limit + 1} attempts."
                    )
                if response.status_code >= 400:
                    # Generic 4xx is a hard error: do not
                    # retry, do not buffer the body (the
                    # body could be an attack payload that
                    # the cap must bound even on a 4xx
                    # path). The status / headers / body
                    # are surfaced through ``HttpClientError``
                    # so the caller can record the upstream
                    # failure without leaking the raw body
                    # into the error envelope.
                    raise HttpClientError(f"HTTP {method} {url} returned {response.status_code}.")
                # 2xx / 3xx-rejected path: read the body
                # under the cap and return the response.
                content = _stream_bounded_body(response, limits.max_response_bytes)
                if len(content) > limits.max_response_bytes:
                    # Defensive: the streaming cap already
                    # raises on oversize; the explicit
                    # check is a safety net for stub
                    # responses that do not implement
                    # ``iter_bytes`` honestly.
                    raise HttpResponseTooLargeError(
                        f"Response body is {len(content)} bytes; max is "
                        f"{limits.max_response_bytes}."
                    )
                return HttpResponse(
                    status_code=response.status_code,
                    headers=dict(response.headers.items()),
                    body=content,
                    elapsed_seconds=elapsed,
                    attempts=attempt,
                )
        except httpx.TimeoutException as exc:
            last_error = exc
            time.sleep(
                _sleep_seconds(
                    attempt,
                    backoff_base=limits.backoff_base_seconds,
                    backoff_cap=limits.backoff_cap_seconds,
                    retry_after=None,
                )
            )
            continue
        except httpx.HTTPError as exc:
            last_error = exc
            time.sleep(
                _sleep_seconds(
                    attempt,
                    backoff_base=limits.backoff_base_seconds,
                    backoff_cap=limits.backoff_cap_seconds,
                    retry_after=None,
                )
            )
            continue
        # A successful ``return`` inside the ``with``
        # block already closed the response; the
        # ``continue`` paths in the block also close on
        # exit. We do not need a final ``close()`` here.
    raise HttpClientError(
        f"HTTP {method} {url} failed after {limits.retry_limit + 1} attempts: {last_error!r}"
    )


def _stream_bounded_body(response: httpx.Response, max_bytes: int) -> bytes:
    """Stream the response body in fixed-size chunks.

    The cap is enforced *while* the body is being read;
    a hostile upstream that sends more bytes than the
    cap is aborted as soon as the cap is crossed. The
    partial body is discarded via ``parts.clear()`` so
    a single oversized response cannot exhaust process
    memory. The function returns the bytes only when
    the total fits within the cap; otherwise it raises
    :class:`HttpResponseTooLargeError` and the response
    is closed by the surrounding
    ``with client.stream(...)`` context manager.

    The function uses the streaming ``iter_bytes`` API.
    A response stub that does not implement
    ``iter_bytes`` honestly is detected by the
    ``read()`` fallback below, which is bounded by the
    same cap check on the buffered body. The fallback
    is only used by tests; production responses are
    real ``httpx.Response`` objects and stream.
    """
    chunk_size = max(64 * 1024, min(max_bytes, 1024 * 1024))
    parts: list[bytes] = []
    total = 0
    if hasattr(response, "iter_bytes"):
        try:
            for chunk in response.iter_bytes(chunk_size=chunk_size):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    parts.clear()
                    raise HttpResponseTooLargeError(
                        f"Response body exceeded the limit {max_bytes} while streaming."
                    )
                parts.append(chunk)
        except httpx.HTTPError as exc:
            raise HttpClientError(f"Stream interrupted: {exc}") from exc
    else:
        # Test stub path: ``read()`` may return the
        # whole body at once. The cap is checked on the
        # buffered body; the production streaming path
        # never reaches this branch.
        try:
            body = response.read()
        except httpx.HTTPError as exc:
            raise HttpClientError(f"Stream interrupted: {exc}") from exc
        if len(body) > max_bytes:
            raise HttpResponseTooLargeError(
                f"Response body is {len(body)} bytes; max is {max_bytes}."
            )
        parts.append(body)
    return b"".join(parts)


def make_request_fn(
    limits: HttpRequestLimits | None = None,
) -> Callable[[str, str, bytes, Mapping[str, str]], HttpResponse]:
    """Return a :class:`Callable` suitable for dependency injection.

    Tests substitute this with a mock. The signature is
    ``(method, url, body, headers) -> HttpResponse``.
    """
    inner_limits = limits or HttpRequestLimits()

    def _request(
        method: str,
        url: str,
        body: bytes,
        headers: Mapping[str, str],
    ) -> HttpResponse:
        return _request_with_retries(method, url, body=body, headers=headers, limits=inner_limits)

    return _request
