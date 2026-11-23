"""Tenant Admin: departments and teams (extension 7.4)."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import admin, tx
from app.schemas.admin import DepartmentCreate, DepartmentUpdate, MemberRef, TeamCreate
from app.schemas.common import ERROR_RESPONSES, Message
from app.security.context import RequestContext
from app.services import analytics_service, identity_service

router = APIRouter(prefix="/admin", tags=["Tenant Admin - Departments & Teams"], responses=ERROR_RESPONSES)
MANAGE = "admin.departments.manage"


@router.get("/departments")
def list_departments(ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> list[dict]:
    with tx(ctx, "tenant_admin") as db:
        return [dict(r) for r in db.execute(text("""
            SELECT d.*, (SELECT count(*) FROM iam.users u WHERE u.department_id = d.department_id) AS user_count,
                   (SELECT count(*) FROM iam.teams t WHERE t.department_id = d.department_id) AS team_count
              FROM iam.departments d ORDER BY d.name""")).mappings()]


@router.post("/departments", status_code=201)
def create_department(body: DepartmentCreate, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return identity_service.create_department(db, ctx.security("tenant_admin"), body.code, body.name, body.description,
                                                  body.parent_department_id)


@router.put("/departments/{department_id}")
def update_department(department_id: uuid.UUID, body: DepartmentUpdate, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return identity_service.update_department(db, ctx.security("tenant_admin"), department_id,
                                                  body.model_dump(exclude_unset=True))


@router.get("/departments/{department_id}/usage", summary="Department usage statistics")
def department_usage(department_id: uuid.UUID, start: date | None = None, end: date | None = None,
                     ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return analytics_service.department_dashboard(db, department_id, start, end)


@router.get("/teams")
def list_teams(department_id: uuid.UUID | None = None, ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> list[dict]:
    with tx(ctx, "tenant_admin") as db:
        return [dict(r) for r in db.execute(text("""SELECT t.*, (SELECT count(*) FROM iam.team_members m WHERE m.team_id = t.team_id) AS members
                                                      FROM iam.teams t WHERE (CAST(:d AS uuid) IS NULL OR t.department_id = :d)
                                                     ORDER BY t.name"""), {"d": department_id}).mappings()]


@router.post("/teams", status_code=201)
def create_team(body: TeamCreate, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return identity_service.create_team(db, ctx.security("tenant_admin"), body.department_id, body.name, body.description)


@router.post("/teams/{team_id}/members", response_model=Message)
def add_team_member(team_id: uuid.UUID, body: MemberRef, ctx: RequestContext = Depends(admin(MANAGE))) -> Message:
    with tx(ctx, "tenant_admin") as db:
        identity_service.add_team_member(db, ctx.security("tenant_admin"), team_id, body.user_id)
    return Message(message="Member added")
