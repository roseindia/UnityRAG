"""Correlation-ID, request metrics and security-header middleware (FR-199, NFR-072/074)."""
from __future__ import annotations

import logging
import time

from opentelemetry.trace import SpanKind, Status, StatusCode
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.context import get_correlation_id, new_correlation_id, set_log_tenant
from app.observability.metrics import HTTP_LATENCY, HTTP_REQUESTS
from app.observability.tracing import extract_context, tracer

log = logging.getLogger("app.http")


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cid = new_correlation_id(request.headers.get("x-correlation-id"))
        set_log_tenant(None)
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > get_settings().max_request_bytes:
            return JSONResponse({"error": {"code": "payload_too_large", "message": "Request too large",
                                           "correlation_id": cid, "details": []}}, status_code=413)
        start = time.perf_counter()
        with tracer.start_as_current_span(f"HTTP {request.method}", context=extract_context(request.headers),
                                          kind=SpanKind.SERVER) as sp:
            sp.set_attribute("http.request.method", request.method)
            sp.set_attribute("correlation_id", cid)
            response = await call_next(request)
            route = request.scope.get("route")
            path = getattr(route, "path", "unmatched")
            sp.update_name(f"{request.method} {path}")
            sp.set_attribute("http.route", path)
            sp.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 500:
                sp.set_status(Status(StatusCode.ERROR))
            trace_id = sp.get_span_context().trace_id
        elapsed = time.perf_counter() - start
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, path).observe(elapsed)
        response.headers["X-Correlation-ID"] = get_correlation_id()
        if trace_id:
            response.headers["X-Trace-ID"] = format(trace_id, "032x")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        log.info("request", extra={"method": request.method, "path": path, "status": response.status_code,
                                   "duration_ms": round(elapsed * 1000, 1)})
        return response
