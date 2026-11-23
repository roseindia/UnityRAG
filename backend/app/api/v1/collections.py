"""Collections (FR-167; extension 7.6)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import admin, tx
from app.dependencies.auth import require
from app.schemas.admin import CollectionCreate, CollectionGrant, CollectionUpdate
from app.schemas.common import ERROR_RESPONSES, Message
from app.security.context import RequestContext
from app.services import document_service

router = APIRouter(prefix="/collections", tags=["Collections"], responses=ERROR_RESPONSES)
admin_router = APIRouter(prefix="/admin/collections", tags=["Tenant Admin - Collections"], responses=ERROR_RESPONSES)
MANAGE = "admin.collections.manage"


@router.get("", summary="Collections the caller may use")
def my_collections(ctx: RequestContext = Depends(require("collections.read"))) -> list[dict]:
    with tx(ctx, "user") as db:
        return document_service.list_collections(db)


@admin_router.get("")
def list_all(ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> list[dict]:
    with tx(ctx, "tenant_admin") as db:
        return document_service.list_collections(db)


@admin_router.post("", status_code=201)
def create(body: CollectionCreate, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return document_service.create_collection(db, ctx.security("tenant_admin"), body.model_dump())


@admin_router.get("/{collection_id}")
def get(collection_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return document_service.get_collection(db, collection_id)


@admin_router.put("/{collection_id}")
def update(collection_id: uuid.UUID, body: CollectionUpdate, ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return document_service.update_collection(db, ctx.security("tenant_admin"), collection_id,
                                                  body.model_dump(exclude_unset=True))


@admin_router.delete("/{collection_id}", response_model=Message)
def delete(collection_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE))) -> Message:
    with tx(ctx, "tenant_admin") as db:
        document_service.delete_collection(db, ctx.security("tenant_admin"), collection_id)
    return Message(message="Collection deleted")


@admin_router.put("/{collection_id}/access", summary="Assign users / groups / roles / departments to a collection")
def set_access(collection_id: uuid.UUID, body: list[CollectionGrant], ctx: RequestContext = Depends(admin(MANAGE))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return document_service.set_collection_access(db, ctx.security("tenant_admin"), collection_id,
                                                      [g.model_dump() for g in body])


@admin_router.get("/{collection_id}/stats", summary="Collection statistics and ingestion monitoring")
def stats(collection_id: uuid.UUID, ctx: RequestContext = Depends(admin(MANAGE, write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return document_service.collection_stats(db, collection_id)
