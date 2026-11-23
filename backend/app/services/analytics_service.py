"""Tenant and department analytics, dashboards and CSV reports (FR-216..FR-225,
extension 7.1, 7.8, 10).  All figures are computed from database data:
daily aggregates (ops.*) for trends and indexed live counts for current totals.
Costs are labelled as estimates.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.services import quota_service
from app.utils.clock import utc_today

COST_NOTE = "Estimated from catalogue model pricing; not provider billing data."


def _range(start: date | None, end: date | None) -> tuple[date, date]:
    end = end or utc_today()
    start = start or end - timedelta(days=29)
    if start > end or (end - start).days > 400:
        raise ValidationFailed("invalid date range (max 400 days)")
    return start, end


def tenant_dashboard(db: Session, tenant_id: uuid.UUID, start: date | None, end: date | None) -> dict[str, Any]:
    start, end = _range(start, end)
    live = db.execute(text("""
        SELECT (SELECT count(*) FROM iam.users) AS total_users,
               (SELECT count(*) FROM iam.users WHERE status = 'active') AS active_users,
               (SELECT count(*) FROM content.documents WHERE deleted_at IS NULL) AS total_documents,
               (SELECT count(*) FROM content.documents WHERE deleted_at IS NULL AND lifecycle_state = 'published') AS indexed_documents,
               (SELECT count(*) FROM content.documents WHERE deleted_at IS NULL
                   AND lifecycle_state IN ('draft', 'processing', 'in_review', 'approved')) AS pending_documents,
               (SELECT count(*) FROM ingest.ingestion_jobs WHERE status IN ('failed', 'dead_letter')) AS failed_ingestion_jobs,
               (SELECT count(*) FROM content.collections) AS total_collections,
               (SELECT chunks_count FROM platform.tenant_usage WHERE tenant_id = :t) AS total_chunks,
               (SELECT storage_bytes FROM platform.tenant_usage WHERE tenant_id = :t) AS storage_bytes
    """), {"t": tenant_id}).mappings().one()
    agg = db.execute(text("""
        SELECT COALESCE(sum(searches), 0) AS searches, COALESCE(sum(chats), 0) AS chats,
               COALESCE(sum(conversations_started), 0) AS conversations, COALESCE(sum(ai_requests), 0) AS ai_requests,
               COALESCE(sum(input_tokens + output_tokens), 0) AS tokens, COALESCE(sum(estimated_cost), 0) AS estimated_cost,
               round(avg(avg_search_latency_ms)) AS avg_search_latency_ms, round(avg(avg_llm_latency_ms)) AS avg_llm_latency_ms,
               COALESCE(sum(feedback_positive), 0) AS feedback_positive, COALESCE(sum(feedback_negative), 0) AS feedback_negative,
               COALESCE(sum(abstentions), 0) AS abstentions, COALESCE(sum(guardrail_blocks), 0) AS guardrail_blocks,
               COALESCE(sum(documents_ingested), 0) AS documents_ingested, COALESCE(sum(ingestion_failures), 0) AS ingestion_failures
          FROM ops.tenant_usage_daily WHERE tenant_id = :t AND usage_date BETWEEN :s AND :e"""),
        {"t": tenant_id, "s": start, "e": end}).mappings().one()
    series = [dict(r) for r in db.execute(text("""
        SELECT usage_date, searches, chats, conversations_started, active_users, documents_ingested, ingestion_failures,
               input_tokens + output_tokens AS tokens, estimated_cost, avg_search_latency_ms, avg_llm_latency_ms,
               feedback_positive, feedback_negative, abstentions
          FROM ops.tenant_usage_daily WHERE tenant_id = :t AND usage_date BETWEEN :s AND :e ORDER BY usage_date"""),
        {"t": tenant_id, "s": start, "e": end}).mappings().all()]
    quotas = [q.__dict__ | {"pct": q.pct} for q in quota_service.snapshot(db, tenant_id)]
    totals = dict(live) | dict(agg)
    fb = (agg["feedback_positive"] or 0) + (agg["feedback_negative"] or 0)
    totals["feedback_satisfaction_pct"] = round(100 * agg["feedback_positive"] / fb, 1) if fb else None
    return {"range": {"start": start, "end": end}, "totals": totals, "series": series, "quotas": quotas,
            "cost_note": COST_NOTE}


def department_dashboard(db: Session, department_id: uuid.UUID, start: date | None, end: date | None) -> dict[str, Any]:
    start, end = _range(start, end)
    series = [dict(r) for r in db.execute(text("""SELECT usage_date, searches, chats, input_tokens + output_tokens AS tokens,
                                                         estimated_cost, active_users FROM ops.department_usage_daily
                                                   WHERE department_id = :d AND usage_date BETWEEN :s AND :e ORDER BY usage_date"""),
                                          {"d": department_id, "s": start, "e": end}).mappings().all()]
    users = db.execute(text("SELECT count(*) FROM iam.users WHERE department_id = :d AND status = 'active'"),
                       {"d": department_id}).scalar_one()
    return {"department_id": department_id, "range": {"start": start, "end": end}, "active_users": users,
            "totals": {k: sum((r[k] or 0) for r in series) for k in ("searches", "chats", "tokens", "estimated_cost")},
            "series": series, "cost_note": COST_NOTE}


def usage_and_costs(db: Session, tenant_id: uuid.UUID, start: date | None, end: date | None) -> dict[str, Any]:
    start, end = _range(start, end)
    by_model = [dict(r) for r in db.execute(text("""
        SELECT provider, model, purpose, count(*) AS requests, sum(input_tokens) AS input_tokens,
               sum(output_tokens) AS output_tokens, round(avg(latency_ms)) AS avg_latency_ms,
               sum(estimated_cost) AS estimated_cost,
               count(*) FILTER (WHERE status <> 'success') AS errors
          FROM ai.tenant_model_usage WHERE created_at >= :s AND created_at < CAST(:e AS date) + 1
         GROUP BY provider, model, purpose ORDER BY estimated_cost DESC, requests DESC"""),
        {"s": start, "e": end}).mappings().all()]
    by_dept = [dict(r) for r in db.execute(text("""
        SELECT d.department_id, d.name, COALESCE(sum(u.searches), 0) AS searches, COALESCE(sum(u.chats), 0) AS chats,
               COALESCE(sum(u.input_tokens + u.output_tokens), 0) AS tokens, COALESCE(sum(u.estimated_cost), 0) AS estimated_cost
          FROM iam.departments d LEFT JOIN ops.department_usage_daily u
            ON u.department_id = d.department_id AND u.usage_date BETWEEN :s AND :e
         GROUP BY d.department_id, d.name ORDER BY estimated_cost DESC"""), {"s": start, "e": end}).mappings().all()]
    return {"range": {"start": start, "end": end}, "by_model": by_model, "by_department": by_dept,
            "quotas": [q.__dict__ | {"pct": q.pct} for q in quota_service.snapshot(db, tenant_id)], "cost_note": COST_NOTE}


def search_analytics(db: Session, start: date | None, end: date | None) -> dict[str, Any]:
    start, end = _range(start, end)
    p = {"s": start, "e": end}
    summary = db.execute(text("""SELECT count(*) AS searches, count(*) FILTER (WHERE result_count = 0) AS zero_result,
                                        round(avg(latency_ms)) AS avg_latency_ms,
                                        percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms,
                                        count(*) FILTER (WHERE cache_hit) AS cache_hits
                                   FROM rag.search_logs WHERE created_at >= :s AND created_at < CAST(:e AS date) + 1"""),
                         p).mappings().one()
    by_mode = [dict(r) for r in db.execute(text("""SELECT mode, count(*) AS n, round(avg(latency_ms)) AS avg_latency_ms
                                                    FROM rag.search_logs WHERE created_at >= :s AND created_at < CAST(:e AS date) + 1
                                                   GROUP BY mode"""), p).mappings().all()]
    return {"range": {"start": start, "end": end}, "summary": dict(summary), "by_mode": by_mode}


def chat_analytics(db: Session, start: date | None, end: date | None) -> dict[str, Any]:
    start, end = _range(start, end)
    p = {"s": start, "e": end}
    status = [dict(r) for r in db.execute(text("""SELECT answer_status, count(*) AS n, round(avg(latency_ms)) AS avg_latency_ms
                                                   FROM rag.conversation_messages WHERE role = 'assistant'
                                                    AND created_at >= :s AND created_at < CAST(:e AS date) + 1
                                                  GROUP BY answer_status"""), p).mappings().all()]
    evidence = [dict(r) for r in db.execute(text("""SELECT evidence_strength, count(*) AS n FROM rag.conversation_messages
                                                     WHERE role = 'assistant' AND created_at >= :s AND created_at < CAST(:e AS date) + 1
                                                     GROUP BY evidence_strength"""), p).mappings().all()]
    coverage = db.execute(text("""SELECT count(*) AS answers,
                                         count(*) FILTER (WHERE EXISTS (SELECT 1 FROM rag.message_sources s WHERE s.message_id = m.message_id)) AS with_citations,
                                         count(*) FILTER (WHERE EXISTS (SELECT 1 FROM rag.message_sources s WHERE s.message_id = m.message_id AND NOT s.verified)) AS with_unverified
                                    FROM rag.conversation_messages m WHERE role = 'assistant' AND answer_status = 'answered'
                                     AND created_at >= :s AND created_at < CAST(:e AS date) + 1"""), p).mappings().one()
    feedback = [dict(r) for r in db.execute(text("""SELECT category, status, count(*) AS n FROM rag.feedback
                                                     WHERE created_at >= :s AND created_at < CAST(:e AS date) + 1
                                                     GROUP BY category, status"""), p).mappings().all()]
    ans = coverage["answers"] or 0
    return {"range": {"start": start, "end": end}, "by_status": status, "by_evidence": evidence,
            "citation_coverage_pct": round(100 * coverage["with_citations"] / ans, 1) if ans else None,
            "unverified_citation_answers": coverage["with_unverified"], "feedback": feedback}


REPORTS = {
    "user_activity": """SELECT u.email::text AS email, u.display_name, a.usage_date, a.searches, a.chats, a.tokens
                          FROM ops.user_activity_daily a JOIN iam.users u ON u.user_id = a.user_id
                         WHERE a.usage_date BETWEEN :s AND :e ORDER BY a.usage_date, u.email""",
    "document_inventory": """SELECT d.document_id, d.title, c.code AS collection, d.document_type, d.insurance_line,
                                    d.classification, d.lifecycle_state, d.size_bytes, d.effective_from, d.effective_to,
                                    d.updated_at FROM content.documents d JOIN content.collections c ON c.collection_id = d.collection_id
                              WHERE d.deleted_at IS NULL ORDER BY c.code, d.title""",
    "ingestion_performance": """SELECT job_id, document_id, job_type, status, attempt, error_code, queued_at, started_at, finished_at,
                                       EXTRACT(EPOCH FROM (finished_at - started_at)) AS seconds
                                  FROM ingest.ingestion_jobs WHERE queued_at >= :s AND queued_at < CAST(:e AS date) + 1
                                 ORDER BY queued_at""",
    "search_usage": """SELECT usage_date, searches, avg_search_latency_ms, active_users FROM ops.tenant_usage_daily
                        WHERE usage_date BETWEEN :s AND :e ORDER BY usage_date""",
    "chat_usage": """SELECT usage_date, chats, conversations_started, abstentions, avg_llm_latency_ms FROM ops.tenant_usage_daily
                      WHERE usage_date BETWEEN :s AND :e ORDER BY usage_date""",
    "feedback": """SELECT feedback_id, category, rating, severity, status, created_at, resolved_at FROM rag.feedback
                    WHERE created_at >= :s AND created_at < CAST(:e AS date) + 1 ORDER BY created_at""",
    "token_consumption": """SELECT date_trunc('day', created_at)::date AS day, provider, model, purpose, sum(input_tokens) AS input_tokens,
                                   sum(output_tokens) AS output_tokens FROM ai.tenant_model_usage
                             WHERE created_at >= :s AND created_at < CAST(:e AS date) + 1 GROUP BY 1, 2, 3, 4 ORDER BY 1""",
    "estimated_expenditure": """SELECT date_trunc('day', created_at)::date AS day, provider, model, sum(estimated_cost) AS estimated_cost
                                  FROM ai.tenant_model_usage WHERE created_at >= :s AND created_at < CAST(:e AS date) + 1
                                 GROUP BY 1, 2, 3 ORDER BY 1""",
    "department_usage": """SELECT d.name AS department, u.usage_date, u.searches, u.chats, u.input_tokens + u.output_tokens AS tokens,
                                  u.estimated_cost FROM ops.department_usage_daily u JOIN iam.departments d
                                    ON d.department_id = u.department_id WHERE u.usage_date BETWEEN :s AND :e ORDER BY 2, 1""",
    "retrieval_quality": """SELECT r.run_id, ds.name AS dataset, r.mode, r.k, r.summary->>'recall_at_k' AS recall_at_k,
                                   r.summary->>'precision_at_k' AS precision_at_k, r.summary->>'mrr' AS mrr,
                                   r.summary->>'ndcg_at_k' AS ndcg_at_k, r.gate_passed, r.finished_at
                              FROM eval.evaluation_runs r JOIN eval.evaluation_datasets ds ON ds.dataset_id = r.dataset_id
                             WHERE r.created_at >= :s AND r.created_at < CAST(:e AS date) + 1 ORDER BY r.created_at""",
    "citation_coverage": """SELECT date_trunc('day', m.created_at)::date AS day, count(*) AS answers,
                                   count(*) FILTER (WHERE EXISTS (SELECT 1 FROM rag.message_sources s WHERE s.message_id = m.message_id)) AS cited
                              FROM rag.conversation_messages m WHERE m.role = 'assistant' AND m.answer_status = 'answered'
                               AND m.created_at >= :s AND m.created_at < CAST(:e AS date) + 1 GROUP BY 1 ORDER BY 1""",
}
# Search logs and conversation messages are owner-scoped (users' personal
# history).  Aggregate-only analytics over them run in a controlled worker
# context for the admin's own tenant and return counts, never rows or text
# (see PROJECT_ARCHITECTURE_DECISIONS.md, ADR-012).
OWNER_SCOPED = {"citation_coverage"}


def report_csv(db: Session, name: str, start: date | None, end: date | None) -> str:
    if name not in REPORTS:
        raise ValidationFailed(f"unknown report; available: {sorted(REPORTS)}")
    start, end = _range(start, end)
    result = db.execute(text(REPORTS[name]), {"s": start, "e": end})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(result.keys())
    for row in result:
        w.writerow(["" if v is None else v for v in row])
    return buf.getvalue()
