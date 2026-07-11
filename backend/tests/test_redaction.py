"""Tests for :mod:`app.utils.redaction`."""

from __future__ import annotations

from app.utils.redaction import (
    redact_headers,
    redact_payload,
    redact_provider_summary,
    redact_url,
)


def test_redacts_bearer_token() -> None:
    summary = "Server said: Authorization: Bearer abcdef1234567890abcdef1234567890"
    out = redact_provider_summary(summary)
    assert "abcdef1234567890abcdef1234567890" not in out
    # Either the "Bearer" line is rewritten, or the key=value form is
    # redacted. Both are acceptable. The contract is "no token leaks".
    assert "Bearer [REDACTED]" in out or "Authorization=[REDACTED]" in out


def test_redacts_authorization_key_value() -> None:
    summary = "Failed with authorization=Bearer xyz"
    out = redact_provider_summary(summary)
    assert "[REDACTED]" in out
    assert "xyz" not in out


def test_redacts_api_key() -> None:
    summary = "Bad request, api_key=12345"
    out = redact_provider_summary(summary)
    assert "12345" not in out


def test_redacts_access_token() -> None:
    summary = "Token expired: access_token=secret123"
    out = redact_provider_summary(summary)
    assert "secret123" not in out


def test_truncates_long_summary() -> None:
    summary = "x" * 2000
    out = redact_provider_summary(summary, max_length=100)
    assert out is not None
    assert len(out) <= 100
    assert out.endswith("...")


def test_handles_none() -> None:
    assert redact_provider_summary(None) is None


def test_redact_url_strips_query_and_fragment() -> None:
    out = redact_url("https://api.example.com/path?token=abc#frag")
    assert out == "https://api.example.com/path"
    assert "token" not in out
    assert "frag" not in out


def test_redact_headers_drops_authorization() -> None:
    safe = redact_headers(
        {
            "Authorization": "Bearer xyz",
            "Content-Type": "application/json",
            "X-Request-Id": "abc",
        }
    )
    assert "Authorization" not in safe
    assert safe["Content-Type"] == "application/json"
    assert safe["X-Request-Id"] == "abc"


def test_redact_payload_strips_sensitive_keys() -> None:
    payload = {
        "user": "alice",
        "password": "hunter2",
        "nested": {"api_key": "k", "ok": True},
        "list": [{"token": "t"}, "fine"],
    }
    out = redact_payload(payload)
    assert out["password"] == "[REDACTED]"
    assert out["nested"]["api_key"] == "[REDACTED]"
    assert out["nested"]["ok"] is True
    assert out["list"][0]["token"] == "[REDACTED]"
    assert out["list"][1] == "fine"
