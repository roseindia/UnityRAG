"""Tenant / department analytics, usage & costs, CSV reports (extension 7.8, 10; FR-193, FR-225)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.deps import admin, tx, worker_tx
from app.core.errors import PermissionDenied
from app.dependencies.auth import require_any
from app.schemas.common import ERROR_RESPONSES
from app.security.context import RequestContext
from app.services import analytics_service
from app.services.audit import tenant_audit

router = APIRouter(tags=["Analytics"], responses=ERROR_RESPONSES)


@router.get("/admin/analytics", summary="Search and chat analytics, retrieval and citation quality")
def analytics(start: date | None = None, end: date | None = None,
              ctx: RequestContext = Depends(admin("admin.analytics.view", write=False))) -> dict:
    with worker_tx(ctx) as db:  # aggregate-only (ADR-012)
        return {"search": analytics_service.search_analytics(db, start, end),
                "chat": analytics_service.chat_analytics(db, start, end)}


@router.get("/admin/analytics/search")
def search_analytics(start: date | None = None, end: date | None = None,
                     ctx: RequestContext = Depends(admin("admin.analytics.view", write=False))) -> dict:
    with worker_tx(ctx) as db:
        return analytics_service.search_analytics(db, start, end)


@router.get("/admin/analytics/chat")
def chat_analytics(start: date | None = None, end: date | None = None,
                   ctx: RequestContext = Depends(admin("admin.analytics.view", write=False))) -> dict:
    with worker_tx(ctx) as db:
        return analytics_service.chat_analytics(db, start, end)


@router.get("/admin/usage", summary="Usage, quotas and estimated AI costs by model and department")
def usage(start: date | None = None, end: date | None = None,
          ctx: RequestContext = Depends(admin("admin.usage.view", write=False))) -> dict:
    with tx(ctx, "auditor") as db:
        return analytics_service.usage_and_costs(db, ctx.tenant_id, start, end)  # type: ignore[arg-type]


@router.get("/admin/reports/{name}.csv", summary="Export an authorised report as CSV")
def report(name: str, start: date | None = None, end: date | None = None,
           ctx: RequestContext = Depends(admin("admin.reports.export", write=False))) -> Response:
    if name in analytics_service.OWNER_SCOPED:
        with worker_tx(ctx) as db:
            body = analytics_service.report_csv(db, name, start, end)
    else:
        with tx(ctx, "auditor") as db:
            body = analytics_service.report_csv(db, name, start, end)
    with tx(ctx, "auditor") as db:
        tenant_audit(db, tenant_id=ctx.tenant_id, category="document_access", event_type="report_exported",  # type: ignore[arg-type]
                     actor_user_id=ctx.user_id, resource_type="report", resource_id=name,
                     detail={"start": str(start), "end": str(end), "bytes": len(body)})
    return Response(content=body, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"', "Cache-Control": "no-store"})


@router.get("/analytics/department", summary="Department administrator view (own department only)")
def department(start: date | None = None, end: date | None = None,
               ctx: RequestContext = Depends(require_any("department.analytics.view", "admin.analytics.view"))) -> dict:
    if ctx.department_id is None:
        raise PermissionDenied("You are not assigned to a department")
    with tx(ctx, "auditor") as db:
        return analytics_service.department_dashboard(db, ctx.department_id, start, end)
