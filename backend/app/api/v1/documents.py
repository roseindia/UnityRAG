"""Documents: upload, bulk upload, list, detail, metadata, versions, delete,
download, preview, reprocess / re-index, access (FR-018, FR-052, FR-110,
FR-182..FR-185; extension 7.5)."""
from __future__ import annotations

import json
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from app.api.deps import admin, tx
from app.core.errors import AppError, PermissionDenied, ValidationFailed
from app.dependencies.auth import require, require_any
from app.schemas.admin import AccessEntry, DocumentMetadataUpdate, LegalHold, LifecycleChange
from app.schemas.common import ERROR_RESPONSES, Message, Page, PageParams
from app.security.context import RequestContext
from app.services import document_service
from app.workers.tasks import dispatch_ingestion

router = APIRouter(prefix="/documents", tags=["Documents"], responses=ERROR_RESPONSES)
admin_router = APIRouter(prefix="/admin/documents", tags=["Tenant Admin - Documents"], responses=ERROR_RESPONSES)


def _meta(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationFailed("metadata must be a JSON object") from exc
    if not isinstance(data, dict):
        raise ValidationFailed("metadata must be a JSON object")
    for k in ("effective_from", "effective_to", "review_due_at"):
        if data.get(k):
            try:
                data[k] = date.fromisoformat(data[k])
            except ValueError as exc:
                raise ValidationFailed(f"{k} must be an ISO date") from exc
    return data


def _is_admin(ctx: RequestContext) -> bool:
    return "admin.documents.manage" in ctx.permissions


@router.post("", status_code=202, summary="Upload a document to a collection; returns document and ingestion job ids")
async def upload(collection_id: uuid.UUID = Form(...), file: UploadFile = File(...),
                 metadata: str | None = Form(None, description="JSON object: title, document_type, insurance_line, product, "
                                                                "jurisdictions, classification, effective_from/to, extra{}"),
                 ctx: RequestContext = Depends(require("documents.upload"))) -> dict:
    data = await file.read()
    mode = "tenant_admin" if _is_admin(ctx) else "user"
    with tx(ctx, mode) as db:
        result = document_service.upload(db, ctx.security(mode), collection_id=collection_id, filename=file.filename or "upload",
                                         data=data, metadata=_meta(metadata), admin=_is_admin(ctx))
    dispatch_ingestion(ctx.tenant_id, result["job_id"])  # type: ignore[arg-type]
    return result


@router.post("/bulk", status_code=207, summary="Bulk upload with per-file results")
async def bulk_upload(collection_id: uuid.UUID = Form(...), files: list[UploadFile] = File(...),
                      metadata: str | None = Form(None), ctx: RequestContext = Depends(require("documents.upload"))) -> dict:
    if len(files) > 100:
        raise ValidationFailed("At most 100 files per bulk upload")
    meta = _meta(metadata)
    mode = "tenant_admin" if _is_admin(ctx) else "user"
    results = []
    for f in files:
        data = await f.read()
        try:
            with tx(ctx, mode) as db:
                r = document_service.upload(db, ctx.security(mode), collection_id=collection_id, filename=f.filename or "upload",
                                            data=data, metadata=dict(meta), admin=_is_admin(ctx))
            dispatch_ingestion(ctx.tenant_id, r["job_id"])  # type: ignore[arg-type]
            results.append({**r, "filename": f.filename, "status": "accepted", "ingestion_status": r["status"]})
        except AppError as exc:
            results.append({"filename": f.filename, "status": "rejected", "error": {"code": exc.code, "message": exc.message}})
    return {"results": results, "accepted": sum(r["status"] == "accepted" for r in results), "rejected":
            sum(r["status"] == "rejected" for r in results)}


@router.post("/{document_id}/versions", status_code=202, summary="Upload a new version of an existing document")
async def new_version(document_id: uuid.UUID, file: UploadFile = File(...), metadata: str | None = Form(None),
                      ctx: RequestContext = Depends(require("documents.upload"))) -> dict:
    data = await file.read()
    mode = "tenant_admin" if _is_admin(ctx) else "user"
    with tx(ctx, mode) as db:
        doc = document_service.get_document(db, document_id)
        result = document_service.upload(db, ctx.security(mode), collection_id=doc["collection_id"],
                                         filename=file.filename or "upload", data=data, metadata=_meta(metadata),
                                         document_id=document_id, admin=_is_admin(ctx))
    dispatch_ingestion(ctx.tenant_id, result["job_id"])  # type: ignore[arg-type]
    return result


@router.get("", response_model=Page[dict], summary="Documents visible to the caller")
def list_documents(q: str | None = None, collection_id: uuid.UUID | None = None, document_type: str | None = None,
                   insurance_line: str | None = None, sort: str = "updated_at", page: PageParams = Depends(),
                   ctx: RequestContext = Depends(require("documents.read"))) -> Page[dict]:
    with tx(ctx, "user") as db:
        items, total = document_service.list_documents(db, q=q, collection_id=collection_id, document_type=document_type,
                                                       insurance_line=insurance_line, limit=page.limit,
                                                       offset=page.offset, sort=sort)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/{document_id}")
def get_document(document_id: uuid.UUID, ctx: RequestContext = Depends(require("documents.read"))) -> dict:
    with tx(ctx, "user") as db:
        return document_service.get_document(db, document_id)


@router.put("/{document_id}", summary="Update document metadata (owner or administrator)")
def update_document(document_id: uuid.UUID, body: DocumentMetadataUpdate,
                    ctx: RequestContext = Depends(require_any("documents.manage", "admin.documents.manage"))) -> dict:
    if not _is_admin(ctx):
        # Owners edit via the owner policy; ACL propagation is an administrative operation.
        raise PermissionDenied("Metadata changes that affect access require admin.documents.manage")
    with tx(ctx, "tenant_admin") as db:
        return document_service.update_metadata(db, ctx.security("tenant_admin"), document_id, body.model_dump(exclude_unset=True))


@router.delete("/{document_id}", status_code=202, summary="Withdraw immediately and purge derived data asynchronously")
def delete_document(document_id: uuid.UUID, reason: str | None = None,
                    ctx: RequestContext = Depends(require_any("documents.delete", "admin.documents.manage"))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        if not _is_admin(ctx):
            doc = document_service.get_document(db, document_id)
            if doc["owner_user_id"] != ctx.user_id:
                raise PermissionDenied("Only the owner or an administrator may delete this document")
        job_id = document_service.delete_document(db, ctx.security("tenant_admin"), document_id, reason)
    dispatch_ingestion(ctx.tenant_id, job_id)  # type: ignore[arg-type]
    return {"document_id": document_id, "deletion_job_id": job_id, "status": "withdrawn"}


@router.get("/{document_id}/download", summary="Download the original file (access verified at request time)")
def download(document_id: uuid.UUID, version_id: uuid.UUID | None = None,
             ctx: RequestContext = Depends(require("documents.download"))) -> Response:
    with tx(ctx, "user") as db:
        data, filename, mime = document_service.read_original(db, ctx.security("user"), document_id, version_id)
    safe = "".join(c for c in filename if c.isalnum() or c in "._- ")[:150] or "document"
    return Response(content=data, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="{safe}"', "Cache-Control": "no-store",
        "X-Watermark-User": str(ctx.user_id)})


@router.get("/{document_id}/preview", summary="Preview a page or the page of a cited passage (PII masked)")
def preview(document_id: uuid.UUID, page: int | None = None, chunk_id: uuid.UUID | None = None,
            ctx: RequestContext = Depends(require("documents.read"))) -> dict:
    with tx(ctx, "user") as db:
        return document_service.preview(db, ctx.security("user"), document_id, page, chunk_id)


# ----------------------------------------------------------------- administration
@admin_router.get("", response_model=Page[dict], summary="Document inventory (metadata only, all documents of the tenant)")
def inventory(q: str | None = None, collection_id: uuid.UUID | None = None, lifecycle_state: str | None = None,
              document_type: str | None = None, sort: str = "updated_at", page: PageParams = Depends(),
              ctx: RequestContext = Depends(admin("admin.documents.manage", write=False))) -> Page[dict]:
    with tx(ctx, "tenant_admin") as db:
        items, total = document_service.list_documents(db, q=q, collection_id=collection_id, lifecycle_state=lifecycle_state,
                                                       document_type=document_type, limit=page.limit, offset=page.offset,
                                                       sort=sort)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@admin_router.get("/{document_id}")
def admin_get(document_id: uuid.UUID, ctx: RequestContext = Depends(admin("admin.documents.manage", write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        doc = document_service.get_document(db, document_id)
        doc["access"] = document_service.list_document_access(db, document_id)
        return doc


@admin_router.post("/{document_id}/reprocess", status_code=202, summary="Re-run parsing, chunking and embedding")
def reprocess(document_id: uuid.UUID, ctx: RequestContext = Depends(admin("admin.documents.manage"))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        doc = document_service.get_document(db, document_id)
        version = doc["current_version_id"] or (doc["versions"][0]["version_id"] if doc["versions"] else None)
        job_id = document_service.create_job(db, ctx.security("tenant_admin"), document_id=document_id, version_id=version,
                                             job_type="reprocess")
    dispatch_ingestion(ctx.tenant_id, job_id)  # type: ignore[arg-type]
    return {"job_id": job_id}


@admin_router.post("/{document_id}/reindex", status_code=202, summary="Re-embed with the active embedding model")
def reindex(document_id: uuid.UUID, ctx: RequestContext = Depends(admin("admin.documents.manage"))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        document_service.get_document(db, document_id)
        job_id = document_service.create_job(db, ctx.security("tenant_admin"), document_id=document_id, version_id=None,
                                             job_type="reembed")
    dispatch_ingestion(ctx.tenant_id, job_id)  # type: ignore[arg-type]
    return {"job_id": job_id}


@admin_router.post("/{document_id}/lifecycle", summary="Approve / publish / archive / expire / withdraw")
def lifecycle(document_id: uuid.UUID, body: LifecycleChange, ctx: RequestContext = Depends(admin("admin.documents.manage"))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return document_service.set_lifecycle(db, ctx.security("tenant_admin"), document_id, body.state, body.reason)


@admin_router.put("/{document_id}/access", summary="Replace document-level access rules (propagated to chunks immediately)")
def set_access(document_id: uuid.UUID, body: list[AccessEntry],
               ctx: RequestContext = Depends(admin("admin.documents.manage"))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return document_service.set_document_access(db, ctx.security("tenant_admin"), document_id,
                                                    [e.model_dump() for e in body])


@admin_router.post("/{document_id}/legal-hold", response_model=Message)
def legal_hold(document_id: uuid.UUID, body: LegalHold, ctx: RequestContext = Depends(admin("admin.documents.manage"))) -> Message:
    with tx(ctx, "tenant_admin") as db:
        document_service.set_legal_hold(db, ctx.security("tenant_admin"), document_id, body.hold, body.reason)
    return Message(message="Legal hold updated")
