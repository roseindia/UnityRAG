"""Tenant audit log views and integrity verification (FR-194, FR-229, FR-230)."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import text

from app.api.deps import admin, tx
from app.schemas.common import ERROR_RESPONSES, Page, PageParams
from app.security.context import RequestContext
from app.services.audit import tenant_audit

router = APIRouter(prefix="/admin/audit", tags=["Tenant Admin - Audit"], responses=ERROR_RESPONSES)


def _query(category: str | None, actor_user_id: uuid.UUID | None, resource_id: str | None, correlation_id: str | None,
           outcome: str | None, start: datetime | None, end: datetime | None) -> tuple[str, dict]:
    where, p = ["tenant_id = app.current_tenant_id()"], {}
    for col, val in (("category", category), ("actor_user_id", actor_user_id), ("resource_id", resource_id),
                     ("correlation_id", correlation_id), ("outcome", outcome)):
        if val:
            where.append(f"{col} = :{col}")
            p[col] = val
    if start:
        where.append("occurred_at >= :start")
        p["start"] = start
    if end:
        where.append("occurred_at < :end")
        p["end"] = end
    return " AND ".join(where), p


@router.get("", response_model=Page[dict], summary="Search tenant audit events")
def list_events(category: str | None = None, actor_user_id: uuid.UUID | None = None, resource_id: str | None = None,
                correlation_id: str | None = None, outcome: str | None = None, start: datetime | None = None,
                end: datetime | None = None, page: PageParams = Depends(),
                ctx: RequestContext = Depends(admin("admin.audit.view", write=False))) -> Page[dict]:
    w, p = _query(category, actor_user_id, resource_id, correlation_id, outcome, start, end)
    with tx(ctx, "auditor") as db:
        total = db.execute(text(f"SELECT count(*) FROM audit.tenant_audit_logs WHERE {w}"), p).scalar_one()
        items = [dict(r) for r in db.execute(text(f"""SELECT event_id, seq, occurred_at, category, event_type, outcome, actor_type,
                                                             actor_user_id, resource_type, resource_id, correlation_id, detail, hash
                                                        FROM audit.tenant_audit_logs WHERE {w}
                                                       ORDER BY seq DESC LIMIT :l OFFSET :o"""),
                                             p | {"l": page.limit, "o": page.offset}).mappings()]
        # audit-log access is itself audited (FR-228)
        tenant_audit(db, tenant_id=ctx.tenant_id, category="administration", event_type="audit_queried",  # type: ignore[arg-type]
                     actor_user_id=ctx.user_id, detail={"filters": {k: str(v) for k, v in p.items()}})
    return Page(items=items, total=int(total), limit=page.limit, offset=page.offset)


@router.get("/export.csv", summary="Export audit events as CSV")
def export(category: str | None = None, start: datetime | None = None, end: datetime | None = None,
           ctx: RequestContext = Depends(admin("admin.audit.view", write=False))) -> Response:
    w, p = _query(category, None, None, None, None, start, end)
    with tx(ctx, "auditor") as db:
        res = db.execute(text(f"""SELECT occurred_at, category, event_type, outcome, actor_user_id, resource_type, resource_id,
                                         correlation_id, hash FROM audit.tenant_audit_logs WHERE {w} ORDER BY seq LIMIT 100000"""), p)
        buf = io.StringIO()
        wr = csv.writer(buf)
        wr.writerow(res.keys())
        wr.writerows(res)
        tenant_audit(db, tenant_id=ctx.tenant_id, category="administration", event_type="audit_exported",  # type: ignore[arg-type]
                     actor_user_id=ctx.user_id)
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="audit.csv"'})


@router.get("/verify", summary="Verify the tenant's audit hash chain (tamper evidence)")
def verify(ctx: RequestContext = Depends(admin("admin.audit.view", write=False))) -> dict:
    with tx(ctx, "auditor") as db:
        row = db.execute(text("SELECT * FROM audit.verify_tenant_chain()")).mappings().one()
    return dict(row)
