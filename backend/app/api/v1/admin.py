"""Tenant Admin Console: dashboard, AI/RAG configuration, settings, feedback
review (extension 7.1, 7.7, 9; FR-157..FR-162, FR-170..FR-173)."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import admin, tx, worker_tx
from app.core.errors import NotFound
from app.schemas.admin import AiConfigUpdate, FeedbackUpdate, RagConfigUpdate, TenantSettingsUpdate
from app.schemas.common import ERROR_RESPONSES, Page, PageParams
from app.security.context import RequestContext
from app.services import analytics_service, config_service
from app.services.audit import tenant_audit
from app.services.document_service import invalidate_tenant_cache

router = APIRouter(prefix="/admin", tags=["Tenant Admin - Console"], responses=ERROR_RESPONSES)


@router.get("/dashboard", summary="Tenant dashboard: totals, trends, quotas (real database data)")
def dashboard(start: date | None = None, end: date | None = None,
              ctx: RequestContext = Depends(admin("admin.dashboard.view", write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        out = analytics_service.tenant_dashboard(db, ctx.tenant_id, start, end)  # type: ignore[arg-type]
    with worker_tx(ctx) as wdb:  # aggregate-only counts over owner-scoped tables (ADR-012)
        live = wdb.execute(text("""SELECT (SELECT count(*) FROM rag.conversations WHERE status = 'active') AS total_conversations,
                                          (SELECT count(*) FROM rag.search_logs WHERE mode <> 'chat') AS total_searches""")).mappings().one()
    out["totals"] |= dict(live)
    return out


@router.get("/config", summary="Active AI and RAG configuration plus the settings the tenant may change")
def get_config(ctx: RequestContext = Depends(admin("admin.ai_config.manage", write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        overridable = db.execute(text("SELECT tenant_overridable_ai_settings FROM platform.tenant_settings WHERE tenant_id = :t"),
                                 {"t": ctx.tenant_id}).scalar()
        return {"ai": config_service.active_ai_config(db).__dict__, "rag": config_service.active_rag_config(db).__dict__,
                "tenant_overridable_settings": overridable,
                "available_models": [dict(r) for r in db.execute(text("""
                    SELECT p.code AS provider, m.model_name, m.purpose, m.dimensions, m.status FROM platform.model_catalogue m
                      JOIN platform.ai_providers p ON p.provider_id = m.provider_id
                     WHERE m.status IN ('approved', 'active') AND p.is_enabled ORDER BY m.purpose, p.code""")).mappings()]}


@router.put("/config", summary="Update AI and/or RAG configuration (creates new versions)")
def put_config(ai: AiConfigUpdate | None = None, rag: RagConfigUpdate | None = None,
               ctx: RequestContext = Depends(admin("admin.ai_config.manage"))) -> dict:
    out: dict = {}
    with tx(ctx, "tenant_admin") as db:
        sec = ctx.security("tenant_admin")
        if ai:
            changes = ai.model_dump(exclude_unset=True)
            reason = changes.pop("reason", None)
            if changes:
                out["ai"] = config_service.update_ai_config(db, sec, changes, reason)
        if rag:
            if "admin.rag_config.manage" not in ctx.permissions:
                from app.core.errors import PermissionDenied

                raise PermissionDenied("admin.rag_config.manage required")
            changes = rag.model_dump(exclude_unset=True)
            reason = changes.pop("reason", None)
            if changes:
                out["rag"] = config_service.update_rag_config(db, sec, changes, reason)
    invalidate_tenant_cache(ctx.tenant_id)  # type: ignore[arg-type]
    return out


@router.put("/config/ai", summary="Update AI model configuration")
def put_ai(body: AiConfigUpdate, ctx: RequestContext = Depends(admin("admin.ai_config.manage"))) -> dict:
    changes = body.model_dump(exclude_unset=True)
    reason = changes.pop("reason", None)
    with tx(ctx, "tenant_admin") as db:
        res = config_service.update_ai_config(db, ctx.security("tenant_admin"), changes, reason)
    invalidate_tenant_cache(ctx.tenant_id)  # type: ignore[arg-type]
    return res


@router.put("/config/rag", summary="Update RAG configuration")
def put_rag(body: RagConfigUpdate, ctx: RequestContext = Depends(admin("admin.rag_config.manage"))) -> dict:
    changes = body.model_dump(exclude_unset=True)
    reason = changes.pop("reason", None)
    with tx(ctx, "tenant_admin") as db:
        res = config_service.update_rag_config(db, ctx.security("tenant_admin"), changes, reason)
    invalidate_tenant_cache(ctx.tenant_id)  # type: ignore[arg-type]
    return res


@router.get("/config/history/{kind}", summary="Configuration version history (ai | rag)")
def config_history(kind: str, ctx: RequestContext = Depends(admin("admin.ai_config.manage", write=False))) -> list[dict]:
    table = {"ai": "tenant_ai_configurations", "rag": "tenant_rag_configurations"}.get(kind)
    if not table:
        raise NotFound("unknown configuration kind")
    with tx(ctx, "tenant_admin") as db:
        return config_service.history(db, table)


@router.post("/config/rollback/{kind}/{version}", summary="Roll back to a previous configuration version")
def config_rollback(kind: str, version: int, ctx: RequestContext = Depends(admin("admin.ai_config.manage"))) -> dict:
    table = {"ai": "tenant_ai_configurations", "rag": "tenant_rag_configurations"}.get(kind)
    if not table:
        raise NotFound("unknown configuration kind")
    with tx(ctx, "tenant_admin") as db:
        res = config_service.rollback(db, ctx.security("tenant_admin"), table, version)
    invalidate_tenant_cache(ctx.tenant_id)  # type: ignore[arg-type]
    return res


@router.get("/settings")
def get_settings_(ctx: RequestContext = Depends(admin("admin.settings.manage", write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        row = db.execute(text("SELECT * FROM platform.tenant_settings WHERE tenant_id = :t"), {"t": ctx.tenant_id}).mappings().one()
        tenant = db.execute(text("SELECT code, name, status, branding FROM platform.tenants WHERE tenant_id = :t"),
                            {"t": ctx.tenant_id}).mappings().one()
        flags = {r[0]: r[1] for r in db.execute(text("SELECT flag, enabled FROM platform.tenant_feature_flags WHERE tenant_id = :t"),
                                                  {"t": ctx.tenant_id})}
    return {"settings": dict(row), "tenant": dict(tenant), "features": flags}


@router.put("/settings")
def put_settings(body: TenantSettingsUpdate, ctx: RequestContext = Depends(admin("admin.settings.manage"))) -> dict:
    changes = body.model_dump(exclude_unset=True)
    with tx(ctx, "tenant_admin") as db:
        if changes:
            sets = ", ".join(f"{k} = :{k}" for k in changes)
            db.execute(text(f"UPDATE platform.tenant_settings SET {sets}, updated_by = :by, updated_at = now() WHERE tenant_id = :t"),
                       {**changes, "by": ctx.account_id, "t": ctx.tenant_id})
            tenant_audit(db, tenant_id=ctx.tenant_id, category="configuration", event_type="tenant_settings_changed",  # type: ignore[arg-type]
                         actor_user_id=ctx.user_id, resource_type="tenant_settings", resource_id=ctx.tenant_id,
                         detail={"changed": changes})
        return dict(db.execute(text("SELECT * FROM platform.tenant_settings WHERE tenant_id = :t"), {"t": ctx.tenant_id}).mappings().one())


@router.get("/feedback", response_model=Page[dict], summary="Human review queue (FR-157)")
def feedback_queue(status: str | None = None, category: str | None = None, page: PageParams = Depends(),
                   ctx: RequestContext = Depends(admin("feedback.review", write=False))) -> Page[dict]:
    where, p = ["true"], {"l": page.limit, "o": page.offset}
    if status:
        where.append("status = :status")
        p["status"] = status
    if category:
        where.append("category = :category")
        p["category"] = category
    w = " AND ".join(where)
    with tx(ctx, "tenant_admin") as db:
        total = db.execute(text(f"SELECT count(*) FROM rag.feedback WHERE {w}"), p).scalar_one()
        items = [dict(r) for r in db.execute(text(f"""SELECT * FROM rag.feedback WHERE {w}
                                                     ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                                                              WHEN 'medium' THEN 2 ELSE 3 END, created_at
                                                     LIMIT :l OFFSET :o"""), p).mappings()]
    return Page(items=items, total=int(total), limit=page.limit, offset=page.offset)


@router.put("/feedback/{feedback_id}", summary="Triage / assign / resolve feedback")
def feedback_update(feedback_id: uuid.UUID, body: FeedbackUpdate, ctx: RequestContext = Depends(admin("feedback.review"))) -> dict:
    changes = body.model_dump(exclude_unset=True)
    with tx(ctx, "tenant_admin") as db:
        if changes:
            sets = ", ".join(f"{k} = :{k}" for k in changes)
            extra = ", resolved_at = now()" if changes.get("status") in ("resolved", "rejected") else ""
            res = db.execute(text(f"UPDATE rag.feedback SET {sets}{extra} WHERE feedback_id = :f"), {**changes, "f": feedback_id})
            if res.rowcount == 0:
                raise NotFound("Feedback not found")
            tenant_audit(db, tenant_id=ctx.tenant_id, category="feedback", event_type="feedback_updated",  # type: ignore[arg-type]
                         actor_user_id=ctx.user_id, resource_type="feedback", resource_id=feedback_id,
                         detail={k: str(v) for k, v in changes.items() if k != "resolution"})
        return dict(db.execute(text("SELECT * FROM rag.feedback WHERE feedback_id = :f"), {"f": feedback_id}).mappings().one())
