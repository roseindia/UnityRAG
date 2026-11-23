"""Platform-level tenant lifecycle, subscriptions, quotas and features
(FR-176, FR-178, extension 1.3, 6.2-6.4).

Platform operations run in access mode `platform` (platform tables only).
Operations inside one tenant's identity / configuration tables (provisioning,
managing tenant administrators) switch the SAME transaction to mode
`platform_provisioning` for exactly that tenant; content tables have no policy
for this mode, so platform administrators never read tenant documents or
conversations through these paths (extension 11).
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.database.session import SecurityContext, apply_security_context
from app.services import identity_service
from app.services.audit import platform_audit, tenant_audit

TRANSITIONS = {
    "activate": ({"trial", "suspended", "deactivated"}, "active"),
    "suspend": ({"trial", "active"}, "suspended"),
    "deactivate": ({"trial", "active", "suspended"}, "deactivated"),
    "archive": ({"suspended", "deactivated"}, "archived"),
}
_QUOTA_COLS = ("max_users", "max_documents", "max_storage_bytes", "max_document_size_bytes", "monthly_ai_tokens",
               "monthly_ai_requests", "max_concurrent_chats", "max_ingestion_jobs", "max_collections")


def _platform(sec: SecurityContext) -> SecurityContext:
    return SecurityContext(access_mode="platform", account_id=sec.account_id, platform_role=sec.platform_role)


def _provisioning(sec: SecurityContext, tenant_id: uuid.UUID) -> SecurityContext:
    return SecurityContext(access_mode="platform_provisioning", tenant_id=tenant_id, account_id=sec.account_id,
                           platform_role=sec.platform_role)


def create_tenant(db: Session, sec: SecurityContext, *, code: str, name: str, legal_entity: str | None,
                  plan_code: str, home_region: str = "default", branding: dict | None = None,
                  admin_email: str | None = None, admin_name: str | None = None, admin_password: str | None = None,
                  trial_days: int = 30) -> dict[str, Any]:
    plan = db.execute(text("SELECT * FROM platform.tenant_plans WHERE code = :c AND is_active"), {"c": plan_code}).mappings().first()
    if plan is None:
        raise ValidationFailed(f"Unknown or inactive plan {plan_code}")
    if db.execute(text("SELECT 1 FROM platform.tenants WHERE code = :c"), {"c": code}).first():
        raise Conflict("Tenant code already in use")
    tenant_id = uuid.uuid4()
    status = "trial" if plan_code == "trial" else "active"
    now = datetime.now(UTC)
    db.execute(text("""INSERT INTO platform.tenants (tenant_id, code, name, legal_entity, status, home_region,
                                                     allowed_regions, branding, created_by, activated_at)
                       VALUES (:t, :c, :n, :le, :s, :r, ARRAY[:r], CAST(:b AS jsonb), :by, :act)"""),
               {"t": tenant_id, "c": code, "n": name, "le": legal_entity, "s": status, "r": home_region,
                "b": json.dumps(branding or {}), "by": sec.account_id, "act": now})
    db.execute(text("""INSERT INTO platform.tenant_subscriptions (tenant_id, plan_id, status, trial_ends_at, created_by)
                       VALUES (:t, :p, :s, :te, :by)"""),
               {"t": tenant_id, "p": plan["plan_id"], "s": "trial" if status == "trial" else "active",
                "te": now + timedelta(days=trial_days) if status == "trial" else None, "by": sec.account_id})
    cols = ", ".join(_QUOTA_COLS)
    db.execute(text(f"INSERT INTO platform.tenant_quotas (tenant_id, {cols}, updated_by) "
                    f"SELECT :t, {cols}, :by FROM platform.tenant_plans WHERE plan_id = :p"),
               {"t": tenant_id, "p": plan["plan_id"], "by": sec.account_id})
    db.execute(text("INSERT INTO platform.tenant_usage (tenant_id) VALUES (:t)"), {"t": tenant_id})
    db.execute(text("INSERT INTO platform.tenant_settings (tenant_id, updated_by) VALUES (:t, :by)"),
               {"t": tenant_id, "by": sec.account_id})
    for flag, enabled in (plan["features"] or {}).items():
        db.execute(text("INSERT INTO platform.tenant_feature_flags (tenant_id, flag, enabled, updated_by) VALUES (:t, :f, :e, :by)"),
                   {"t": tenant_id, "f": flag, "e": bool(enabled), "by": sec.account_id})
    platform_audit(db, category="administration", action="tenant_created", actor_account_id=sec.account_id,
                   target_tenant_id=tenant_id, target_type="tenant", target_id=tenant_id,
                   detail={"code": code, "plan": plan_code})

    # --- inside the new tenant: roles, default configuration, first administrator
    prov = _provisioning(sec, tenant_id)
    apply_security_context(db, prov)
    identity_service.install_system_roles(db, tenant_id)
    db.execute(text("INSERT INTO ai.tenant_ai_configurations (tenant_id, version, is_active, change_reason, created_by) "
                    "VALUES (:t, 1, true, 'initial provisioning', NULL)"), {"t": tenant_id})
    db.execute(text("INSERT INTO ai.tenant_rag_configurations (tenant_id, version, is_active, change_reason) "
                    "VALUES (:t, 1, true, 'initial provisioning')"), {"t": tenant_id})
    tenant_audit(db, tenant_id=tenant_id, category="administration", event_type="tenant_provisioned",
                 actor_type="platform_admin", actor_account_id=sec.account_id, resource_type="tenant",
                 resource_id=tenant_id)
    admin = None
    if admin_email:
        admin = identity_service.create_user(db, prov, email=admin_email, display_name=admin_name or admin_email,
                                             password=admin_password, role_codes=["tenant_admin"], clearance_rank=3,
                                             lines_of_business=["*"], jurisdictions=["*"])
    apply_security_context(db, _platform(sec))
    result = get_tenant(db, tenant_id)
    result["initial_admin"] = admin
    return result


def get_tenant(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    row = db.execute(text("""
        SELECT t.*, p.code AS plan_code, p.name AS plan_name, s.status AS subscription_status, s.trial_ends_at,
               u.users_count, u.documents_count, u.collections_count, u.chunks_count, u.storage_bytes,
               u.ai_tokens_month, u.ai_requests_month
          FROM platform.tenants t
          LEFT JOIN platform.tenant_subscriptions s ON s.tenant_id = t.tenant_id AND s.status IN ('trial', 'active', 'past_due')
          LEFT JOIN platform.tenant_plans p ON p.plan_id = s.plan_id
          LEFT JOIN platform.tenant_usage u ON u.tenant_id = t.tenant_id
         WHERE t.tenant_id = :t"""), {"t": tenant_id}).mappings().first()
    if row is None:
        raise NotFound("Tenant not found")
    return dict(row)


def list_tenants(db: Session, *, q: str | None, status: str | None, plan: str | None, limit: int, offset: int,
                 sort: str = "name") -> tuple[list[dict[str, Any]], int]:
    where, params = ["true"], {"limit": limit, "offset": offset}
    if q:
        where.append("(t.name ILIKE :q OR t.code ILIKE :q)")
        params["q"] = f"%{q}%"
    if status:
        where.append("t.status = :status")
        params["status"] = status
    if plan:
        where.append("p.code = :plan")
        params["plan"] = plan
    order = {"name": "t.name", "created_at": "t.created_at DESC", "status": "t.status, t.name",
             "documents": "u.documents_count DESC NULLS LAST", "storage": "u.storage_bytes DESC NULLS LAST",
             "ai_usage": "u.ai_tokens_month DESC NULLS LAST",
             "last_activity": "t.last_activity_at DESC NULLS LAST"}.get(sort, "t.name")
    base = """FROM platform.tenants t
              LEFT JOIN platform.tenant_subscriptions s ON s.tenant_id = t.tenant_id AND s.status IN ('trial','active','past_due')
              LEFT JOIN platform.tenant_plans p ON p.plan_id = s.plan_id
              LEFT JOIN platform.tenant_usage u ON u.tenant_id = t.tenant_id WHERE """ + " AND ".join(where)
    total = db.execute(text("SELECT count(*) " + base), params).scalar_one()
    rows = db.execute(text(f"""SELECT t.tenant_id, t.code, t.name, t.status, t.created_at, t.last_activity_at,
                                      p.code AS plan_code, u.users_count, u.documents_count, u.storage_bytes,
                                      u.ai_tokens_month, u.ai_requests_month {base}
                               ORDER BY {order} LIMIT :limit OFFSET :offset"""), params).mappings().all()
    return [dict(r) for r in rows], int(total)


def update_tenant(db: Session, sec: SecurityContext, tenant_id: uuid.UUID, changes: dict[str, Any]) -> dict[str, Any]:
    allowed = {k: v for k, v in changes.items() if k in {"name", "legal_entity", "home_region"} and v is not None}
    if "branding" in changes and changes["branding"] is not None:
        allowed["branding"] = json.dumps(changes["branding"])
    if allowed:
        sets = ", ".join(f"{k} = CAST(:{k} AS jsonb)" if k == "branding" else f"{k} = :{k}" for k in allowed)
        res = db.execute(text(f"UPDATE platform.tenants SET {sets} WHERE tenant_id = :t"), {**allowed, "t": tenant_id})
        if res.rowcount == 0:
            raise NotFound("Tenant not found")
    platform_audit(db, category="administration", action="tenant_updated", actor_account_id=sec.account_id,
                   target_tenant_id=tenant_id, target_type="tenant", target_id=tenant_id,
                   detail={"changed": sorted(allowed)})
    return get_tenant(db, tenant_id)


def transition(db: Session, sec: SecurityContext, tenant_id: uuid.UUID, action: str, reason: str) -> dict[str, Any]:
    if action not in TRANSITIONS:
        raise ValidationFailed("Unknown lifecycle action")
    if not reason or len(reason.strip()) < 10:
        raise ValidationFailed("A reason of at least 10 characters is required for lifecycle changes")
    allowed_from, target = TRANSITIONS[action]
    tenant = get_tenant(db, tenant_id)
    if tenant["status"] not in allowed_from:
        raise Conflict(f"Cannot {action} a tenant in status {tenant['status']}")
    extra = {"activate": ", activated_at = now(), suspended_at = NULL", "suspend": ", suspended_at = now()",
             "deactivate": ", suspended_at = COALESCE(suspended_at, now())",
             "archive": ", archived_at = now(), retention_until = (now() + interval '7 years')::date"}[action]
    db.execute(text(f"UPDATE platform.tenants SET status = :s, status_reason = :r {extra} WHERE tenant_id = :t"),
               {"s": target, "r": reason, "t": tenant_id})
    if action in ("suspend", "deactivate", "archive"):
        # Active sessions of the tenant stop working immediately (request-time
        # validation already refuses non-operational tenants; this also ends them).
        db.execute(text("UPDATE iam.sessions SET revoked_at = now(), revoked_reason = :r "
                        "WHERE tenant_id = :t AND revoked_at IS NULL"), {"r": f"tenant_{target}", "t": tenant_id})
    platform_audit(db, category="administration", action=f"tenant_{action}", severity="medium",
                   actor_account_id=sec.account_id, target_tenant_id=tenant_id, target_type="tenant",
                   target_id=tenant_id, reason=reason, detail={"from": tenant["status"], "to": target})
    return get_tenant(db, tenant_id)


def set_quotas(db: Session, sec: SecurityContext, tenant_id: uuid.UUID, quotas: dict[str, int], reason: str | None) -> dict[str, Any]:
    vals = {k: v for k, v in quotas.items() if k in _QUOTA_COLS and v is not None}
    if not vals:
        raise ValidationFailed("No quota values supplied")
    if any(v < 0 for v in vals.values()):
        raise ValidationFailed("Quota values must be non-negative")
    before = dict(db.execute(text("SELECT * FROM platform.tenant_quotas WHERE tenant_id = :t"), {"t": tenant_id}).mappings().first() or {})
    if not before:
        raise NotFound("Tenant not found")
    sets = ", ".join(f"{k} = :{k}" for k in vals)
    db.execute(text(f"UPDATE platform.tenant_quotas SET {sets}, updated_by = :by, updated_at = now() WHERE tenant_id = :t"),
               {**vals, "by": sec.account_id, "t": tenant_id})
    platform_audit(db, category="configuration", action="tenant_quotas_updated", actor_account_id=sec.account_id,
                   target_tenant_id=tenant_id, target_type="tenant_quotas", target_id=tenant_id, reason=reason,
                   detail={"before": {k: before.get(k) for k in vals}, "after": vals})
    return dict(db.execute(text("SELECT * FROM platform.tenant_quotas WHERE tenant_id = :t"), {"t": tenant_id}).mappings().one())


def set_feature(db: Session, sec: SecurityContext, tenant_id: uuid.UUID, flag: str, enabled: bool) -> None:
    db.execute(text("""INSERT INTO platform.tenant_feature_flags (tenant_id, flag, enabled, updated_by)
                       VALUES (:t, :f, :e, :by) ON CONFLICT (tenant_id, flag)
                       DO UPDATE SET enabled = EXCLUDED.enabled, updated_by = EXCLUDED.updated_by, updated_at = now()"""),
               {"t": tenant_id, "f": flag, "e": enabled, "by": sec.account_id})
    platform_audit(db, category="configuration", action="tenant_feature_set", actor_account_id=sec.account_id,
                   target_tenant_id=tenant_id, target_type="feature_flag", target_id=flag, detail={"enabled": enabled})


def change_plan(db: Session, sec: SecurityContext, tenant_id: uuid.UUID, plan_code: str, apply_quotas: bool) -> dict[str, Any]:
    plan = db.execute(text("SELECT * FROM platform.tenant_plans WHERE code = :c AND is_active"), {"c": plan_code}).mappings().first()
    if plan is None:
        raise ValidationFailed("Unknown plan")
    db.execute(text("UPDATE platform.tenant_subscriptions SET status = 'cancelled', ends_at = now() "
                    "WHERE tenant_id = :t AND status IN ('trial','active','past_due')"), {"t": tenant_id})
    db.execute(text("INSERT INTO platform.tenant_subscriptions (tenant_id, plan_id, status, created_by) VALUES (:t, :p, 'active', :by)"),
               {"t": tenant_id, "p": plan["plan_id"], "by": sec.account_id})
    if apply_quotas:
        sets = ", ".join(f"{c} = p.{c}" for c in _QUOTA_COLS)
        db.execute(text(f"UPDATE platform.tenant_quotas q SET {sets}, updated_by = :by, updated_at = now() "
                        "FROM platform.tenant_plans p WHERE p.plan_id = :p AND q.tenant_id = :t"),
                   {"p": plan["plan_id"], "t": tenant_id, "by": sec.account_id})
    platform_audit(db, category="administration", action="tenant_plan_changed", actor_account_id=sec.account_id,
                   target_tenant_id=tenant_id, target_type="subscription", target_id=plan_code,
                   detail={"apply_quotas": apply_quotas})
    return get_tenant(db, tenant_id)


def tenant_admins(db: Session, sec: SecurityContext, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    get_tenant(db, tenant_id)
    apply_security_context(db, _provisioning(sec, tenant_id))
    rows = db.execute(text("""SELECT u.user_id, u.email::text AS email, u.display_name, u.status, ur.granted_at
                                FROM iam.user_roles ur JOIN iam.roles r ON r.role_id = ur.role_id
                                JOIN iam.users u ON u.user_id = ur.user_id
                               WHERE r.code = 'tenant_admin' ORDER BY u.display_name""")).mappings().all()
    apply_security_context(db, _platform(sec))
    return [dict(r) for r in rows]


def add_tenant_admin(db: Session, sec: SecurityContext, tenant_id: uuid.UUID, *, email: str, display_name: str,
                     password: str | None) -> dict[str, Any]:
    get_tenant(db, tenant_id)
    prov = _provisioning(sec, tenant_id)
    apply_security_context(db, prov)
    existing = db.execute(text("SELECT user_id FROM iam.users WHERE email = :e"), {"e": email.lower()}).scalar()
    if existing:
        identity_service.assign_role(db, prov, existing, role_code="tenant_admin")
        user = identity_service.get_user(db, existing)
    else:
        user = identity_service.create_user(db, prov, email=email, display_name=display_name, password=password,
                                            role_codes=["tenant_admin"], clearance_rank=3,
                                            lines_of_business=["*"], jurisdictions=["*"])
    apply_security_context(db, _platform(sec))
    platform_audit(db, category="administration", action="tenant_admin_added", actor_account_id=sec.account_id,
                   target_tenant_id=tenant_id, target_type="user", target_id=user["user_id"])
    return user


def tenant_usage_series(db: Session, tenant_id: uuid.UUID, start: date, end: date) -> list[dict[str, Any]]:
    rows = db.execute(text("""SELECT * FROM ops.tenant_usage_daily WHERE tenant_id = :t AND usage_date BETWEEN :s AND :e
                              ORDER BY usage_date"""), {"t": tenant_id, "s": start, "e": end}).mappings().all()
    return [dict(r) for r in rows]
