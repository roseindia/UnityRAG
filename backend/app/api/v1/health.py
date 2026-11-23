"""Liveness, readiness and metrics (FR-235, NFR-072)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.core.config import get_settings
from app.database.session import SecurityContext, scoped_session
from app.utils.cache import get_cache

router = APIRouter(tags=["Health"])


@router.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
def ready() -> JSONResponse:
    checks = {}
    try:
        with scoped_session(SecurityContext.anonymous()) as db:
            db.execute(text("SELECT 1"))
            ext = db.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
        checks["database"] = "ok"
        checks["pgvector"] = ext or "missing"
    except Exception as exc:
        checks["database"] = f"error:{type(exc).__name__}"
    checks["cache"] = "ok" if get_cache().ping() else "unavailable"
    ok = checks.get("database") == "ok" and checks.get("pgvector") not in (None, "missing")
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Prometheus exposition; scrape from inside the network (Nginx denies it publicly)."""
    if not get_settings().metrics_enabled:
        return Response(status_code=404)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
