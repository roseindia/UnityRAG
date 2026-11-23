"""Tenant Admin: roles and permission matrix (extension 7.3, FR-165, FR-191)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import admin, tx
from app.schemas.admin import RoleCreate, RoleUpdate
from app.schemas.common import ERROR_RESPONSES, Message
from app.security.context import RequestContext
from app.services import identity_service

router = APIRouter(prefix="/admin/roles", tags=["Tenant Admin - Roles"], responses=ERROR_RESPONSES)
MANAGE = "admin.roles.manage"


@router.get("", summary="Roles with their permissions (permission matrix)")
def list_roles(ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> list[dict]:
    with tx(ctx, "tenant_admin") as db:
        return identity_service.list_roles(db)


@router.post("", status_code=201, summary="Create a custom role")
def create_role(body: RoleCreate, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return identity_service.create_role(db, ctx.security("tenant_admin"), code=body.code, name=body.name,
                                            description=body.description, permissions=body.permissions,
                                            conflicts_with=body.conflicts_with)


@router.put("/{role_id}", summary="Edit a custom role (system roles are protected)")
def update_role(role_id: uuid.UUID, body: RoleUpdate, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return identity_service.update_role(db, ctx.security("tenant_admin"), role_id, name=body.name,
                                            description=body.description, permissions=body.permissions)


@router.delete("/{role_id}", response_model=Message)
def delete_role(role_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE))) -> Message:
    with tx(ctx, "tenant_admin") as db:
        identity_service.delete_role(db, ctx.security("tenant_admin"), role_id)
    return Message(message="Role deleted")
