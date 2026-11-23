"""Quota enforcement in backend services (FR-176, NFR-105, extension 6.4).

Limits come from platform.tenant_quotas (configurable per tenant, defaulted
from the plan); usage counters live in platform.tenant_usage and are updated in
the same transaction as the operation they meter (row-locked, so concurrent
requests cannot overshoot).  Exceeding a limit rejects the operation with a
clear error and records an audit event; nothing is silently dropped.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import QuotaExceeded
from app.database.session import SecurityContext
from app.services.audit import audit_out_of_band

# metric -> (usage column, quota column)
_METRICS = {
    "users": ("users_count", "max_users"),
    "documents": ("documents_count", "max_documents"),
    "collections": ("collections_count", "max_collections"),
    "storage_bytes": ("storage_bytes", "max_storage_bytes"),
    "ai_tokens": ("ai_tokens_month", "monthly_ai_tokens"),
    "ai_requests": ("ai_requests_month", "monthly_ai_requests"),
    "ingestion_jobs": ("active_ingestion_jobs", "max_ingestion_jobs"),
}


@dataclass
class QuotaState:
    metric: str
    used: int
    limit: int

    @property
    def pct(self) -> float:
        return round(100.0 * self.used / self.limit, 1) if self.limit else 100.0


def _roll_month(db: Session, tenant_id: uuid.UUID) -> None:
    db.execute(text("""UPDATE platform.tenant_usage SET usage_month = date_trunc('month', now())::date,
                              ai_tokens_month = 0, ai_requests_month = 0
                        WHERE tenant_id = :t AND usage_month < date_trunc('month', now())::date"""), {"t": tenant_id})


def consume(db: Session, sec: SecurityContext, metric: str, amount: int = 1) -> QuotaState:
    """Check-and-increment atomically.  Raises QuotaExceeded (HTTP 429)."""
    usage_col, quota_col = _METRICS[metric]
    tenant_id = sec.tenant_id
    assert tenant_id is not None
    _roll_month(db, tenant_id)
    row = db.execute(text(f"""
        SELECT u.{usage_col} AS used, q.{quota_col} AS lim
          FROM platform.tenant_usage u JOIN platform.tenant_quotas q USING (tenant_id)
         WHERE u.tenant_id = :t FOR UPDATE OF u"""), {"t": tenant_id}).mappings().first()
    if row is None:
        raise QuotaExceeded("No quota configuration for tenant", code="quota_not_configured")
    if amount > 0 and row["used"] + amount > row["lim"]:
        audit_out_of_band(sec, tenant_id=tenant_id, category="administration", event_type="quota_exceeded",
                          outcome="denied", actor_user_id=sec.user_id,
                          detail={"metric": metric, "used": row["used"], "limit": row["lim"], "requested": amount})
        raise QuotaExceeded(f"Quota exceeded for {metric}: {row['used']} of {row['lim']} used",
                            details=[{"metric": metric, "used": row["used"], "limit": row["lim"]}])
    db.execute(text(f"UPDATE platform.tenant_usage SET {usage_col} = GREATEST({usage_col} + :n, 0), updated_at = now() "
                    "WHERE tenant_id = :t"), {"n": amount, "t": tenant_id})
    return QuotaState(metric, row["used"] + amount, row["lim"])


def release(db: Session, tenant_id: uuid.UUID, metric: str, amount: int = 1) -> None:
    usage_col, _ = _METRICS[metric]
    db.execute(text(f"UPDATE platform.tenant_usage SET {usage_col} = GREATEST({usage_col} - :n, 0), updated_at = now() "
                    "WHERE tenant_id = :t"), {"n": amount, "t": tenant_id})


def check_limit(db: Session, tenant_id: uuid.UUID, quota_col: str) -> int:
    return int(db.execute(text(f"SELECT {quota_col} FROM platform.tenant_quotas WHERE tenant_id = :t"),
                          {"t": tenant_id}).scalar_one())


def snapshot(db: Session, tenant_id: uuid.UUID) -> list[QuotaState]:
    row = db.execute(text("SELECT * FROM platform.tenant_usage u JOIN platform.tenant_quotas q USING (tenant_id) "
                          "WHERE tenant_id = :t"), {"t": tenant_id}).mappings().first()
    if row is None:
        return []
    return [QuotaState(m, int(row[u]), int(row[q])) for m, (u, q) in _METRICS.items()]
