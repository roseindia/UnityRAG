"""Centralised error model (FR-195, NFR-094).

Every error leaving the API has the same machine-readable shape:
    {"error": {"code": "...", "message": "...", "correlation_id": "...", "details": [...]}}
Internal details (stack traces, SQL, driver messages) are never returned.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.context import get_correlation_id

log = logging.getLogger("app.errors")


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: list[dict[str, Any]] | None = None,
                 status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or []


class AuthenticationError(AppError):
    status_code = 401
    code = "authentication_failed"


class PermissionDenied(AppError):
    status_code = 403
    code = "permission_denied"


class TenantUnavailable(AppError):
    status_code = 403
    code = "tenant_unavailable"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class QuotaExceeded(AppError):
    status_code = 429
    code = "quota_exceeded"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"


def _body(code: str, message: str, details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "correlation_id": get_correlation_id(),
                      "details": details or []}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        headers = {"Retry-After": "60"} if exc.status_code == 429 else None
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"field": ".".join(str(p) for p in e.get("loc", [])), "message": e.get("msg", "")}
                   for e in exc.errors()]
        return JSONResponse(_body("validation_failed", "Request validation failed", details), status_code=422)

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        log.warning("integrity error", extra={"sqlstate": getattr(exc.orig, "sqlstate", None)})
        return JSONResponse(_body("conflict", "The request conflicts with existing data or references "
                                              "a resource that is not available."), status_code=409)

    @app.exception_handler(DBAPIError)
    async def _dbapi(_: Request, exc: DBAPIError) -> JSONResponse:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate == "42501":  # insufficient_privilege, incl. RLS WITH CHECK violations
            log.warning("database privilege / RLS violation", extra={"sqlstate": sqlstate})
            return JSONResponse(_body("permission_denied", "The operation is not permitted."), status_code=403)
        if sqlstate == "22P02":  # invalid text representation (e.g. bad uuid in context)
            return JSONResponse(_body("bad_request", "Invalid identifier."), status_code=400)
        log.exception("database error", extra={"sqlstate": sqlstate})
        return JSONResponse(_body("internal_error", "An internal error occurred."), status_code=500)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(_body("internal_error", "An internal error occurred."), status_code=500)
