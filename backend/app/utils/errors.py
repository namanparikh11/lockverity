"""Cross-cutting errors and small helpers used across the backend."""

from __future__ import annotations

from enum import Enum
from typing import Any


class ApiErrorCode(str, Enum):
    """Stable, machine-readable error codes returned to clients.

    These are public API surface area. New codes may be added; existing
    codes must not be removed or renamed without a deprecation cycle.
    """

    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    ILLEGAL_TRANSITION = "illegal_transition"
    DUPLICATE = "duplicate"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    ARCHIVE_UNSAFE = "archive_unsafe"
    PATH_UNSAFE = "path_unsafe"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    RATE_LIMITED = "rate_limited"
    INTERNAL = "internal_error"
    # v1.6.1: a rescan was requested but the original
    # source evidence is no longer available (for
    # example, the original uploaded archive was
    # cleaned up). The route must return this code
    # before creating a broken queued scan.
    RESCAN_SOURCE_UNAVAILABLE = "rescan_source_unavailable"
    # v2.1.1: a syntactically-valid ref (branch, tag or
    # full commit SHA) that does not exist on the
    # targeted repository. The intake distinguishes
    # this from ``NOT_FOUND`` (which is the "URL is
    # wrong / private repository / repository does not
    # exist" classification); the two are different
    # user-facing failure modes and need distinct
    # actionable messages.
    INVALID_REF = "invalid_ref"
    # v2.1.1: a request reached the application but the
    # server failed to satisfy it for an unexpected
    # reason (a programmer error, an unhandled
    # exception, a filesystem error that survived every
    # bounded fallback, etc.). The error envelope
    # carries a short, non-PII correlation id; the full
    # stack trace and the safe diagnostics are written
    # to the local log file under the runtime home.
    INTERNAL_UNEXPECTED = "internal_unexpected"


class ApiError(Exception):
    """Application error with a stable code and safe message.

    Use :class:`ApiError` for every error that should reach a client.
    Anything else bubbles up to the generic 500 handler.
    """

    def __init__(
        self,
        code: str | ApiErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code.value if isinstance(code, ApiErrorCode) else code
        self.message = message
        self.details = details
        self.headers = headers
