"""Celery application: ingestion, maintenance and aggregation workers (spec 6.3, extension 13).

Queues:  ingestion (document processing), maintenance (retries, aggregation,
heartbeats).  acks_late + reject_on_worker_lost give at-least-once delivery;
the pipeline is idempotent so redelivery is safe.  Tasks that exhaust their
retries are recorded as dead_letter in ingest.ingestion_jobs (dead-letter
handling) and can be retried from the Admin Console.
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from app.core.config import get_settings

_s = get_settings()
celery_app = Celery("enterprise_rag", broker=_s.broker_url, backend=_s.result_backend,
                    include=["app.workers.tasks"])
celery_app.conf.update(
    task_serializer="json", accept_content=["json"], result_serializer="json", timezone="UTC", enable_utc=True,
    task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
    task_always_eager=_s.celery_task_always_eager, task_eager_propagates=False,
    task_routes={"app.workers.tasks.process_ingestion_job": {"queue": "ingestion"},
                 "app.workers.tasks.*": {"queue": "maintenance"}},
    task_default_queue="maintenance", result_expires=3600, broker_connection_retry_on_startup=True,
    beat_schedule={
        "requeue-due-jobs": {"task": "app.workers.tasks.requeue_due_jobs", "schedule": 60.0},
        "aggregate-usage": {"task": "app.workers.tasks.aggregate_usage", "schedule": crontab(minute="*/15")},
        "worker-heartbeat": {"task": "app.workers.tasks.heartbeat", "schedule": 30.0},
    },
)


@worker_process_init.connect
def _verify_database_role(**_: object) -> None:
    """Workers must never run with a credential that bypasses RLS (extension 2.3)."""
    from app.observability.tracing import configure_tracing

    configure_tracing("worker")
    if get_settings().environment != "test":
        from app.database.session import enforce_role_safety

        enforce_role_safety(("worker",))
