"""Audit writer for the 15 audit categories of spec section 15 (FR-226..FR-230).

Audit rows are written in the *same transaction* as the audited change, so a
change can never commit without its audit record.  Denials / failures (whose
business transaction is rolled back) are written in a separate transaction.
Records hold identifiers and hashes - never passwords, secrets or document text.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.context import get_correlation_id
from app.database.session import SecurityContext, scoped_session

log = logging.getLogger("app.audit")

CATEGORIES = {"authentication", "authorization", "document_access", "search", "retrieval", "answer", "model_call",
              "prompt", "guardrail", "feedback", "ingestion", "document_update", "document_deletion",
              "configuration", "administration", "security"}
_SENSITIVE_KEYS = {"password", "secret", "api_key", "token", "content", "query_text", "comment", "mfa_secret"}


def _clean(detail: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (detail or {}).items():
        if any(s in key.lower() for s in _SENSITIVE_KEYS):
            out[key] = "[REDACTED]"
        elif isinstance(value, dict):
            out[key] = _clean(value)
        else:
            out[key] = value
    return out


def tenant_audit(db: Session, *, tenant_id: uuid.UUID, category: str, event_type: str, outcome: str = "success",
                 actor_user_id: uuid.UUID | None = None, actor_account_id: uuid.UUID | None = None,
                 actor_type: str = "user", resource_type: str | None = None, resource_id: Any = None,
                 detail: dict[str, Any] | None = None, source_ip: str | None = None) -> None:
    if category not in CATEGORIES:
        raise ValueError(f"unknown audit category {category}")
    db.execute(text("""
        INSERT INTO audit.tenant_audit_logs (tenant_id, category, event_type, outcome, actor_type, actor_user_id,
               actor_account_id, resource_type, resource_id, correlation_id, source_ip, detail)
        VALUES (:tenant_id, :category, :event_type, :outcome, :actor_type, :actor_user_id, :actor_account_id,
                :resource_type, :resource_id, :correlation_id, CAST(:source_ip AS inet), CAST(:detail AS jsonb))"""),
        {"tenant_id": tenant_id, "category": category, "event_type": event_type, "outcome": outcome,
         "actor_type": actor_type, "actor_user_id": actor_user_id, "actor_account_id": actor_account_id,
         "resource_type": resource_type, "resource_id": str(resource_id) if resource_id is not None else None,
         "correlation_id": get_correlation_id(), "source_ip": source_ip,
         "detail": json.dumps(_clean(detail), default=str)})


def platform_audit(db: Session, *, category: str, action: str, outcome: str = "success", severity: str = "info",
                   actor_account_id: uuid.UUID | None = None, target_tenant_id: uuid.UUID | None = None,
                   target_type: str | None = None, target_id: Any = None, reason: str | None = None,
                   detail: dict[str, Any] | None = None, source_ip: str | None = None) -> None:
    db.execute(text("""
        INSERT INTO platform.platform_audit_logs (category, action, outcome, severity, actor_account_id,
               target_tenant_id, target_type, target_id, reason, correlation_id, source_ip, detail)
        VALUES (:category, :action, :outcome, :severity, :actor, :tenant, :ttype, :tid, :reason, :cid,
                CAST(:ip AS inet), CAST(:detail AS jsonb))"""),
        {"category": category, "action": action, "outcome": outcome, "severity": severity,
         "actor": actor_account_id, "tenant": target_tenant_id, "ttype": target_type,
         "tid": str(target_id) if target_id is not None else None, "reason": reason, "cid": get_correlation_id(),
         "ip": source_ip, "detail": json.dumps(_clean(detail), default=str)})


def audit_out_of_band(ctx: SecurityContext, **kwargs: Any) -> None:
    """Write a tenant audit record in its own transaction (for denials whose
    business transaction rolls back).  Failures are logged, not swallowed silently."""
    try:
        with scoped_session(ctx) as db:
            tenant_audit(db, **kwargs)
    except Exception:
        log.exception("failed to write out-of-band audit event", extra={"event_type": kwargs.get("event_type")})


def platform_audit_out_of_band(**kwargs: Any) -> None:
    try:
        with scoped_session(SecurityContext(access_mode="none")) as db:
            platform_audit(db, **kwargs)
    except Exception:
        log.exception("failed to write platform audit event", extra={"action": kwargs.get("action")})
