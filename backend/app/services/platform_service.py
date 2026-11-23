"""Platform Super Admin services: dashboard, monitoring, AI providers, model
catalogue, platform users, audit / security events and break-glass access
(extension 6, 9, 11).  Statistics are aggregated and tenant-aware; no document
content or conversation text is exposed.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.database.session import SecurityContext, apply_security_context, get_engine
from app.security.crypto import decrypt_secret, encrypt_secret
from app.services.audit import platform_audit, tenant_audit
from app.utils.cache import get_cache
from app.utils.clock import utc_today

COST_NOTE = "Estimated from catalogue model pricing; not provider billing data."


def dashboard(db: Session, start: date | None, end: date | None, tenant_id: uuid.UUID | None) -> dict[str, Any]:
    end = end or utc_today()
    start = start or end - timedelta(days=29)
    tf = "AND tenant_id = :tid" if tenant_id else ""
    p = {"s": start, "e": end, "tid": tenant_id}
    tenants = db.execute(text(f"""SELECT count(*) AS total, count(*) FILTER (WHERE status = 'active') AS active,
                                         count(*) FILTER (WHERE status = 'suspended') AS suspended,
                                         count(*) FILTER (WHERE status = 'trial') AS trial,
                                         count(*) FILTER (WHERE status IN ('deactivated', 'archived')) AS inactive
                                    FROM platform.tenants WHERE true {tf}"""), p).mappings().one()
    live = db.execute(text(f"""SELECT COALESCE(sum(users_count), 0) AS users, COALESCE(sum(documents_count), 0) AS documents,
                                      COALESCE(sum(chunks_count), 0) AS chunks, COALESCE(sum(storage_bytes), 0) AS storage_bytes,
                                      COALESCE(sum(active_ingestion_jobs), 0) AS active_ingestion_jobs
                                 FROM platform.tenant_usage WHERE true {tf}"""), p).mappings().one()
    accounts = db.execute(text("""SELECT count(*) AS total, count(*) FILTER (WHERE status = 'active') AS active,
                                         count(*) FILTER (WHERE last_login_at > now() - interval '30 days') AS active_30d
                                    FROM iam.user_accounts""")).mappings().one()
    agg = db.execute(text(f"""
        SELECT COALESCE(sum(searches), 0) AS searches, COALESCE(sum(chats), 0) AS chats,
               COALESCE(sum(conversations_started), 0) AS conversations, COALESCE(sum(ai_requests), 0) AS ai_requests,
               COALESCE(sum(input_tokens + output_tokens), 0) AS tokens, COALESCE(sum(estimated_cost), 0) AS estimated_cost,
               COALESCE(sum(documents_ingested), 0) AS ingested, COALESCE(sum(ingestion_failures), 0) AS ingestion_failures,
               round(avg(avg_search_latency_ms)) AS avg_search_latency_ms, round(avg(avg_llm_latency_ms)) AS avg_llm_latency_ms
          FROM ops.tenant_usage_daily WHERE usage_date BETWEEN :s AND :e {tf}"""), p).mappings().one()
    total_jobs = (agg["ingested"] or 0) + (agg["ingestion_failures"] or 0)
    series = [dict(r) for r in db.execute(text(f"""
        SELECT usage_date, sum(searches) AS searches, sum(chats) AS chats, sum(ai_requests) AS ai_requests,
               sum(input_tokens + output_tokens) AS tokens, sum(estimated_cost) AS estimated_cost,
               sum(active_users) AS active_users, sum(documents_ingested) AS documents_ingested
          FROM ops.tenant_usage_daily WHERE usage_date BETWEEN :s AND :e {tf} GROUP BY usage_date ORDER BY usage_date"""),
        p).mappings().all()]
    top = [dict(r) for r in db.execute(text("""
        SELECT t.tenant_id, t.code, t.name, COALESCE(sum(u.searches + u.chats), 0) AS requests,
               COALESCE(sum(u.input_tokens + u.output_tokens), 0) AS tokens, COALESCE(sum(u.estimated_cost), 0) AS estimated_cost
          FROM platform.tenants t LEFT JOIN ops.tenant_usage_daily u ON u.tenant_id = t.tenant_id
                                       AND u.usage_date BETWEEN :s AND :e
         GROUP BY t.tenant_id, t.code, t.name ORDER BY tokens DESC, requests DESC LIMIT 10"""), p).mappings().all()]
    recent = [dict(r) for r in db.execute(text("""SELECT occurred_at, category, action, outcome, severity, target_tenant_id
                                                   FROM platform.platform_audit_logs ORDER BY seq DESC LIMIT 15""")).mappings().all()]
    return {"range": {"start": start, "end": end},
            "tenants": dict(tenants),
            "users": {"total_accounts": accounts["total"], "active_accounts": accounts["active"],
                      "inactive_accounts": accounts["total"] - accounts["active"], "active_last_30_days": accounts["active_30d"],
                      "tenant_users": live["users"]},
            "content": {"documents": live["documents"], "chunks": live["chunks"], "embeddings": live["chunks"],
                        "storage_bytes": live["storage_bytes"], "active_ingestion_jobs": live["active_ingestion_jobs"]},
            "usage": dict(agg) | {
                "ingestion_success_rate": round(100 * agg["ingested"] / total_jobs, 1) if total_jobs else None,
                "ingestion_failure_rate": round(100 * agg["ingestion_failures"] / total_jobs, 1) if total_jobs else None},
            "series": series, "top_tenants": top, "recent_events": recent, "health": health(db),
            "alerts": alerts(db), "cost_note": COST_NOTE}


def health(db: Session) -> dict[str, Any]:
    out: dict[str, Any] = {"api": {"status": "up"}}
    t = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        pool = get_engine("app").pool
        out["database"] = {"status": "up", "latency_ms": round((time.perf_counter() - t) * 1000, 1),
                           "pool": {"size": pool.size(), "checked_out": pool.checkedout()}}  # type: ignore[attr-defined]
    except Exception as exc:
        out["database"] = {"status": "down", "error": type(exc).__name__}
    t = time.perf_counter()
    out["redis"] = {"status": "up" if get_cache().ping() else "down", "latency_ms": round((time.perf_counter() - t) * 1000, 1)}
    workers = [dict(r) for r in db.execute(text("SELECT worker_name, status, processed, failed, last_seen_at FROM ops.worker_heartbeats "
                                                "ORDER BY last_seen_at DESC")).mappings().all()]
    now = datetime.now(UTC)
    for w in workers:
        w["healthy"] = w["last_seen_at"] > now - timedelta(minutes=2)
    out["workers"] = {"status": "up" if any(w["healthy"] for w in workers) else ("down" if workers else "unknown"),
                      "instances": workers}
    out["queue"] = queue_depth()
    return out


def queue_depth() -> dict[str, Any]:
    try:
        import redis

        r = redis.Redis.from_url(get_settings().broker_url, socket_timeout=2)
        return {"ingestion": r.llen("ingestion"), "maintenance": r.llen("maintenance"), "status": "up"}
    except Exception as exc:
        return {"status": "unknown", "error": type(exc).__name__}


def alerts(db: Session) -> list[dict[str, Any]]:
    out = []
    for r in db.execute(text("""SELECT t.code, q.max_storage_bytes, u.storage_bytes, q.monthly_ai_tokens, u.ai_tokens_month,
                                       q.max_documents, u.documents_count, q.warning_threshold_pct
                                  FROM platform.tenant_quotas q JOIN platform.tenant_usage u USING (tenant_id)
                                  JOIN platform.tenants t USING (tenant_id) WHERE t.status IN ('active', 'trial')""")).mappings():
        for metric, used, lim in (("storage", r["storage_bytes"], r["max_storage_bytes"]),
                                  ("ai_tokens", r["ai_tokens_month"], r["monthly_ai_tokens"]),
                                  ("documents", r["documents_count"], r["max_documents"])):
            if lim and used / lim * 100 >= r["warning_threshold_pct"]:
                out.append({"severity": "warning" if used < lim else "critical", "tenant": r["code"], "metric": metric,
                            "used": used, "limit": lim, "message": f"{r['code']}: {metric} at {round(100 * used / lim)}% of quota"})
    failed = db.execute(text("""SELECT t.code, sum(d.ingestion_failures) AS n FROM ops.tenant_usage_daily d
                                  JOIN platform.tenants t USING (tenant_id) WHERE d.usage_date >= CURRENT_DATE - 1
                                 GROUP BY t.code HAVING sum(d.ingestion_failures) > 0""")).all()
    out.extend({"severity": "warning", "tenant": c, "metric": "ingestion_failures", "used": int(n),
                "message": f"{c}: {n} ingestion failures in the last 24h"} for c, n in failed)
    high = db.execute(text("""SELECT count(*) FROM platform.platform_audit_logs
                               WHERE severity IN ('high', 'critical') AND occurred_at > now() - interval '24 hours'""")).scalar_one()
    if high:
        out.append({"severity": "critical", "metric": "security_events", "used": high,
                    "message": f"{high} high-severity security events in the last 24h"})
    return out


def monitoring(db: Session) -> dict[str, Any]:
    from prometheus_client import REGISTRY

    h = health(db)
    metrics: dict[str, float] = {}
    for fam in REGISTRY.collect():
        if fam.name in ("http_requests", "rag_answers", "rag_guardrail_decisions", "ingestion_jobs", "rag_empty_retrievals"):
            for s in fam.samples:
                if s.name.endswith("_total"):
                    key = s.name + ("{" + ",".join(f"{k}={v}" for k, v in sorted(s.labels.items())) + "}" if s.labels else "")
                    metrics[key] = s.value
    errors = sum(v for k, v in metrics.items() if k.startswith("http_requests_total") and "status=5" in k)
    total = sum(v for k, v in metrics.items() if k.startswith("http_requests_total"))
    db_stats = db.execute(text("""SELECT numbackends, xact_commit, xact_rollback, blks_hit, blks_read, deadlocks
                                    FROM pg_stat_database WHERE datname = current_database()""")).mappings().first()
    hit = (db_stats["blks_hit"] / max(1, db_stats["blks_hit"] + db_stats["blks_read"])) if db_stats else None
    return {"health": h, "process_metrics": metrics,
            "error_rate_pct": round(100 * errors / total, 2) if total else 0.0,
            "database": dict(db_stats or {}) | {"cache_hit_ratio": round(hit, 4) if hit is not None else None},
            "provider_health": [dict(r) for r in db.execute(text(
                "SELECT code, provider_type, health_status, last_checked_at, is_enabled FROM platform.ai_providers")).mappings().all()]}


def jobs_overview(db: Session) -> dict[str, Any]:
    per_tenant = [dict(r) for r in db.execute(text("""
        SELECT t.tenant_id, t.code, u.active_ingestion_jobs,
               (SELECT COALESCE(sum(ingestion_failures), 0) FROM ops.tenant_usage_daily d WHERE d.tenant_id = t.tenant_id
                 AND d.usage_date >= CURRENT_DATE - 7) AS failures_7d,
               (SELECT COALESCE(sum(documents_ingested), 0) FROM ops.tenant_usage_daily d WHERE d.tenant_id = t.tenant_id
                 AND d.usage_date >= CURRENT_DATE - 7) AS ingested_7d
          FROM platform.tenants t JOIN platform.tenant_usage u USING (tenant_id) ORDER BY t.code""")).mappings().all()]
    return {"queue": queue_depth(), "workers": health(db)["workers"], "tenants": per_tenant}


# --- AI providers and model catalogue -------------------------------------------------------
def _provider_out(r: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in r.items() if k != "api_key_enc"}
    out["api_key_masked"] = ("****" + r["api_key_last4"]) if r.get("api_key_last4") else None
    return out


def list_providers(db: Session) -> list[dict[str, Any]]:
    return [_provider_out(dict(r)) for r in db.execute(text("SELECT * FROM platform.ai_providers ORDER BY code")).mappings().all()]


def upsert_provider(db: Session, sec: SecurityContext, data: dict[str, Any], provider_id: uuid.UUID | None = None) -> dict[str, Any]:
    key = data.pop("api_key", None)
    if provider_id is None:
        provider_id = uuid.uuid4()
        db.execute(text("""INSERT INTO platform.ai_providers (provider_id, code, name, provider_type, base_url, api_version,
                                  api_key_enc, api_key_last4, region, is_enabled, allow_tenant_override, rate_limit_per_min)
                           VALUES (:id, :code, :name, :pt, :url, :ver, :enc, :last4, :region, :en, :ovr, :rl)"""),
                   {"id": provider_id, "code": data["code"], "name": data["name"], "pt": data["provider_type"],
                    "url": data.get("base_url"), "ver": data.get("api_version"), "enc": encrypt_secret(key) if key else None,
                    "last4": key[-4:] if key else None, "region": data.get("region", "default"),
                    "en": data.get("is_enabled", True), "ovr": data.get("allow_tenant_override", False),
                    "rl": data.get("rate_limit_per_min")})
        action = "ai_provider_created"
    else:
        fields = {k: v for k, v in data.items() if k in {"name", "base_url", "api_version", "region", "is_enabled",
                                                          "allow_tenant_override", "rate_limit_per_min"} and v is not None}
        if key:
            fields["api_key_enc"], fields["api_key_last4"] = encrypt_secret(key), key[-4:]
        if fields:
            sets = ", ".join(f"{k} = :{k}" for k in fields)
            res = db.execute(text(f"UPDATE platform.ai_providers SET {sets}, updated_at = now() WHERE provider_id = :id"),
                             {**fields, "id": provider_id})
            if res.rowcount == 0:
                raise NotFound("Provider not found")
        action = "ai_provider_updated"
    platform_audit(db, category="configuration", action=action, actor_account_id=sec.account_id, target_type="ai_provider",
                   target_id=provider_id, detail={"fields": sorted(data), "api_key_changed": bool(key)})
    return _provider_out(dict(db.execute(text("SELECT * FROM platform.ai_providers WHERE provider_id = :id"),
                                         {"id": provider_id}).mappings().one()))


def check_provider(db: Session, sec: SecurityContext, provider_id: uuid.UUID) -> dict[str, Any]:
    p = db.execute(text("SELECT * FROM platform.ai_providers WHERE provider_id = :id"), {"id": provider_id}).mappings().first()
    if p is None:
        raise NotFound("Provider not found")
    if p["provider_type"] == "local":
        status, detail = "healthy", "built-in"
    else:
        key = decrypt_secret(p["api_key_enc"])
        url = (p["base_url"] or "https://api.openai.com/v1").rstrip("/")
        if p["provider_type"] == "ollama":
            # Ollama's native API lives at the server root; the chat endpoint is registered as <root>/v1
            # (OpenAI-compatible), so drop that suffix before appending /api/tags.
            if url.endswith("/v1"):
                url = url[: -len("/v1")]
            path = "/api/tags"
        else:
            path = "/health" if p["provider_type"] == "huggingface" else "/models"
        try:
            headers = {"Authorization": f"Bearer {key}"} if key and p["provider_type"] != "azure_openai" else (
                {"api-key": key} if key else {})
            r = httpx.get(url + path, headers=headers, timeout=5.0)
            status = "healthy" if r.status_code < 400 else ("degraded" if r.status_code < 500 else "down")
            detail = f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            status, detail = "down", type(exc).__name__
    db.execute(text("UPDATE platform.ai_providers SET health_status = :s, last_checked_at = now() WHERE provider_id = :id"),
               {"s": status, "id": provider_id})
    return {"provider_id": provider_id, "health_status": status, "detail": detail}


def list_models(db: Session, purpose: str | None = None) -> list[dict[str, Any]]:
    where = "WHERE m.purpose = :p" if purpose else ""
    return [dict(r) for r in db.execute(text(f"""SELECT m.*, p.code AS provider_code FROM platform.model_catalogue m
                                                 JOIN platform.ai_providers p ON p.provider_id = m.provider_id {where}
                                                 ORDER BY m.purpose, p.code, m.model_name"""), {"p": purpose}).mappings().all()]


def upsert_model(db: Session, sec: SecurityContext, data: dict[str, Any], model_id: uuid.UUID | None = None) -> dict[str, Any]:
    if model_id is None:
        model_id = uuid.uuid4()
        db.execute(text("""INSERT INTO platform.model_catalogue (model_id, provider_id, model_name, model_version, purpose,
                                  dimensions, context_window, input_cost_per_1k, output_cost_per_1k, risk_class, status)
                           VALUES (:id, :pid, :n, :v, :p, :d, :cw, :ci, :co, :rc, 'proposed')"""),
                   {"id": model_id, "pid": data["provider_id"], "n": data["model_name"], "v": data.get("model_version", "latest"),
                    "p": data["purpose"], "d": data.get("dimensions"), "cw": data.get("context_window"),
                    "ci": data.get("input_cost_per_1k", 0), "co": data.get("output_cost_per_1k", 0),
                    "rc": data.get("risk_class", "medium")})
        action = "model_registered"
    else:
        fields = {k: v for k, v in data.items() if k in {"input_cost_per_1k", "output_cost_per_1k", "risk_class", "status",
                                                          "context_window", "is_default"} and v is not None}
        if fields.get("status") in ("approved", "active"):
            fields["approved_by"], fields["approved_at"] = sec.account_id, datetime.now(UTC)
        if fields.get("is_default"):
            purpose = db.execute(text("SELECT purpose FROM platform.model_catalogue WHERE model_id = :id"), {"id": model_id}).scalar()
            db.execute(text("UPDATE platform.model_catalogue SET is_default = false WHERE purpose = :p"), {"p": purpose})
        if fields:
            sets = ", ".join(f"{k} = :{k}" for k in fields)
            res = db.execute(text(f"UPDATE platform.model_catalogue SET {sets} WHERE model_id = :id"), {**fields, "id": model_id})
            if res.rowcount == 0:
                raise NotFound("Model not found")
        action = "model_updated"
    platform_audit(db, category="configuration", action=action, actor_account_id=sec.account_id, target_type="model",
                   target_id=model_id, detail={k: str(v) for k, v in data.items()})
    return dict(db.execute(text("SELECT * FROM platform.model_catalogue WHERE model_id = :id"), {"id": model_id}).mappings().one())


# --- platform users ---------------------------------------------------------------------------
def list_platform_users(db: Session) -> list[dict[str, Any]]:
    return [dict(r) for r in db.execute(text("""SELECT p.account_id, a.email::text AS email, a.display_name, r.code AS role,
                                                       p.status, p.created_at, a.last_login_at, a.mfa_enabled
                                                  FROM platform.platform_users p JOIN iam.user_accounts a USING (account_id)
                                                  JOIN platform.platform_roles r ON r.role_id = p.role_id ORDER BY a.email""")).mappings().all()]


def set_platform_user(db: Session, sec: SecurityContext, *, email: str, display_name: str | None, role: str,
                      password: str | None, status: str = "active") -> dict[str, Any]:
    from app.security.passwords import hash_password, password_policy_errors

    role_id = db.execute(text("SELECT role_id FROM platform.platform_roles WHERE code = :c"), {"c": role}).scalar()
    if role_id is None:
        raise ValidationFailed("unknown platform role")
    account_id = db.execute(text("SELECT account_id FROM iam.user_accounts WHERE email = :e"), {"e": email.lower()}).scalar()
    if account_id is None:
        if not password:
            raise ValidationFailed("password required for a new platform account")
        errs = password_policy_errors(password, get_settings().password_min_length)
        if errs:
            raise ValidationFailed("Password does not meet policy", details=[{"field": "password", "message": e} for e in errs])
        account_id = uuid.uuid4()
        db.execute(text("INSERT INTO iam.user_accounts (account_id, email, display_name, password_hash) VALUES (:a, :e, :n, :h)"),
                   {"a": account_id, "e": email.lower(), "n": display_name or email, "h": hash_password(password)})
    if account_id == sec.account_id and status != "active":
        raise ValidationFailed("You cannot disable your own platform access")
    db.execute(text("""INSERT INTO platform.platform_users (account_id, role_id, status, created_by) VALUES (:a, :r, :s, :by)
                       ON CONFLICT (account_id) DO UPDATE SET role_id = EXCLUDED.role_id, status = EXCLUDED.status,
                              updated_at = now()"""),
               {"a": account_id, "r": role_id, "s": status, "by": sec.account_id})
    platform_audit(db, category="administration", action="platform_user_set", severity="medium",
                   actor_account_id=sec.account_id, target_type="platform_user", target_id=account_id,
                   detail={"role": role, "status": status})
    return next(u for u in list_platform_users(db) if u["account_id"] == account_id)


# --- audit / security --------------------------------------------------------------------------
def audit_events(db: Session, *, category: str | None, tenant_id: uuid.UUID | None, severity: str | None,
                 start: datetime | None, end: datetime | None, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    where, p = ["true"], {"l": limit, "o": offset}
    for col, val in (("category", category), ("target_tenant_id", tenant_id), ("severity", severity)):
        if val:
            where.append(f"{col} = :{col}")
            p[col] = val
    if start:
        where.append("occurred_at >= :start")
        p["start"] = start
    if end:
        where.append("occurred_at < :end")
        p["end"] = end
    w = " AND ".join(where)
    total = db.execute(text(f"SELECT count(*) FROM platform.platform_audit_logs WHERE {w}"), p).scalar_one()
    rows = db.execute(text(f"""SELECT event_id, seq, occurred_at, category, action, outcome, severity, actor_account_id,
                                      target_tenant_id, target_type, target_id, reason, correlation_id, detail, hash
                                 FROM platform.platform_audit_logs WHERE {w} ORDER BY seq DESC LIMIT :l OFFSET :o"""), p).mappings().all()
    return [dict(r) for r in rows], int(total)


# --- break-glass (extension 11) ----------------------------------------------------------------
def open_break_glass(db: Session, sec: SecurityContext, tenant_id: uuid.UUID, reason: str, minutes: int,
                     scope: list[str]) -> dict[str, Any]:
    if len((reason or "").strip()) < 15:
        raise ValidationFailed("A business reason of at least 15 characters is required")
    if not 5 <= minutes <= 480:
        raise ValidationFailed("Break-glass duration must be between 5 and 480 minutes")
    tenant = db.execute(text("SELECT status FROM platform.tenants WHERE tenant_id = :t"), {"t": tenant_id}).scalar()
    if tenant is None:
        raise NotFound("Tenant not found")
    if db.execute(text("""SELECT enabled FROM platform.tenant_feature_flags WHERE tenant_id = :t AND flag = 'break_glass_support'"""),
                  {"t": tenant_id}).scalar() is False:
        raise PermissionDenied("The tenant's subscription does not permit break-glass support access")
    if db.execute(text("SELECT 1 FROM platform.break_glass_grants WHERE account_id = :a AND tenant_id = :t AND status = 'active' "
                       "AND expires_at > now()"), {"a": sec.account_id, "t": tenant_id}).first():
        raise Conflict("An active break-glass grant already exists for this tenant")
    gid = uuid.uuid4()
    now = datetime.now(UTC)
    db.execute(text("""INSERT INTO platform.break_glass_grants (grant_id, account_id, tenant_id, reason, scope, starts_at, expires_at)
                       VALUES (:g, :a, :t, :r, :s, :st, :ex)"""),
               {"g": gid, "a": sec.account_id, "t": tenant_id, "r": reason, "s": scope or ["documents:read"], "st": now,
                "ex": now + timedelta(minutes=minutes)})
    platform_audit(db, category="security", action="break_glass_opened", severity="high", actor_account_id=sec.account_id,
                   target_tenant_id=tenant_id, target_type="break_glass_grant", target_id=gid, reason=reason,
                   detail={"minutes": minutes, "scope": scope})
    return dict(db.execute(text("SELECT * FROM platform.break_glass_grants WHERE grant_id = :g"), {"g": gid}).mappings().one())


def close_break_glass(db: Session, sec: SecurityContext, grant_id: uuid.UUID) -> dict[str, Any]:
    res = db.execute(text("""UPDATE platform.break_glass_grants SET status = 'ended', ended_at = now()
                              WHERE grant_id = :g AND account_id = :a AND status = 'active'"""), {"g": grant_id, "a": sec.account_id})
    if res.rowcount == 0:
        raise NotFound("Active grant not found")
    g = dict(db.execute(text("SELECT * FROM platform.break_glass_grants WHERE grant_id = :g"), {"g": grant_id}).mappings().one())
    platform_audit(db, category="security", action="break_glass_closed", severity="high", actor_account_id=sec.account_id,
                   target_tenant_id=g["tenant_id"], target_type="break_glass_grant", target_id=grant_id,
                   detail={"resources_accessed": len(g["resources_accessed"])})
    return g


def break_glass_read(db: Session, sec: SecurityContext, grant_id: uuid.UUID, resource: str,
                     resource_id: uuid.UUID | None) -> dict[str, Any]:
    """Read-only, time-limited access through the `break_glass` RLS mode.  Every
    access is appended to the grant and audited in BOTH platform and tenant logs."""
    g = db.execute(text("SELECT * FROM platform.break_glass_grants WHERE grant_id = :g AND account_id = :a"),
                   {"g": grant_id, "a": sec.account_id}).mappings().first()
    if g is None or g["status"] != "active" or g["expires_at"] <= datetime.now(UTC):
        raise PermissionDenied("No active break-glass grant", code="break_glass_inactive")
    tenant_id = g["tenant_id"]
    apply_security_context(db, SecurityContext(access_mode="break_glass", tenant_id=tenant_id, account_id=sec.account_id,
                                               platform_role=sec.platform_role))
    if resource == "documents":
        data: Any = [dict(r) for r in db.execute(text("""SELECT document_id, title, document_type, lifecycle_state, classification,
                                                                 updated_at FROM content.documents ORDER BY updated_at DESC LIMIT 200""")).mappings().all()]
    elif resource == "document" and resource_id:
        data = [dict(r) for r in db.execute(text("""SELECT chunk_id, section_path, page_from, content FROM content.document_chunks
                                                     WHERE document_id = :d ORDER BY chunk_index LIMIT 500"""), {"d": resource_id}).mappings().all()]
    elif resource == "conversation" and resource_id:
        if "conversations:read" not in (g["scope"] or []):
            raise PermissionDenied("Grant scope does not include conversations")
        data = [dict(r) for r in db.execute(text("""SELECT seq, role, content, answer_status, created_at FROM rag.conversation_messages
                                                     WHERE conversation_id = :c ORDER BY seq"""), {"c": resource_id}).mappings().all()]
    else:
        raise ValidationFailed("resource must be documents, document or conversation")
    entry = {"at": datetime.now(UTC).isoformat(), "resource": resource, "id": str(resource_id) if resource_id else None,
             "rows": len(data)}
    db.execute(text("""UPDATE platform.break_glass_grants SET resources_accessed = resources_accessed || CAST(:e AS jsonb)
                        WHERE grant_id = :g"""), {"e": json.dumps([entry]), "g": grant_id})
    tenant_audit(db, tenant_id=tenant_id, category="administration", event_type="break_glass_access", actor_type="platform_admin",
                 actor_account_id=sec.account_id, resource_type=resource, resource_id=resource_id,
                 detail={"grant_id": str(grant_id), "rows": len(data)})
    apply_security_context(db, SecurityContext(access_mode="platform", account_id=sec.account_id, platform_role=sec.platform_role))
    platform_audit(db, category="security", action="break_glass_access", severity="high", actor_account_id=sec.account_id,
                   target_tenant_id=tenant_id, target_type=resource, target_id=resource_id,
                   detail={"grant_id": str(grant_id), "rows": len(data)})
    return {"grant_id": grant_id, "tenant_id": tenant_id, "resource": resource, "data": data,
            "expires_at": g["expires_at"]}
