"""Scheduled usage aggregation (extension 10; FR-216..FR-222, NFR-078, NFR-107).

Tenants are enumerated in `scheduler` mode (tenant id + status only); each
tenant is then aggregated in its OWN transaction under a worker context for
that tenant, so a batch job never mixes tenants.  Dashboards read the
resulting daily aggregates instead of scanning raw tables on every page load.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import text

from app.database.session import SecurityContext, scoped_session
from app.utils.clock import utc_today

log = logging.getLogger("app.aggregation")

_TENANT_DAY = text("""
WITH bounds AS (SELECT CAST(:d AS date) AS d0, CAST(:d AS date) + 1 AS d1),
s AS (SELECT count(*) FILTER (WHERE mode <> 'chat') AS searches, avg(latency_ms) FILTER (WHERE mode <> 'chat') AS lat
        FROM rag.search_logs, bounds WHERE created_at >= d0 AND created_at < d1),
m AS (SELECT count(*) FILTER (WHERE role = 'assistant') AS chats,
             count(*) FILTER (WHERE role = 'assistant' AND answer_status = 'abstained') AS abst
        FROM rag.conversation_messages, bounds WHERE created_at >= d0 AND created_at < d1),
c AS (SELECT count(*) AS started FROM rag.conversations, bounds WHERE created_at >= d0 AND created_at < d1),
u AS (SELECT count(*) FILTER (WHERE purpose IN ('chat', 'rewrite', 'judge')) AS req,
             COALESCE(sum(input_tokens), 0) AS tin, COALESCE(sum(output_tokens), 0) AS tout,
             COALESCE(sum(estimated_cost), 0) AS cost, avg(latency_ms) FILTER (WHERE purpose = 'chat') AS llm_lat
        FROM ai.tenant_model_usage, bounds WHERE created_at >= d0 AND created_at < d1),
j AS (SELECT count(*) FILTER (WHERE status = 'succeeded' AND job_type IN ('ingest', 'reprocess')) AS ok,
             count(*) FILTER (WHERE status IN ('failed', 'dead_letter')) AS bad
        FROM ingest.ingestion_jobs, bounds WHERE finished_at >= d0 AND finished_at < d1),
a AS (SELECT count(DISTINCT user_id) AS active FROM (
        SELECT user_id FROM rag.search_logs, bounds WHERE created_at >= d0 AND created_at < d1
        UNION SELECT user_id FROM rag.conversation_messages, bounds WHERE created_at >= d0 AND created_at < d1) x),
f AS (SELECT count(*) FILTER (WHERE rating = 1) AS pos, count(*) FILTER (WHERE rating = -1 OR category <> 'rating') AS neg
        FROM rag.feedback, bounds WHERE created_at >= d0 AND created_at < d1),
g AS (SELECT count(*) FILTER (WHERE decision IN ('block', 'quarantine')) AS blocks
        FROM ai.guardrail_events, bounds WHERE occurred_at >= d0 AND occurred_at < d1),
snap AS (SELECT (SELECT count(*) FROM content.documents WHERE deleted_at IS NULL) AS docs,
                (SELECT count(*) FROM content.document_chunks) AS chunks,
                (SELECT COALESCE(sum(size_bytes), 0) FROM content.documents WHERE deleted_at IS NULL) AS bytes,
                (SELECT count(*) FROM iam.users WHERE status = 'active') AS users)
INSERT INTO ops.tenant_usage_daily (tenant_id, usage_date, searches, chats, conversations_started, ai_requests,
       input_tokens, output_tokens, estimated_cost, documents_ingested, ingestion_failures, active_users,
       avg_search_latency_ms, avg_llm_latency_ms, abstentions, feedback_positive, feedback_negative, guardrail_blocks,
       documents_total, chunks_total, storage_bytes, users_total, computed_at)
SELECT :t, :d, s.searches, m.chats, c.started, u.req, u.tin, u.tout, u.cost, j.ok, j.bad, a.active, s.lat, u.llm_lat,
       m.abst, f.pos, f.neg, g.blocks, snap.docs, snap.chunks, snap.bytes, snap.users, now()
  FROM s, m, c, u, j, a, f, g, snap
ON CONFLICT (tenant_id, usage_date) DO UPDATE SET
  searches = EXCLUDED.searches, chats = EXCLUDED.chats, conversations_started = EXCLUDED.conversations_started,
  ai_requests = EXCLUDED.ai_requests, input_tokens = EXCLUDED.input_tokens, output_tokens = EXCLUDED.output_tokens,
  estimated_cost = EXCLUDED.estimated_cost, documents_ingested = EXCLUDED.documents_ingested,
  ingestion_failures = EXCLUDED.ingestion_failures, active_users = EXCLUDED.active_users,
  avg_search_latency_ms = EXCLUDED.avg_search_latency_ms, avg_llm_latency_ms = EXCLUDED.avg_llm_latency_ms,
  abstentions = EXCLUDED.abstentions, feedback_positive = EXCLUDED.feedback_positive,
  feedback_negative = EXCLUDED.feedback_negative, guardrail_blocks = EXCLUDED.guardrail_blocks,
  documents_total = EXCLUDED.documents_total, chunks_total = EXCLUDED.chunks_total,
  storage_bytes = EXCLUDED.storage_bytes, users_total = EXCLUDED.users_total, computed_at = now()
