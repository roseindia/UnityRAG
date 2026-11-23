"""Tenant Admin: user administration (extension 7.2, FR-163, FR-190)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import admin, tx
from app.schemas.admin import RoleAssign, UserCreate, UserUpdate
from app.schemas.common import ERROR_RESPONSES, Message, Page, PageParams
from app.security.context import RequestContext
from app.services import auth_service, identity_service

router = APIRouter(prefix="/admin/users", tags=["Tenant Admin - Users"], responses=ERROR_RESPONSES)
MANAGE = "admin.users.manage"


@router.get("", response_model=Page[dict], summary="List / search users of the active tenant")
def list_users(q: str | None = None, status: str | None = None, department_id: uuid.UUID | None = None,
               sort: str = "display_name", page: PageParams = Depends(),
               ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> Page[dict]:
    with tx(ctx, "tenant_admin") as db:
        items, total = identity_service.list_users(db, q=q, status=status, department_id=department_id,
                                                   limit=page.limit, offset=page.offset, sort=sort)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("", status_code=201, summary="Create a user (or add an existing identity to this tenant)")
def create_user(body: UserCreate, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    if "tenant_admin" in body.roles and "admin.roles.manage" not in ctx.permissions:
        from app.core.errors import PermissionDenied

        raise PermissionDenied("Assigning the tenant_admin role requires admin.roles.manage")
    with tx(ctx, "tenant_admin") as db:
        return identity_service.create_user(
            db, ctx.security("tenant_admin"), email=body.email, display_name=body.display_name, password=body.password,
            auth_provider=body.auth_provider, external_subject=body.external_subject, user_type=body.user_type,
            department_id=body.department_id, business_unit=body.business_unit, country=body.country,
            lines_of_business=body.lines_of_business, jurisdictions=body.jurisdictions,
            clearance_rank=body.clearance_rank, role_codes=body.roles, group_ids=body.group_ids)


@router.get("/{user_id}")
def get_user(user_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        user = identity_service.get_user(db, user_id)
        user["effective_permissions"] = identity_service.effective_permissions(db, user_id)
        return user


@router.put("/{user_id}")
def update_user(user_id: uuid.UUID, body: UserUpdate, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return identity_service.update_user(db, ctx.security("tenant_admin"), user_id, body.model_dump(exclude_unset=True))


@router.post("/{user_id}/activate")
def activate(user_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return identity_service.set_user_status(db, ctx.security("tenant_admin"), user_id, True)


@router.post("/{user_id}/deactivate", summary="Deactivate a user; active sessions are revoked immediately")
def deactivate(user_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return identity_service.set_user_status(db, ctx.security("tenant_admin"), user_id, False)


@router.post("/{user_id}/revoke-sessions", response_model=Message)
def revoke_sessions(user_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE))) -> Message:
    with tx(ctx, "tenant_admin") as db:
        n = identity_service.revoke_sessions(db, ctx.security("tenant_admin"), user_id)
    return Message(message=f"{n} session(s) revoked")


@router.post("/{user_id}/password-reset", summary="Issue a single-use password reset token (secure workflow)")
def password_reset(user_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        user = identity_service.get_user(db, user_id)
        identity_service._audit(db, ctx.security("tenant_admin"), "password_reset_issued", "user", user_id, category="security")
    token = auth_service.create_password_reset(ctx.security("tenant_admin"), user["account_id"])
    return {"user_id": user_id, "reset_token": token, "expires_in_minutes": auth_service.get_settings().password_reset_minutes,
            "delivery": "Return the token to the user through an approved out-of-band channel; it is shown only once."}


@router.post("/{user_id}/roles", response_model=Message)
def assign_role(user_id: uuid.UUID, body: RoleAssign, ctx: RequestContext = Depends(admin("admin.roles.manage"))) -> Message:
    with tx(ctx, "tenant_admin") as db:
        identity_service.assign_role(db, ctx.security("tenant_admin"), user_id, role_code=body.role_code,
                                     role_id=body.role_id, valid_to=body.valid_to)
    return Message(message="Role assigned")


@router.delete("/{user_id}/roles/{role_id}", response_model=Message)
def unassign_role(user_id: uuid.UUID, role_id: uuid.UUID, ctx: RequestContext = Depends(admin("admin.roles.manage"))) -> Message:
    with tx(ctx, "tenant_admin") as db:
        identity_service.unassign_role(db, ctx.security("tenant_admin"), user_id, role_id)
    return Message(message="Role removed")


@router.get("/{user_id}/activity", summary="User activity (daily aggregates) and recent audit events")
def activity(user_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        identity_service.get_user(db, user_id)
        daily = [dict(r) for r in db.execute(text("""SELECT usage_date, searches, chats, tokens FROM ops.user_activity_daily
                                                       WHERE user_id = :u ORDER BY usage_date DESC LIMIT 90"""), {"u": user_id}).mappings()]
        events = [dict(r) for r in db.execute(text("""SELECT occurred_at, category, event_type, outcome, resource_type
                                                        FROM audit.tenant_audit_logs WHERE actor_user_id = :u
                                                       ORDER BY occurred_at DESC LIMIT 100"""), {"u": user_id}).mappings()]
    return {"user_id": user_id, "daily": daily, "recent_events": events}


@router.get("/{user_id}/logins", summary="Login history")
def logins(user_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> list[dict]:
    with tx(ctx, "tenant_admin") as db:
        user = identity_service.get_user(db, user_id)
        return [dict(r) for r in db.execute(text("""SELECT occurred_at, success, reason, auth_method, host(ip) AS ip
                                                      FROM iam.login_events WHERE account_id = :a
                                                     ORDER BY occurred_at DESC LIMIT 100"""), {"a": user["account_id"]}).mappings()]
