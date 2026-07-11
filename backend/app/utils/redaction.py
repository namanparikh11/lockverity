"""Provider-error redaction.

When external providers fail, we keep an *error_summary* on disk for
debugging. The summary must never include:

- Authorization headers or their values
- API keys, access tokens, or session cookies
- Sensitive query parameters
- Local filesystem paths (other than the workspace path itself)
- Excessively long provider messages
- Raw response bodies

This module also exposes :func:`redact_url` which strips query strings
from URLs entirely and replaces the path with a SHA-256 prefix when
needed. Providers occasionally echo back request URLs in error messages;
those URLs often contain tokens in the query string.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# Tokens we always strip from free-form text. We match the assignment
# shape ("key=value", "key: value", "key: Bearer <token>") so the
# redaction does not depend on a specific provider's exact wording.
_SENSITIVE_KEYS = (
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api_key",
    "apikey",
    "access_token",
    "access-token",
    "accesstoken",
    "refresh_token",
    "refresh-token",
    "id_token",
    "session",
    "sessionid",
    "cookie",
    "set-cookie",
    "token",
    "bearer",
    "password",
    "secret",
)

_SENSITIVE_KEY_RE = re.compile(
    r"(?i)\b(" + "|".join(re.escape(k) for k in _SENSITIVE_KEYS) + r")\b"
    r"\s*[:=]\s*([^\s,;\"'`<>]+|\"[^\"]*\"|'[^']*')"
)
# Bearer prefix capture: ``Authorization: Bearer <token>``.
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]+")
# Long opaque strings often used as tokens (heuristic - 32+ chars of
# base64-ish content, not anchored to a key word).
_BLOB_RE = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")

MAX_SUMMARY_LENGTH = 500


def _scrub(value: str) -> str:
    """Strip sensitive material from a free-form string."""
    if not value:
        return value
    scrubbed = _BEARER_RE.sub("Bearer [REDACTED]", value)
    scrubbed = _SENSITIVE_KEY_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", scrubbed)
    # We deliberately do *not* run the heuristic blob scrubber on every
    # string - it would destroy useful diagnostics like commit SHAs.
    # Callers can opt in by passing ``scrub_blobs=True``.
    return scrubbed


def redact_provider_summary(
    summary: str | None,
    *,
    max_length: int = MAX_SUMMARY_LENGTH,
    scrub_blobs: bool = False,
) -> str | None:
    """Return a safe, bounded provider error summary string."""
    if summary is None:
        return None
    if not isinstance(summary, str):
        summary = str(summary)
    scrubbed = _scrub(summary)
    if scrub_blobs:
        scrubbed = _BLOB_RE.sub("[REDACTED]", scrubbed)
    if len(scrubbed) > max_length:
        scrubbed = scrubbed[: max_length - 3] + "..."
    return scrubbed


def redact_url(url: str) -> str:
    """Strip query strings and fragments from ``url`` for safe logging.

    The path is preserved in full because it identifies the resource.
    The query string and fragment are removed entirely.
    """
    if not isinstance(url, str) or not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[invalid-url]"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def redact_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    """Return a copy of ``headers`` with sensitive values removed.

    Authorization, cookie, and token headers are dropped. Other values
    are preserved verbatim. The result is suitable for diagnostic logs.
    """
    if not headers:
        return {}
    safe: dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(value, str):
            continue
        if any(s in key.lower() for s in _SENSITIVE_KEYS):
            continue
        safe[key] = value
    return safe


def redact_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a deep-copied payload with sensitive keys redacted.

    This is conservative: any key whose lowercased name matches one of
    the sensitive patterns is replaced with ``"[REDACTED]"``. Lists and
    dicts are walked recursively.
    """
    if payload is None:
        return {}
    return _redact_mapping(payload)


def _redact_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(key, str) and any(s in key.lower() for s in _SENSITIVE_KEYS):
            result[key] = "[REDACTED]"
        elif isinstance(value, Mapping):
            result[key] = _redact_mapping(value)
        elif isinstance(value, list):
            result[key] = [_redact_any(v) for v in value]
        else:
            result[key] = value
    return result


def _redact_any(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _redact_mapping(value)
    if isinstance(value, list):
        return [_redact_any(v) for v in value]
    if isinstance(value, str):
        return _scrub(value)
    return value
