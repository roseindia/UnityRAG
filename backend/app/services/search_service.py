"""Search API service: vector, full-text and hybrid search without generation
(FR-015, FR-084..FR-099, FR-186, FR-226), with search history (FR-019)."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.context import get_correlation_id
from app.core.errors import ValidationFailed
from app.database.session import scoped_session
from app.rag.retrieval.hybrid import HybridRetriever, RetrievedChunk, SearchFilters
from app.security.context import RequestContext
from app.services import config_service
from app.services.audit import tenant_audit


def _store_query_text(db: Session) -> bool:
    return bool(db.execute(text("SELECT store_query_text FROM platform.tenant_settings WHERE tenant_id = app.current_tenant_id()")).scalar())


def log_search(db: Session, ctx: RequestContext, *, query: str, mode: str, filters: SearchFilters,
               results: list[RetrievedChunk], latency_ms: int, rag_version: int, cache_hit: bool,
               conversation_id: uuid.UUID | None = None, message_id: uuid.UUID | None = None,
               candidates: list[RetrievedChunk] | None = None) -> uuid.UUID:
    search_id = uuid.uuid4()
    db.execute(text("""INSERT INTO rag.search_logs (tenant_id, search_id, user_id, department_id, conversation_id, message_id,
                              mode, query_hash, query_text, filters, policy_scope_hash, rag_config_version, result_count,
                              top_score, latency_ms, cache_hit, correlation_id)
                       VALUES (:t, :s, :u, :dep, :c, :m, :mode, :qh, :qt, CAST(:f AS jsonb), :ph, :rv, :n, :top, :lat,
                               :hit, :cid)"""),
               {"t": ctx.tenant_id, "s": search_id, "u": ctx.user_id, "dep": ctx.department_id, "c": conversation_id,
                "m": message_id, "mode": mode, "qh": hashlib.sha256(query.encode()).hexdigest(),
                "qt": query[:2000] if _store_query_text(db) else None, "f": filters.key(),
                "ph": ctx.permission_fingerprint(), "rv": rag_version, "n": len(results),
                "top": max((r.score for r in results), default=None), "lat": latency_ms, "hit": cache_hit,
                "cid": get_correlation_id()})
    selected = {r.chunk_id for r in results}
    for stage, items in (("fused", candidates or results), ("context" if message_id else "reranked", results)):
        for rank, r in enumerate(items, start=1):
            db.execute(text("""INSERT INTO rag.retrieval_logs (tenant_id, search_id, user_id, stage, rank, chunk_id, document_id,
                                      score, selected) VALUES (:t, :s, :u, :st, :r, :c, :d, :sc, :sel)"""),
                       {"t": ctx.tenant_id, "s": search_id, "u": ctx.user_id, "st": stage, "r": rank, "c": r.chunk_id,
                        "d": r.document_id, "sc": r.score, "sel": r.chunk_id in selected})
    tenant_audit(db, tenant_id=ctx.tenant_id, category="search", event_type=f"{mode}_search",  # type: ignore[arg-type]
                 actor_user_id=ctx.user_id, actor_account_id=ctx.account_id, resource_type="search", resource_id=search_id,
                 detail={"query_hash": hashlib.sha256(query.encode()).hexdigest()[:16], "query_length": len(query),
                         "result_count": len(results), "latency_ms": latency_ms, "filters": json.loads(filters.key()),
                         "policy_scope_hash": ctx.permission_fingerprint()})
    tenant_audit(db, tenant_id=ctx.tenant_id, category="retrieval", event_type="chunks_returned",  # type: ignore[arg-type]
                 actor_user_id=ctx.user_id, resource_type="search", resource_id=search_id,
                 detail={"chunks": [{"chunk_id": str(r.chunk_id), "document_id": str(r.document_id),
                                     "version_id": str(r.version_id), "score": round(r.score, 4)} for r in results]})
    return search_id


def _highlights(db: Session, query: str, ids: list[uuid.UUID], cfg: str) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = db.execute(text("""SELECT c.chunk_id, ts_headline(CAST(:cfg AS regconfig), c.content,
                                     websearch_to_tsquery(CAST(:cfg AS regconfig), :q),
                                     'MaxFragments=2, MaxWords=35, MinWords=12, StartSel=<mark>, StopSel=</mark>')
                                FROM content.document_chunks c WHERE c.chunk_id = ANY (CAST(:ids AS uuid[]))"""),
                      {"cfg": cfg, "q": query, "ids": [str(i) for i in ids]}).all()
    return {r[0]: r[1] for r in rows}


def search(ctx: RequestContext, *, query: str, filters: SearchFilters, mode: str = "hybrid", top_k: int | None = None,
           rerank: bool | None = None) -> dict[str, Any]:
    if mode not in ("hybrid", "vector", "fulltext"):
        raise ValidationFailed("mode must be hybrid, vector or fulltext")
    query = (query or "").strip()
    if not query or len(query) > 2000:
        raise ValidationFailed("query must be 1-2000 characters")
    t0 = time.perf_counter()
    with scoped_session(ctx.security("user")) as db:
        rag = config_service.active_rag_config(db)
        ai = config_service.active_ai_config(db)
        retriever = HybridRetriever(db, ctx, rag, ai)
        out = retriever.search(query, filters, mode=mode, top_k=top_k, rerank=rerank)
        latency = int((time.perf_counter() - t0) * 1000)
        search_id = log_search(db, ctx, query=query, mode=mode, filters=filters, results=out.results,
                               latency_ms=latency, rag_version=rag.version, cache_hit=out.cache_hit)
        hl = _highlights(db, query, [r.chunk_id for r in out.results], retriever.fts_cfg)
        results = []
        for r in out.results:
            item = r.public(include_content=True)
            item["highlight"] = hl.get(r.chunk_id)
            item["explanation"] = {"matched_branches": sorted(r.branch_ranks), "branch_ranks": r.branch_ranks,
                                   "branch_scores": r.branch_scores, "rrf_score": round(r.rrf_score, 6),
                                   "rerank_score": r.rerank_score}
            results.append(item)
        return {"search_id": search_id, "mode": mode, "query": query, "results": results, "latency_ms": latency,
                "cache_hit": out.cache_hit, "diagnostics": out.diagnostics,
                "filters_applied": json.loads(filters.key())}


def history(ctx: RequestContext, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    with scoped_session(ctx.security("user")) as db:
        total = db.execute(text("SELECT count(*) FROM rag.search_logs")).scalar_one()
        rows = db.execute(text("""SELECT search_id, mode, query_text, filters, result_count, latency_ms, created_at
                                    FROM rag.search_logs ORDER BY created_at DESC LIMIT :l OFFSET :o"""),
                          {"l": limit, "o": offset}).mappings().all()
        return [dict(r) for r in rows], int(total)


_FACETS = text("""
WITH d AS (SELECT d.collection_id, d.document_type, d.insurance_line, d.product, d.jurisdictions, d.lifecycle_state,
                  d.classification, d.effective_from
             FROM content.documents d WHERE d.deleted_at IS NULL)
