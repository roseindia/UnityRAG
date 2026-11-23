"""Platform Admin: tenant lifecycle, subscriptions, quotas, features and tenant
administrators (extension 1.3, 6.2-6.4, 9)."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import platform_tx
from app.core.errors import ValidationFailed
from app.dependencies.auth import require_platform
from app.schemas.common import ERROR_RESPONSES, Page, PageParams
from app.schemas.platform import FeatureFlag, LifecycleAction, PlanChange, QuotaUpdate, TenantAdminCreate, TenantCreate, TenantUpdate
from app.security.context import RequestContext
from app.services import platform_service, quota_service, tenant_service
from app.utils.clock import utc_today

router = APIRouter(prefix="/platform/tenants", tags=["Platform Admin - Tenants"], responses=ERROR_RESPONSES)
VIEW, MANAGE = "platform.tenants.view", "platform.tenants.manage"


@router.get("", response_model=Page[dict])
def list_tenants(q: str | None = None, status: str | None = None, plan: str | None = None, sort: str = "name",
                 page: PageParams = Depends(), ctx: RequestContext = Depends(require_platform(VIEW))) -> Page[dict]:
    with platform_tx(ctx) as db:
        items, total = tenant_service.list_tenants(db, q=q, status=status, plan=plan, limit=page.limit, offset=page.offset,
                                                   sort=sort)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("", status_code=201, summary="Create (provision) a tenant, optionally with its first administrator")
def create_tenant(body: TenantCreate, ctx: RequestContext = Depends(require_platform(MANAGE))) -> dict:
    with platform_tx(ctx) as db:
        return tenant_service.create_tenant(db, ctx.platform_security(), code=body.code, name=body.name,
                                            legal_entity=body.legal_entity, plan_code=body.plan_code,
                                            home_region=body.home_region, branding=body.branding,
                                            admin_email=body.admin_email, admin_name=body.admin_name,
                                            admin_password=body.admin_password)


@router.get("/{tenant_id}", summary="Tenant details: profile, subscription, admins, usage, quotas, configuration, audit")
def tenant_details(tenant_id: uuid.UUID, ctx: RequestContext = Depends(require_platform(VIEW))) -> dict:
    with platform_tx(ctx) as db:
        t = tenant_service.get_tenant(db, tenant_id)
        t["quotas"] = [q.__dict__ | {"pct": q.pct} for q in quota_service.snapshot(db, tenant_id)]
        t["features"] = {r[0]: r[1] for r in db.execute(text("SELECT flag, enabled FROM platform.tenant_feature_flags WHERE tenant_id = :t"),
                                                          {"t": tenant_id})}
        t["settings"] = dict(db.execute(text("SELECT * FROM platform.tenant_settings WHERE tenant_id = :t"),
                                        {"t": tenant_id}).mappings().first() or {})
        t["subscriptions"] = [dict(r) for r in db.execute(text("""SELECT s.*, p.code AS plan_code FROM platform.tenant_subscriptions s
                                                                   JOIN platform.tenant_plans p USING (plan_id)
                                                                  WHERE s.tenant_id = :t ORDER BY s.starts_at DESC"""),
                                                              {"t": tenant_id}).mappings()]
        t["usage_30d"] = tenant_service.tenant_usage_series(db, tenant_id, date.fromordinal(utc_today().toordinal() - 29),
                                                            utc_today())
        t["administrators"] = tenant_service.tenant_admins(db, ctx.platform_security(), tenant_id)
        t["recent_audit"] = platform_service.audit_events(db, category=None, tenant_id=tenant_id, severity=None,
                                                          start=None, end=None, limit=20, offset=0)[0]
        return t


@router.put("/{tenant_id}")
def update_tenant(tenant_id: uuid.UUID, body: TenantUpdate, ctx: RequestContext = Depends(require_platform(MANAGE))) -> dict:
    with platform_tx(ctx) as db:
        return tenant_service.update_tenant(db, ctx.platform_security(), tenant_id, body.model_dump(exclude_unset=True))


def _lifecycle(action: str):
    def handler(tenant_id: uuid.UUID, body: LifecycleAction, ctx: RequestContext = Depends(require_platform(MANAGE))) -> dict:
        if not body.confirm:
            raise ValidationFailed("Sensitive operation: set confirm=true")
        with platform_tx(ctx) as db:
            return tenant_service.transition(db, ctx.platform_security(), tenant_id, action, body.reason)
    handler.__name__ = f"{action}_tenant"
    return handler


for _action in ("activate", "suspend", "deactivate", "archive"):
    router.add_api_route(f"/{{tenant_id}}/{_action}", _lifecycle(_action), methods=["POST"],
                         summary=f"{_action.title()} tenant (confirmation + reason captured and audited)")


@router.get("/{tenant_id}/usage", summary="Daily usage aggregates and quota utilisation")
def tenant_usage(tenant_id: uuid.UUID, start: date | None = None, end: date | None = None,
                 ctx: RequestContext = Depends(require_platform(VIEW))) -> dict:
    end = end or utc_today()
    start = start or date.fromordinal(end.toordinal() - 29)
    with platform_tx(ctx) as db:
        tenant_service.get_tenant(db, tenant_id)
        return {"series": tenant_service.tenant_usage_series(db, tenant_id, start, end),
                "quotas": [q.__dict__ | {"pct": q.pct} for q in quota_service.snapshot(db, tenant_id)],
                "cost_note": platform_service.COST_NOTE}


@router.get("/{tenant_id}/audit", summary="Platform audit events about this tenant")
def tenant_audit_events(tenant_id: uuid.UUID, page: PageParams = Depends(),
                        ctx: RequestContext = Depends(require_platform("platform.audit.view"))) -> Page[dict]:
    with platform_tx(ctx) as db:
        items, total = platform_service.audit_events(db, category=None, tenant_id=tenant_id, severity=None, start=None,
                                                     end=None, limit=page.limit, offset=page.offset)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.put("/{tenant_id}/quotas")
def set_quotas(tenant_id: uuid.UUID, body: QuotaUpdate, ctx: RequestContext = Depends(require_platform("platform.quotas.manage"))) -> dict:
    vals = body.model_dump(exclude_unset=True)
    reason = vals.pop("reason", None)
    with platform_tx(ctx) as db:
        return tenant_service.set_quotas(db, ctx.platform_security(), tenant_id, vals, reason)


@router.put("/{tenant_id}/features")
def set_feature(tenant_id: uuid.UUID, body: FeatureFlag, ctx: RequestContext = Depends(require_platform("platform.quotas.manage"))) -> dict:
    with platform_tx(ctx) as db:
        tenant_service.set_feature(db, ctx.platform_security(), tenant_id, body.flag, body.enabled)
        return {r[0]: r[1] for r in db.execute(text("SELECT flag, enabled FROM platform.tenant_feature_flags WHERE tenant_id = :t"),
                                               {"t": tenant_id})}


@router.put("/{tenant_id}/subscription")
def change_plan(tenant_id: uuid.UUID, body: PlanChange, ctx: RequestContext = Depends(require_platform("platform.plans.manage"))) -> dict:
    with platform_tx(ctx) as db:
        return tenant_service.change_plan(db, ctx.platform_security(), tenant_id, body.plan_code, body.apply_quotas)


@router.get("/{tenant_id}/admins")
def tenant_admins(tenant_id: uuid.UUID, ctx: RequestContext = Depends(require_platform(VIEW))) -> list[dict]:
    with platform_tx(ctx) as db:
        return tenant_service.tenant_admins(db, ctx.platform_security(), tenant_id)


@router.post("/{tenant_id}/admins", status_code=201, summary="Add a tenant administrator")
def add_tenant_admin(tenant_id: uuid.UUID, body: TenantAdminCreate, ctx: RequestContext = Depends(require_platform(MANAGE))) -> dict:
    with platform_tx(ctx) as db:
        return tenant_service.add_tenant_admin(db, ctx.platform_security(), tenant_id, email=body.email,
                                               display_name=body.display_name, password=body.password)
