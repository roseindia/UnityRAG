"""Permission catalogue and effective permissions (extension 7.3)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import admin, tx
from app.schemas.common import ERROR_RESPONSES
from app.security.context import RequestContext
from app.services import identity_service

router = APIRouter(prefix="/admin/permissions", tags=["Tenant Admin - Roles"], responses=ERROR_RESPONSES)


@router.get("", summary="Permission catalogue")
def catalogue(ctx: RequestContext = Depends(admin("admin.roles.manage", write=False))) -> list[dict]:
    with tx(ctx, "tenant_admin") as db:
        return [dict(r) for r in db.execute(text("SELECT * FROM iam.permissions ORDER BY category, permission_code")).mappings()]


@router.get("/effective/{user_id}", summary="Effective permissions of a user")
def effective(user_id: uuid.UUID, ctx: RequestContext = Depends(admin("admin.roles.manage", write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        identity_service.get_user(db, user_id)
        return {"user_id": user_id, "permissions": identity_service.effective_permissions(db, user_id)}
