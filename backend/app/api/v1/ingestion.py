"""Ingestion monitoring and control (FR-053, FR-183, FR-184)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.api.deps import admin, tx
from app.core.errors import Conflict, NotFound
from app.dependencies.auth import get_tenant_context
from app.schemas.common import ERROR_RESPONSES, Page, PageParams
from app.security.context import RequestContext
from app.workers.tasks import dispatch_ingestion

router = APIRouter(tags=["Ingestion"], responses=ERROR_RESPONSES)
_COLS = """job_id, document_id, version_id, job_type, status, stage, attempt, max_attempts, priority, error_code,
           error_message, stats, queued_at, started_at, finished_at, next_retry_at, correlation_id"""


@router.get("/ingestion/jobs/{job_id}", summary="Status of an ingestion job (own jobs, or any for administrators)")
def job_status(job_id: uuid.UUID, ctx: RequestContext = Depends(get_tenant_context)) -> dict:
    mode = "tenant_admin" if "admin.ingestion.manage" in ctx.permissions else "user"
    with tx(ctx, mode) as db:
        row = db.execute(text(f"SELECT {_COLS} FROM ingest.ingestion_jobs WHERE job_id = :j"), {"j": job_id}).mappings().first()
        if row is None:
            raise NotFound("Job not found")
        logs = [dict(r) for r in db.execute(text("""SELECT stage, level, message, detail, created_at FROM ingest.ingestion_job_logs
                                                      WHERE job_id = :j ORDER BY created_at"""), {"j": job_id}).mappings()]
    return dict(row) | {"logs": logs}


@router.get("/admin/ingestion/jobs", response_model=Page[dict], summary="Ingestion monitoring")
def list_jobs(status: str | None = None, job_type: str | None = None, document_id: uuid.UUID | None = None,
              page: PageParams = Depends(), ctx: RequestContext = Depends(admin("admin.ingestion.manage", write=False))) -> Page[dict]:
    where, p = ["true"], {"l": page.limit, "o": page.offset}
    for col, val in (("status", status), ("job_type", job_type), ("document_id", document_id)):
        if val:
            where.append(f"{col} = :{col}")
            p[col] = val
    w = " AND ".join(where)
    with tx(ctx, "tenant_admin") as db:
        total = db.execute(text(f"SELECT count(*) FROM ingest.ingestion_jobs WHERE {w}"), p).scalar_one()
        items = [dict(r) for r in db.execute(text(f"SELECT {_COLS} FROM ingest.ingestion_jobs WHERE {w} "
                                                  "ORDER BY queued_at DESC LIMIT :l OFFSET :o"), p).mappings()]
    return Page(items=items, total=int(total), limit=page.limit, offset=page.offset)


@router.get("/admin/ingestion/summary", summary="Queue depth, throughput and failure counts")
def summary(ctx: RequestContext = Depends(admin("admin.ingestion.manage", write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        by_status = {r[0]: r[1] for r in db.execute(text("SELECT status, count(*) FROM ingest.ingestion_jobs GROUP BY status"))}
        row = db.execute(text("""SELECT count(*) FILTER (WHERE status = 'succeeded' AND finished_at > now() - interval '1 hour') AS last_hour,
                                        min(queued_at) FILTER (WHERE status IN ('queued', 'retrying')) AS oldest_waiting,
                                        avg(EXTRACT(EPOCH FROM finished_at - started_at)) FILTER (WHERE status = 'succeeded') AS avg_seconds
                                   FROM ingest.ingestion_jobs""")).mappings().one()
    return {"by_status": by_status, "succeeded_last_hour": row["last_hour"], "oldest_waiting_since": row["oldest_waiting"],
            "avg_processing_seconds": float(row["avg_seconds"]) if row["avg_seconds"] else None}


@router.post("/admin/ingestion/jobs/{job_id}/retry", status_code=202, summary="Retry a failed / dead-lettered job")
def retry(job_id: uuid.UUID, ctx: RequestContext = Depends(admin("admin.ingestion.manage"))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        row = db.execute(text("SELECT status FROM ingest.ingestion_jobs WHERE job_id = :j FOR UPDATE"), {"j": job_id}).first()
        if row is None:
            raise NotFound("Job not found")
        if row[0] not in ("failed", "dead_letter", "cancelled", "deferred"):
            raise Conflict(f"Job in status {row[0]} cannot be retried")
        db.execute(text("""UPDATE ingest.ingestion_jobs SET status = 'queued', attempt = 0, error_code = NULL,
                                  error_message = NULL, finished_at = NULL WHERE job_id = :j"""), {"j": job_id})
        db.execute(text("UPDATE platform.tenant_usage SET active_ingestion_jobs = active_ingestion_jobs + 1 WHERE tenant_id = :t"),
                   {"t": ctx.tenant_id})
    dispatch_ingestion(ctx.tenant_id, job_id)  # type: ignore[arg-type]
    return {"job_id": job_id, "status": "queued"}


@router.post("/admin/ingestion/jobs/{job_id}/cancel")
def cancel(job_id: uuid.UUID, ctx: RequestContext = Depends(admin("admin.ingestion.manage"))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        res = db.execute(text("""UPDATE ingest.ingestion_jobs SET status = 'cancelled', finished_at = now()
                                  WHERE job_id = :j AND status IN ('queued', 'retrying', 'deferred')"""), {"j": job_id})
        if res.rowcount == 0:
            raise Conflict("Only queued, retrying or deferred jobs can be cancelled")
        db.execute(text("UPDATE platform.tenant_usage SET active_ingestion_jobs = GREATEST(active_ingestion_jobs - 1, 0) "
                        "WHERE tenant_id = :t"), {"t": ctx.tenant_id})
    return {"job_id": job_id, "status": "cancelled"}
