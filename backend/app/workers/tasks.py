"""Celery tasks.  Every task receives the tenant id explicitly, validates it
against the job row (under RLS) and establishes the worker context for that
tenant on every attempt - retries can never change the tenant context."""
from __future__ import annotations

import logging
import socket
import uuid

from sqlalchemy import text

from app.analytics.aggregation import aggregate_all, list_tenants
from app.database.session import SecurityContext, scoped_session
from app.rag.ingestion.pipeline import TRANSIENT, TenantNotOperational, run_job
from app.workers.celery_app import celery_app

log = logging.getLogger("app.worker")
WORKER_NAME = f"worker@{socket.gethostname()}"


def _heartbeat(processed: int = 0, failed: int = 0) -> None:
    with scoped_session(SecurityContext(access_mode="worker"), role="worker") as db:
        db.execute(text("""INSERT INTO ops.worker_heartbeats (worker_name, hostname, queues, status, processed, failed, last_seen_at)
                           VALUES (:n, :h, '{ingestion,maintenance}', 'online', :p, :f, now())
                           ON CONFLICT (worker_name) DO UPDATE SET last_seen_at = now(), status = 'online',
                                  processed = ops.worker_heartbeats.processed + :p, failed = ops.worker_heartbeats.failed + :f"""),
                   {"n": WORKER_NAME, "h": socket.gethostname(), "p": processed, "f": failed})


def _safe_heartbeat(processed: int = 0, failed: int = 0) -> None:
    """Heartbeats are best-effort telemetry and must never mask the job outcome."""
    try:
        _heartbeat(processed=processed, failed=failed)
    except Exception as exc:
        log.warning("worker heartbeat failed: %s", type(exc).__name__)


@celery_app.task(bind=True, name="app.workers.tasks.process_ingestion_job", max_retries=5)
def process_ingestion_job(self, tenant_id: str, job_id: str) -> dict:
    try:
        outcome = run_job(uuid.UUID(tenant_id), uuid.UUID(job_id))
    except TenantNotOperational:
        log.info("tenant not operational; job deferred", extra={"job_id": job_id})
        return {"status": "deferred"}
    except TRANSIENT as exc:
        _safe_heartbeat(failed=1)
        raise self.retry(exc=exc, countdown=min(300, 5 * 2 ** self.request.retries)) from exc
    except Exception:
        _safe_heartbeat(failed=1)
        raise
    _safe_heartbeat(processed=1)
    return {"status": outcome.status, "chunks": outcome.chunks}


@celery_app.task(name="app.workers.tasks.requeue_due_jobs")
def requeue_due_jobs() -> int:
    """Re-dispatch retrying jobs whose back-off elapsed and deferred jobs whose tenant
    became operational again - one tenant context at a time."""
    n = 0
    for tenant_id, _status in list_tenants(("active", "trial")):
        with scoped_session(SecurityContext.worker(tenant_id), role="worker") as db:
            due = db.execute(text("""SELECT job_id FROM ingest.ingestion_jobs
                                      WHERE (status = 'retrying' AND next_retry_at <= now())
                                         OR status = 'deferred'
                                         OR (status = 'queued' AND queued_at < now() - interval '10 minutes')
                                      ORDER BY priority, queued_at LIMIT 200""")).scalars().all()
            for job_id in due:
                db.execute(text("UPDATE ingest.ingestion_jobs SET status = 'queued' WHERE job_id = :j"), {"j": job_id})
        for job_id in due:
            process_ingestion_job.delay(str(tenant_id), str(job_id))
            n += 1
    return n


@celery_app.task(name="app.workers.tasks.aggregate_usage")
def aggregate_usage(days_back: int = 1) -> int:
    return aggregate_all(days_back)


@celery_app.task(name="app.workers.tasks.heartbeat")
def heartbeat() -> str:
    _heartbeat()
    return WORKER_NAME


def dispatch_ingestion(tenant_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Called by the API *after* the transaction that created the job committed."""
    try:
        res = process_ingestion_job.apply_async(args=[str(tenant_id), str(job_id)], queue="ingestion")
        with scoped_session(SecurityContext.worker(tenant_id), role="worker") as db:
            db.execute(text("UPDATE ingest.ingestion_jobs SET task_id = :tid WHERE job_id = :j AND task_id IS NULL"),
                       {"tid": res.id, "j": job_id})
    except Exception:
        # Broker unavailable: the job stays 'queued' and requeue_due_jobs picks it up (no silent loss).
        log.exception("failed to dispatch ingestion job; it will be re-queued by the scheduler",
                      extra={"job_id": str(job_id)})
