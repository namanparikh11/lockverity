"""Structured API errors.

Lockverity returns a stable error envelope:

    {
        "error": {
            "code": "stable_machine_readable_code",
            "message": "safe human-readable summary",
            "details": {...}    // optional, safe structured data
            "request_id": "..."  // optional, when middleware supplies one
        }
    }

No stack traces, no internal paths, no provider secrets, no arbitrary
provider response bodies. Clients should always be able to parse the
``code`` field and respond programmatically.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.utils.errors import ApiError, ApiErrorCode


def _envelope(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    if request_id is not None:
        body["request_id"] = request_id
    return {"error": body}


def _status_for_code(code: str) -> int:
    """Map stable error codes to HTTP status codes."""
    mapping: dict[str, int] = {
        ApiErrorCode.NOT_FOUND.value: 404,
        ApiErrorCode.VALIDATION_ERROR.value: 422,
        ApiErrorCode.ILLEGAL_TRANSITION.value: 409,
        ApiErrorCode.DUPLICATE.value: 409,
        ApiErrorCode.PROVIDER_UNAVAILABLE.value: 502,
        ApiErrorCode.ARCHIVE_UNSAFE.value: 400,
        ApiErrorCode.PATH_UNSAFE.value: 400,
        ApiErrorCode.UNAUTHORIZED.value: 401,
        ApiErrorCode.FORBIDDEN.value: 403,
        ApiErrorCode.RATE_LIMITED.value: 429,
        ApiErrorCode.INTERNAL.value: 500,
    }
    return mapping.get(code, 500)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=_status_for_code(exc.code),
        content=_envelope(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=_request_id(request),
        ),
        headers=exc.headers or None,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "http_error"
    message = "Request failed."
    details: dict[str, Any] | None = None
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        code = str(exc.detail.get("code", code))
        message = str(exc.detail.get("message", message))
        details = exc.detail.get("details")
    elif isinstance(exc.detail, str):
        message = exc.detail
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(
            code=code,
            message=message,
            details=details,
            request_id=_request_id(request),
        ),
        headers=exc.headers or None,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Only include safe, summarized details - never the raw input payloads.
    safe_errors: list[dict[str, Any]] = []
    for err in exc.errors():
        safe_errors.append(
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "type": str(err.get("type", "value_error")),
                "msg": str(err.get("msg", "")),
            }
        )
    return JSONResponse(
        status_code=422,
        content=_envelope(
            code=ApiErrorCode.VALIDATION_ERROR.value,
            message="Request validation failed.",
            details={"errors": safe_errors},
            request_id=_request_id(request),
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak the traceback. Log server-side instead.
    return JSONResponse(
        status_code=500,
        content=_envelope(
            code=ApiErrorCode.INTERNAL.value,
            message="An internal error occurred.",
            request_id=_request_id(request),
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire structured error handlers onto a FastAPI app."""
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
