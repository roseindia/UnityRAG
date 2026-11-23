"""Platform Super Admin Console APIs: dashboard, analytics, plans, platform users,
AI providers, model catalogue, monitoring, jobs, audit, security events,
settings and break-glass (extension 6, 8, 9, 11)."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import platform_tx
from app.core.errors import NotFound, ValidationFailed
from app.dependencies.auth import require_platform
from app.schemas.common import ERROR_RESPONSES, Page, PageParams
from app.schemas.platform import (
    BreakGlassRequest,
    ModelCreate,
    ModelUpdate,
    PlanUpsert,
    PlatformSetting,
    PlatformUserSet,
    ProviderUpdate,
    ProviderUpsert,
)
from app.security.context import RequestContext
from app.services import platform_service
from app.services.audit import platform_audit
from app.utils.clock import utc_today

router = APIRouter(prefix="/platform", tags=["Platform Admin"], responses=ERROR_RESPONSES)


@router.get("/dashboard", summary="Platform dashboard (aggregated, tenant-aware, no tenant content)")
def dashboard(start: date | None = None, end: date | None = None, tenant_id: uuid.UUID | None = None,
              ctx: RequestContext = Depends(require_platform("platform.dashboard.view"))) -> dict:
    with platform_tx(ctx) as db:
        return platform_service.dashboard(db, start, end, tenant_id)


@router.get("/analytics", summary="Usage comparison across tenants")
def analytics(start: date | None = None, end: date | None = None,
              ctx: RequestContext = Depends(require_platform("platform.dashboard.view"))) -> dict:
    with platform_tx(ctx) as db:
        end = end or utc_today()
        start = start or date.fromordinal(end.toordinal() - 29)
        rows = [dict(r) for r in db.execute(text("""
            SELECT t.tenant_id, t.code, t.name, t.status, COALESCE(sum(u.searches), 0) AS searches, COALESCE(sum(u.chats), 0) AS chats,
                   COALESCE(sum(u.ai_requests), 0) AS ai_requests, COALESCE(sum(u.input_tokens + u.output_tokens), 0) AS tokens,
                   COALESCE(sum(u.estimated_cost), 0) AS estimated_cost, COALESCE(max(u.active_users), 0) AS peak_active_users,
                   round(avg(u.avg_search_latency_ms)) AS avg_search_latency_ms
              FROM platform.tenants t LEFT JOIN ops.tenant_usage_daily u ON u.tenant_id = t.tenant_id
                   AND u.usage_date BETWEEN :s AND :e
             GROUP BY t.tenant_id ORDER BY tokens DESC"""), {"s": start, "e": end}).mappings()]
    return {"range": {"start": start, "end": end}, "tenants": rows, "cost_note": platform_service.COST_NOTE}


@router.get("/monitoring", summary="API, PostgreSQL, Redis, worker, queue and provider health")
def monitoring(ctx: RequestContext = Depends(require_platform("platform.monitoring.view"))) -> dict:
    with platform_tx(ctx) as db:
        return platform_service.monitoring(db)


@router.get("/jobs", summary="Background workers, queue depth and per-tenant ingestion activity")
def jobs(ctx: RequestContext = Depends(require_platform("platform.monitoring.view"))) -> dict:
    with platform_tx(ctx) as db:
        return platform_service.jobs_overview(db)


# --- plans -------------------------------------------------------------------------
@router.get("/plans")
def plans(ctx: RequestContext = Depends(require_platform("platform.tenants.view"))) -> list[dict]:
    with platform_tx(ctx) as db:
        return [dict(r) for r in db.execute(text("""SELECT p.*, (SELECT count(*) FROM platform.tenant_subscriptions s
                                                     WHERE s.plan_id = p.plan_id AND s.status IN ('trial','active')) AS tenants
                                                     FROM platform.tenant_plans p ORDER BY monthly_price""")).mappings()]


@router.put("/plans/{code}", summary="Create or update a subscription plan")
def upsert_plan(code: str, body: PlanUpsert, ctx: RequestContext = Depends(require_platform("platform.plans.manage"))) -> dict:
    if code != body.code:
        raise ValidationFailed("code in path and body must match")
    data = body.model_dump()
    data["features"] = json.dumps(data["features"])
    cols = list(data)
    with platform_tx(ctx) as db:
        db.execute(text(f"""INSERT INTO platform.tenant_plans ({', '.join(cols)})
                            VALUES ({', '.join('CAST(:features AS jsonb)' if c == 'features' else ':' + c for c in cols)})
                            ON CONFLICT (code) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in cols if c != 'code')},
                                   updated_at = now()"""), data)
        platform_audit(db, category="configuration", action="plan_upserted", actor_account_id=ctx.account_id,
                       target_type="plan", target_id=code)
        return dict(db.execute(text("SELECT * FROM platform.tenant_plans WHERE code = :c"), {"c": code}).mappings().one())


# --- platform users -------------------------------------------------------------------
@router.get("/users")
def platform_users(ctx: RequestContext = Depends(require_platform("platform.users.manage"))) -> list[dict]:
    with platform_tx(ctx) as db:
        return platform_service.list_platform_users(db)


@router.put("/users", summary="Create / update a platform administrator")
def set_platform_user(body: PlatformUserSet, ctx: RequestContext = Depends(require_platform("platform.users.manage"))) -> dict:
    with platform_tx(ctx) as db:
        return platform_service.set_platform_user(db, ctx.platform_security(), email=body.email,
                                                  display_name=body.display_name, role=body.role,
                                                  password=body.password, status=body.status)


# --- AI providers and catalogue ------------------------------------------------------------
@router.get("/ai-providers", summary="AI providers (secrets masked)")
def providers(ctx: RequestContext = Depends(require_platform("platform.ai.manage"))) -> list[dict]:
    with platform_tx(ctx) as db:
        return platform_service.list_providers(db)


@router.post("/ai-providers", status_code=201)
def create_provider(body: ProviderUpsert, ctx: RequestContext = Depends(require_platform("platform.ai.manage"))) -> dict:
    with platform_tx(ctx) as db:
        return platform_service.upsert_provider(db, ctx.platform_security(), body.model_dump())


@router.put("/ai-providers/{provider_id}")
def update_provider(provider_id: uuid.UUID, body: ProviderUpdate,
                    ctx: RequestContext = Depends(require_platform("platform.ai.manage"))) -> dict:
    with platform_tx(ctx) as db:
        return platform_service.upsert_provider(db, ctx.platform_security(), body.model_dump(exclude_unset=True), provider_id)


@router.post("/ai-providers/{provider_id}/health-check")
def provider_health(provider_id: uuid.UUID, ctx: RequestContext = Depends(require_platform("platform.ai.manage"))) -> dict:
    with platform_tx(ctx) as db:
        return platform_service.check_provider(db, ctx.platform_security(), provider_id)


@router.get("/models", summary="Model catalogue")
def models(purpose: str | None = None, ctx: RequestContext = Depends(require_platform("platform.ai.manage"))) -> list[dict]:
    with platform_tx(ctx) as db:
        return platform_service.list_models(db, purpose)


@router.post("/models", status_code=201)
def create_model(body: ModelCreate, ctx: RequestContext = Depends(require_platform("platform.ai.manage"))) -> dict:
    with platform_tx(ctx) as db:
        return platform_service.upsert_model(db, ctx.platform_security(), body.model_dump())


@router.put("/models/{model_id}", summary="Approve / activate / deprecate a model or change pricing")
def update_model(model_id: uuid.UUID, body: ModelUpdate, ctx: RequestContext = Depends(require_platform("platform.ai.manage"))) -> dict:
    with platform_tx(ctx) as db:
        return platform_service.upsert_model(db, ctx.platform_security(), body.model_dump(exclude_unset=True), model_id)


# --- settings ------------------------------------------------------------------------------
@router.get("/settings")
def settings(ctx: RequestContext = Depends(require_platform("platform.settings.manage"))) -> dict:
    with platform_tx(ctx) as db:
        return {r[0]: r[1] for r in db.execute(text("SELECT key, value FROM platform.platform_settings ORDER BY key"))}


@router.put("/settings/{key}")
def put_setting(key: str, body: PlatformSetting, ctx: RequestContext = Depends(require_platform("platform.settings.manage"))) -> dict:
    with platform_tx(ctx) as db:
        db.execute(text("""INSERT INTO platform.platform_settings (key, value, updated_by) VALUES (:k, CAST(:v AS jsonb), :by)
                           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = now()"""),
                   {"k": key, "v": json.dumps(body.value), "by": ctx.account_id})
        platform_audit(db, category="configuration", action="platform_setting_changed", actor_account_id=ctx.account_id,
                       target_type="platform_setting", target_id=key)
    return {"key": key, "value": body.value}


# --- audit & security ----------------------------------------------------------------------
@router.get("/audit", response_model=Page[dict])
def audit(category: str | None = None, tenant_id: uuid.UUID | None = None, severity: str | None = None,
          start: datetime | None = None, end: datetime | None = None, page: PageParams = Depends(),
          ctx: RequestContext = Depends(require_platform("platform.audit.view"))) -> Page[dict]:
    with platform_tx(ctx) as db:
        items, total = platform_service.audit_events(db, category=category, tenant_id=tenant_id, severity=severity,
                                                     start=start, end=end, limit=page.limit, offset=page.offset)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/security-events", response_model=Page[dict], summary="Security events and privileged (break-glass) access")
def security_events(page: PageParams = Depends(), ctx: RequestContext = Depends(require_platform("platform.security.view"))) -> Page[dict]:
    with platform_tx(ctx) as db:
        items, total = platform_service.audit_events(db, category="security", tenant_id=None, severity=None, start=None,
                                                     end=None, limit=page.limit, offset=page.offset)
        grants = [dict(r) for r in db.execute(text("""SELECT grant_id, account_id, tenant_id, reason, scope, starts_at, expires_at,
                                                             ended_at, status, jsonb_array_length(resources_accessed) AS accesses
                                                        FROM platform.break_glass_grants ORDER BY created_at DESC LIMIT 50""")).mappings()]
    return Page(items=items + [{"break_glass_grant": g} for g in grants], total=total + len(grants), limit=page.limit,
                offset=page.offset)


# --- break-glass ------------------------------------------------------------------------------
@router.post("/break-glass", status_code=201, summary="Open a time-limited, audited support-access grant")
def open_break_glass(body: BreakGlassRequest, ctx: RequestContext = Depends(require_platform("platform.break_glass.use"))) -> dict:
    if not body.confirm:
        raise ValidationFailed("Break-glass access requires explicit confirmation")
    with platform_tx(ctx) as db:
        return platform_service.open_break_glass(db, ctx.platform_security(), body.tenant_id, body.reason, body.minutes,
                                                 list(body.scope))


@router.post("/break-glass/{grant_id}/close")
def close_break_glass(grant_id: uuid.UUID, ctx: RequestContext = Depends(require_platform("platform.break_glass.use"))) -> dict:
    with platform_tx(ctx) as db:
        return platform_service.close_break_glass(db, ctx.platform_security(), grant_id)


@router.get("/break-glass/{grant_id}/{resource}", summary="Read tenant data under an active grant (documents | document | conversation)")
def break_glass_read(grant_id: uuid.UUID, resource: str, resource_id: uuid.UUID | None = None,
                     ctx: RequestContext = Depends(require_platform("platform.break_glass.use"))) -> dict:
    if resource not in ("documents", "document", "conversation"):
        raise NotFound("unknown resource")
    with platform_tx(ctx) as db:
        return platform_service.break_glass_read(db, ctx.platform_security(), grant_id, resource, resource_id)