SELECT 'collection' AS facet, c.collection_id::text AS value, c.name AS label, count(*) AS n
  FROM d JOIN content.collections c ON c.collection_id = d.collection_id GROUP BY c.collection_id, c.name
UNION ALL SELECT 'document_type', document_type, NULL, count(*) FROM d WHERE document_type IS NOT NULL GROUP BY 2
UNION ALL SELECT 'line_of_business', insurance_line, NULL, count(*) FROM d WHERE insurance_line IS NOT NULL GROUP BY 2
UNION ALL SELECT 'product', product, NULL, count(*) FROM d WHERE product IS NOT NULL GROUP BY 2
UNION ALL SELECT 'jurisdiction', j, NULL, count(*) FROM d, unnest(d.jurisdictions) AS j GROUP BY 2
UNION ALL SELECT 'lifecycle_state', lifecycle_state, NULL, count(*) FROM d GROUP BY 2
UNION ALL SELECT 'classification', classification, NULL, count(*) FROM d GROUP BY 2
UNION ALL SELECT 'effective_year', extract(year FROM effective_from)::int::text, NULL, count(*) FROM d
           WHERE effective_from IS NOT NULL GROUP BY 2
ORDER BY 1, 4 DESC, 2
""")


def facets(ctx: RequestContext) -> dict[str, list[dict[str, Any]]]:
    """Filter values with document counts (FR-016).  Runs in `user` mode, so RLS + the
    ACL predicate guarantee that only values of documents the caller may see appear."""
    with scoped_session(ctx.security("user")) as db:
        out: dict[str, list[dict[str, Any]]] = {}
        for facet, value, label, n in db.execute(_FACETS).all():
            out.setdefault(facet, []).append({"value": value, "label": label or value, "count": int(n)})
        return out