""")

_DEPT_DAY = text("""
INSERT INTO ops.department_usage_daily (tenant_id, usage_date, department_id, searches, chats, input_tokens, output_tokens,
                                        estimated_cost, active_users)
SELECT :t, :d, x.department_id, sum(x.searches), sum(x.chats), sum(x.tin), sum(x.tout), sum(x.cost), count(DISTINCT x.user_id)
  FROM (SELECT department_id, user_id, 1 AS searches, 0 AS chats, 0 AS tin, 0 AS tout, 0::numeric AS cost
          FROM rag.search_logs WHERE created_at >= CAST(:d AS date) AND created_at < CAST(:d AS date) + 1 AND mode <> 'chat'
        UNION ALL
        SELECT department_id, user_id, 0, CASE WHEN purpose = 'chat' THEN 1 ELSE 0 END, input_tokens, output_tokens, estimated_cost
          FROM ai.tenant_model_usage WHERE created_at >= CAST(:d AS date) AND created_at < CAST(:d AS date) + 1
           AND purpose <> 'ingestion_embedding') x
 WHERE x.department_id IS NOT NULL
 GROUP BY x.department_id
ON CONFLICT (tenant_id, usage_date, department_id) DO UPDATE SET searches = EXCLUDED.searches, chats = EXCLUDED.chats,
  input_tokens = EXCLUDED.input_tokens, output_tokens = EXCLUDED.output_tokens, estimated_cost = EXCLUDED.estimated_cost,
  active_users = EXCLUDED.active_users
""")

_USER_DAY = text("""
INSERT INTO ops.user_activity_daily (tenant_id, usage_date, user_id, searches, chats, tokens)
SELECT :t, :d, user_id, sum(se), sum(ch), sum(tok) FROM (
   SELECT user_id, 1 AS se, 0 AS ch, 0 AS tok FROM rag.search_logs
    WHERE created_at >= CAST(:d AS date) AND created_at < CAST(:d AS date) + 1 AND mode <> 'chat'
   UNION ALL
   SELECT user_id, 0, 1, input_tokens + output_tokens FROM rag.conversation_messages
    WHERE created_at >= CAST(:d AS date) AND created_at < CAST(:d AS date) + 1 AND role = 'assistant') x
 GROUP BY user_id
ON CONFLICT (tenant_id, usage_date, user_id) DO UPDATE SET searches = EXCLUDED.searches, chats = EXCLUDED.chats,
  tokens = EXCLUDED.tokens
""")

_RECONCILE = text("""
UPDATE platform.tenant_usage SET
  users_count = (SELECT count(*) FROM iam.users WHERE status = 'active'),
  documents_count = (SELECT count(*) FROM content.documents WHERE deleted_at IS NULL),
  collections_count = (SELECT count(*) FROM content.collections),
  chunks_count = (SELECT count(*) FROM content.document_chunks),
  storage_bytes = (SELECT COALESCE(sum(v.size_bytes), 0) FROM content.document_versions v
                    JOIN content.documents d ON d.document_id = v.document_id WHERE d.deleted_at IS NULL),
  active_ingestion_jobs = (SELECT count(*) FROM ingest.ingestion_jobs WHERE status IN ('queued', 'running', 'retrying')),
  updated_at = now()
WHERE tenant_id = :t
""")


def list_tenants(statuses: tuple[str, ...] | None = None) -> list[tuple[uuid.UUID, str]]:
    with scoped_session(SecurityContext(access_mode="scheduler"), role="worker") as db:
        rows = db.execute(text("SELECT tenant_id, status FROM platform.tenants ORDER BY created_at")).all()
    return [(r[0], r[1]) for r in rows if statuses is None or r[1] in statuses]


def aggregate_tenant(tenant_id: uuid.UUID, day: date, reconcile: bool = True) -> None:
    with scoped_session(SecurityContext.worker(tenant_id), role="worker") as db:
        db.execute(_TENANT_DAY, {"t": tenant_id, "d": day})
        db.execute(_DEPT_DAY, {"t": tenant_id, "d": day})
        db.execute(_USER_DAY, {"t": tenant_id, "d": day})
        if reconcile:
            db.execute(_RECONCILE, {"t": tenant_id})


def aggregate_all(days_back: int = 1) -> int:
    today = utc_today()
    n = 0
    for tenant_id, status in list_tenants():
        if status == "archived":
            continue
        for offset in range(days_back + 1):
            try:
                aggregate_tenant(tenant_id, today - timedelta(days=offset), reconcile=offset == 0)
                n += 1
            except Exception:
                log.exception("aggregation failed for tenant", extra={"tenant": str(tenant_id)})
    return n
