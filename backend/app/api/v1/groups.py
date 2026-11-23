"""Tenant Admin: user groups (extension 7.4, FR-164)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import admin, tx
from app.schemas.admin import GroupCreate, MemberRef
from app.schemas.common import ERROR_RESPONSES, Message
from app.security.context import RequestContext
from app.services import identity_service

router = APIRouter(prefix="/admin/groups", tags=["Tenant Admin - Groups"], responses=ERROR_RESPONSES)
MANAGE = "admin.groups.manage"


@router.get("")
def list_groups(ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> list[dict]:
    with tx(ctx, "tenant_admin") as db:
        return [dict(r) for r in db.execute(text("""SELECT g.*, (SELECT count(*) FROM iam.user_group_members m
                                                                  WHERE m.group_id = g.group_id) AS member_count
                                                      FROM iam.user_groups g ORDER BY g.name""")).mappings()]


@router.post("", status_code=201)
def create_group(body: GroupCreate, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return identity_service.create_group(db, ctx.security("tenant_admin"), body.name, body.description)


@router.get("/{group_id}/members")
def members(group_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> list[dict]:
    with tx(ctx, "tenant_admin") as db:
        return [dict(r) for r in db.execute(text("""SELECT u.user_id, u.email::text AS email, u.display_name, m.valid_from, m.valid_to
                                                      FROM iam.user_group_members m JOIN iam.users u ON u.user_id = m.user_id
                                                     WHERE m.group_id = :g ORDER BY u.display_name"""), {"g": group_id}).mappings()]


@router.post("/{group_id}/members", response_model=Message)
def add_member(group_id: uuid.UUID, body: MemberRef, ctx: RequestContext = Depends(admin(MANAGE))) -> Message:
    with tx(ctx, "tenant_admin") as db:
        identity_service.add_group_member(db, ctx.security("tenant_admin"), group_id, body.user_id)
    return Message(message="Member added")


@router.delete("/{group_id}/members/{user_id}", response_model=Message)
def remove_member(group_id: uuid.UUID, user_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE))) -> Message:
    with tx(ctx, "tenant_admin") as db:
        identity_service.remove_group_member(db, ctx.security("tenant_admin"), group_id, user_id)
    return Message(message="Member removed")
