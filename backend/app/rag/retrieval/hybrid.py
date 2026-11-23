"""Permission-aware hybrid retrieval (spec 6.6, 6.7; FR-083..FR-111; extension 3).

Pipeline (all inside the caller's transaction, i.e. under RLS with the user's
tenant, principals, lines of business, jurisdictions and clearance):

  explicit tenant + metadata + lifecycle filters
  -> vector branch (pgvector HNSW, iterative scan) | full-text branch (websearch_to_tsquery
     + ts_rank_cd, OR fallback) | exact identifier branch (trigram / clause refs)
  -> RRF fusion -> dedupe (chunk id + content hash) -> final authorisation
     re-validation (chunk AND parent document visible) -> rerank (fallback to
     fused order) -> relevance threshold.

Nothing is fetched unrestricted and filtered later: every branch query carries
the ACL predicate both explicitly and through RLS.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.provider_registry import resolve_provider
from app.observability.metrics import CACHE_HITS, EMPTY_RETRIEVALS, RETRIEVAL_LATENCY
from app.observability.tracing import span
from app.rag.embeddings.providers import build_embeddings, vector_literal
from app.rag.hybrid_search.rrf import BranchHit, FusedHit, reciprocal_rank_fusion
from app.rag.ingestion.insurance_metadata import extract_identifiers
from app.rag.reranking.rerankers import LexicalOverlapReranker, build_reranker
from app.security.context import RequestContext
from app.services.config_service import AiConfig, RagConfig
from app.utils.cache import get_cache

log = logging.getLogger("app.retrieval")
SUPPORTED_DIMS = {384, 768, 1024, 1536}
_ID_TOKEN = re.compile(r"\b[A-Z]{2,6}[-/]?\d{2,}[A-Z0-9/-]*\b|\b(?:clause|section|exclusion|condition)\s+\d+(?:\.\d+)*[a-z]?\b", re.I)


@dataclass
class SearchFilters:
    collection_ids: list[uuid.UUID] = field(default_factory=list)
    document_types: list[str] = field(default_factory=list)
    lines_of_business: list[str] = field(default_factory=list)
    jurisdictions: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    document_ids: list[uuid.UUID] = field(default_factory=list)
    as_of: date | None = None
    include_superseded: bool = False

    def key(self) -> str:
        return json.dumps({k: sorted(map(str, v)) if isinstance(v, list) else str(v) for k, v in self.__dict__.items()},
                          sort_keys=True)


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    version_id: uuid.UUID
    parent_chunk_id: uuid.UUID | None
    title: str
    section_path: str | None
    clause_ref: str | None
    page_from: int | None
    page_to: int | None
    content: str
    document_type: str
    line_of_business: str | None
    jurisdictions: list[str]
    effective_from: date | None
    effective_to: date | None
    lifecycle_state: str
    version_label: str | None
    low_confidence: bool
    injection_flag: bool
    sensitivity_tags: list[str]
    score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float | None = None
    branch_ranks: dict[str, int] = field(default_factory=dict)
    branch_scores: dict[str, float] = field(default_factory=dict)
    parent_content: str | None = None

    def public(self, include_content: bool = True) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k not in ("parent_content",)}
        if not include_content:
            d.pop("content", None)
        return d


@dataclass
class SearchOutcome:
    results: list[RetrievedChunk]
    mode: str
    diagnostics: dict[str, Any]
    cache_hit: bool = False


def _filter_sql(f: SearchFilters, params: dict[str, Any], alias: str = "c") -> str:
    clauses = [f"{alias}.tenant_id = :tenant_id", f"{alias}.chunk_type <> 'parent'"]
    if f.as_of or f.include_superseded:
        clauses.append(f"{alias}.lifecycle_state IN ('published', 'superseded')")
    else:
        clauses.append(f"{alias}.lifecycle_state = 'published'")
    if f.as_of:
        # effective-date-aware retrieval (FR-086, FR-253, FR-264)
        clauses.append(f"({alias}.effective_from IS NULL OR {alias}.effective_from <= :as_of)")
        clauses.append(f"({alias}.effective_to IS NULL OR {alias}.effective_to >= :as_of)")
        clauses.append(f"""EXISTS (SELECT 1 FROM content.document_versions vv WHERE vv.version_id = {alias}.version_id
                           AND (vv.effective_from IS NULL OR vv.effective_from <= :as_of)
                           AND (vv.effective_to IS NULL OR vv.effective_to >= :as_of))""")
        params["as_of"] = f.as_of
    else:
        clauses.append(f"({alias}.effective_to IS NULL OR {alias}.effective_to >= CURRENT_DATE)")
    for col, values, cast in (("collection_id", f.collection_ids, "uuid[]"), ("document_type", f.document_types, "text[]"),
                              ("line_of_business", f.lines_of_business, "text[]"), ("product", f.products, "text[]"),
                              ("document_id", f.document_ids, "uuid[]")):
        if values:
            clauses.append(f"{alias}.{col} = ANY (CAST(:f_{col} AS {cast}))")
            params[f"f_{col}"] = [str(v) for v in values]
    if f.jurisdictions:
        clauses.append(f"({alias}.jurisdictions && CAST(:f_jur AS text[]) OR cardinality({alias}.jurisdictions) = 0)")
        params["f_jur"] = list(f.jurisdictions)
    # explicit ACL predicate (in addition to RLS - defence in depth)
    clauses.append(f"app.acl_visible({alias}.classification_rank, {alias}.line_of_business, {alias}.jurisdictions, "
                   f"{alias}.lifecycle_state, {alias}.allow_principals, {alias}.deny_principals)")
    return " AND ".join(clauses)


class HybridRetriever:
    def __init__(self, db: Session, ctx: RequestContext, rag: RagConfig, ai: AiConfig) -> None:
        self.db, self.ctx, self.rag, self.ai = db, ctx, rag, ai
        self._embedder = None
        lang = db.execute(text("SELECT default_language FROM platform.tenant_settings WHERE tenant_id = :t"),
                          {"t": ctx.tenant_id}).scalar() or "english"
        # A constant text-search configuration keeps the GIN index usable.
        self.fts_cfg = lang if lang in {"english", "simple", "french", "german", "spanish", "italian",
                                        "portuguese", "dutch"} else "english"

    # --- branches ---------------------------------------------------------------
    def _embed_query(self, query: str) -> list[float]:
        cache = get_cache()
        key = f"rag:{self.ctx.tenant_id}:emb:{self.ai.embedding_model}:{self.ai.embedding_dimensions}:" \
              f"{hashlib.sha256(query.encode()).hexdigest()}"
        try:
            hit = cache.get(key)
            if hit:
                return hit
        except Exception:
            hit = None
        if self._embedder is None:
            endpoint = resolve_provider(self.db, self.ai.embedding_provider)
            self._embedder = build_embeddings(endpoint, self.ai.embedding_model, self.ai.embedding_dimensions)
        vec = self._embedder.embed_query(query)
        try:
            cache.set(key, vec, get_settings().cache_ttl_seconds * 12)
        except Exception as exc:  # cache is an optimisation; retrieval continues without it
            log.warning("embedding cache write failed: %s", type(exc).__name__)
        return vec

    def vector_branch(self, query: str, f: SearchFilters, k: int) -> list[BranchHit]:
        dims = int(self.ai.embedding_dimensions)
        if dims not in SUPPORTED_DIMS:
            raise ValueError(f"no vector index for dimension {dims}")
        params: dict[str, Any] = {"tenant_id": self.ctx.tenant_id, "k": k, "model": self.ai.embedding_model,
                                  "q": vector_literal(self._embed_query(query))}
        where = _filter_sql(f, params)
        op = {"cosine": "<=>", "inner_product": "<#>", "l2": "<->"}[self.ai.distance_metric]
        score = {"cosine": f"1 - (e.embedding::vector({dims}) <=> CAST(:q AS vector({dims})))",
                 "inner_product": f"-(e.embedding::vector({dims}) <#> CAST(:q AS vector({dims})))",
                 "l2": f"-(e.embedding::vector({dims}) <-> CAST(:q AS vector({dims})))"}[self.ai.distance_metric]
        self.db.execute(text("SELECT set_config('hnsw.ef_search', :ef, true), set_config('hnsw.iterative_scan', 'relaxed_order', true)"),
                        {"ef": str(self.rag.hnsw_ef_search)})
        sql = f"""
            SELECT e.chunk_id, {score} AS score
              FROM content.chunk_embeddings e
              JOIN content.document_chunks c ON c.chunk_id = e.chunk_id AND c.tenant_id = e.tenant_id
             WHERE e.tenant_id = :tenant_id AND e.dimensions = {dims} AND e.is_active AND e.model_name = :model
               AND app.acl_visible(e.classification_rank, e.line_of_business, e.jurisdictions, e.lifecycle_state,
                                   e.allow_principals, e.deny_principals)
               AND {where}
             ORDER BY e.embedding::vector({dims}) {op} CAST(:q AS vector({dims}))
             LIMIT :k"""
        return [BranchHit(r[0], float(r[1])) for r in self.db.execute(text(sql), params).all()]

    def fulltext_branch(self, query: str, f: SearchFilters, k: int) -> list[BranchHit]:
        params: dict[str, Any] = {"tenant_id": self.ctx.tenant_id, "k": k, "q": query[:1000], "cfg": self.fts_cfg}
        where = _filter_sql(f, params)
        sql = f"""
            WITH q AS (SELECT websearch_to_tsquery(CAST(:cfg AS regconfig), :q) AS tsq)
            SELECT c.chunk_id, ts_rank_cd(c.content_tsv, q.tsq, 32) AS score
              FROM content.document_chunks c, q
             WHERE {where} AND c.content_tsv @@ q.tsq
             ORDER BY score DESC LIMIT :k"""
        rows = self.db.execute(text(sql), params).all()
        if not rows:
            # OR fallback so partial matches still surface (precision preserved by RRF + rerank)
            sql_or = f"""
                WITH q AS (SELECT NULLIF(replace(plainto_tsquery(CAST(:cfg AS regconfig), :q)::text, ' & ', ' | '), '')::tsquery AS tsq)
                SELECT c.chunk_id, ts_rank_cd(c.content_tsv, q.tsq, 32) AS score
                  FROM content.document_chunks c, q
                 WHERE {where} AND q.tsq IS NOT NULL AND c.content_tsv @@ q.tsq
                 ORDER BY score DESC LIMIT :k"""
            rows = self.db.execute(text(sql_or), params).all()
        return [BranchHit(r[0], float(r[1])) for r in rows]

    def exact_branch(self, query: str, f: SearchFilters, k: int) -> list[BranchHit]:
        """Exact policy / claim / form / clause numbers (FR-093, FR-099)."""
        ids = list(dict.fromkeys([m.group(0) for m in _ID_TOKEN.finditer(query)] + extract_identifiers(query)))[:5]
        if not ids or k <= 0:
            return []
        params: dict[str, Any] = {"tenant_id": self.ctx.tenant_id, "k": k}
        where = _filter_sql(f, params)
        ors = []
        for i, ident in enumerate(ids):
            params[f"id{i}"] = f"%{ident}%"
            clause = re.sub(r"(?i)^(clause|section|exclusion|condition)\s+", "", ident)
            params[f"cl{i}"] = clause
            ors.append(f"(c.identifiers ILIKE :id{i} OR c.clause_ref = :cl{i} OR c.section_path ILIKE :id{i})")
        sql = f"""SELECT c.chunk_id, 1.0 AS score FROM content.document_chunks c
                   WHERE {where} AND ({' OR '.join(ors)})
                   ORDER BY c.chunk_index LIMIT :k"""
        return [BranchHit(r[0], float(r[1])) for r in self.db.execute(text(sql), params).all()]

    # --- final authorisation + hydration ------------------------------------------------
    def hydrate(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, RetrievedChunk]:
        """Re-fetch under RLS and re-check the parent document's visibility, so a
        chunk can never be returned when its document is not accessible."""
        if not ids:
            return {}
        rows = self.db.execute(text("""
            SELECT c.chunk_id, c.document_id, c.version_id, c.parent_chunk_id, d.title, c.section_path, c.clause_ref,
                   c.page_from, c.page_to, c.content, c.document_type, c.line_of_business, c.jurisdictions,
                   c.effective_from, c.effective_to, c.lifecycle_state, v.version_label, c.low_confidence,
                   c.injection_flag, c.sensitivity_tags, p.content AS parent_content
              FROM content.document_chunks c
              JOIN content.documents d ON d.document_id = c.document_id AND d.tenant_id = c.tenant_id
              JOIN content.document_versions v ON v.version_id = c.version_id
              LEFT JOIN content.document_chunks p ON p.chunk_id = c.parent_chunk_id
             WHERE c.chunk_id = ANY (CAST(:ids AS uuid[])) AND c.tenant_id = :t AND d.deleted_at IS NULL
               AND app.acl_visible(d.classification_rank, d.insurance_line, d.jurisdictions, d.lifecycle_state,
                                   d.allow_principals, d.deny_principals)"""),
            {"ids": [str(i) for i in ids], "t": self.ctx.tenant_id}).mappings().all()
        out = {}
        for r in rows:
            data = dict(r)
            out[r["chunk_id"]] = RetrievedChunk(**data)
        return out

    # --- orchestration ---------------------------------------------------------------------------
    def search(self, query: str, filters: SearchFilters, *, mode: str = "hybrid", top_k: int | None = None,
               rerank: bool | None = None) -> SearchOutcome:
        with span("rag.retrieve", **{"rag.mode": mode, "tenant.id": str(self.ctx.tenant_id),
                                     "rag.config_version": self.rag.version}) as sp:
            out = self._search(query, filters, mode=mode, top_k=top_k, rerank=rerank)
            sp.set_attribute("rag.cache_hit", out.cache_hit)
            sp.set_attribute("rag.returned", len(out.results))
            sp.set_attribute("rag.authorization_filtered", out.diagnostics.get("authorization_filtered", 0))
            return out

    def _search(self, query: str, filters: SearchFilters, *, mode: str, top_k: int | None,
                rerank: bool | None) -> SearchOutcome:
        rag = self.rag
        top_k = top_k or rag.final_top_k
        rerank = rag.rerank_enabled if rerank is None else rerank
        diag: dict[str, Any] = {"mode": mode, "rag_config_version": rag.version, "ai_config_version": self.ai.version,
                                "timings_ms": {}}
        cache_key = self._cache_key(query, filters, mode, top_k, rerank)
        cached = self._cache_get(cache_key)
        branches: dict[str, list[BranchHit]] = {}
        if cached is not None:
            fused = [FusedHit(uuid.UUID(c["id"]), c["rrf"], c["ranks"], c["scores"]) for c in cached["fused"]]
            diag.update(cached.get("diag", {}))
            cache_hit = True
        else:
            cache_hit = False
            if mode in ("hybrid", "vector"):
                t = time.perf_counter()
                with span("rag.retrieve.vector"):
                    branches["vector"] = self.vector_branch(query, filters, rag.vector_top_k)
                diag["timings_ms"]["vector"] = round((time.perf_counter() - t) * 1000, 1)
                RETRIEVAL_LATENCY.labels("vector").observe(time.perf_counter() - t)
            if mode in ("hybrid", "fulltext"):
                t = time.perf_counter()
                with span("rag.retrieve.fulltext"):
                    branches["fulltext"] = self.fulltext_branch(query, filters, rag.fts_top_k)
                diag["timings_ms"]["fulltext"] = round((time.perf_counter() - t) * 1000, 1)
                RETRIEVAL_LATENCY.labels("fulltext").observe(time.perf_counter() - t)
            if mode in ("hybrid", "fulltext"):
                with span("rag.retrieve.exact"):
                    branches["exact"] = self.exact_branch(query, filters, rag.exact_top_k)
            weights = {"vector": rag.vector_weight, "fulltext": rag.fts_weight, "exact": rag.exact_weight}
            fused = reciprocal_rank_fusion(branches, weights, rag.rrf_k)
            diag["branch_counts"] = {b: len(h) for b, h in branches.items()}
            self._cache_set(cache_key, fused, diag)
        candidates = fused[: max(rag.rerank_top_n, top_k)]
        hydrated = self.hydrate([c.chunk_id for c in candidates])
        diag["authorization_filtered"] = len(candidates) - len(hydrated)
        results: list[RetrievedChunk] = []
        seen_hashes: set[str] = set()
        for c in candidates:
            chunk = hydrated.get(c.chunk_id)
            if chunk is None:
                continue
            h = hashlib.sha256(re.sub(r"\s+", " ", chunk.content).encode()).hexdigest()
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            chunk.rrf_score, chunk.branch_ranks, chunk.branch_scores = c.rrf_score, c.branch_ranks, c.branch_scores
            chunk.score = c.rrf_score
            results.append(chunk)
        if rerank and results:
            t = time.perf_counter()
            try:
                endpoint = resolve_provider(self.db, self.ai.reranker_provider)
                reranker = build_reranker(endpoint, self.ai.reranker_model)
                scores = reranker.score(query, [r.content for r in results])
                diag["reranker"] = reranker.name
            except Exception as exc:  # graceful degradation (NFR-026): keep fused order
                log.warning("reranker unavailable, using fused ranking: %s", type(exc).__name__)
                diag["reranker"] = "fallback:fused"
                scores = None
            if scores is not None:
                for r, s in zip(results, scores, strict=True):
                    r.rerank_score = float(s)
                    r.score = float(s)
                results.sort(key=lambda r: (-(r.rerank_score or 0.0), -r.rrf_score))
            diag["timings_ms"]["rerank"] = round((time.perf_counter() - t) * 1000, 1)
            RETRIEVAL_LATENCY.labels("rerank").observe(time.perf_counter() - t)
        if rag.min_relevance > 0:
            results = [r for r in results if r.score >= rag.min_relevance]
        results = results[:top_k]
        if not results:
            EMPTY_RETRIEVALS.inc()
        diag["returned"] = len(results)
        return SearchOutcome(results=results, mode=mode, diagnostics=diag, cache_hit=cache_hit)

    # --- permission-fingerprinted cache (FR-108) ------------------------------------------------
    def _cache_key(self, query: str, f: SearchFilters, mode: str, top_k: int, rerank: bool) -> str:
        epoch = self.db.execute(text("SELECT content_epoch FROM platform.tenant_usage WHERE tenant_id = :t"),
                                {"t": self.ctx.tenant_id}).scalar() or 0
        digest = hashlib.sha256("|".join([query, f.key(), mode, str(top_k), str(rerank)]).encode()).hexdigest()
        return (f"rag:{self.ctx.tenant_id}:ret:{self.ctx.permission_fingerprint()}:e{epoch}:"
                f"r{self.rag.version}:a{self.ai.version}:{digest}")

    def _cache_get(self, key: str) -> dict | None:
        try:
            hit = get_cache().get(key)
        except Exception:
            return None
        CACHE_HITS.labels("hit" if hit else "miss").inc()
        return hit

    def _cache_set(self, key: str, fused: list[FusedHit], diag: dict[str, Any]) -> None:
        try:
            get_cache().set(key, {"fused": [{"id": str(h.chunk_id), "rrf": h.rrf_score, "ranks": h.branch_ranks,
                                             "scores": h.branch_scores} for h in fused[:200]],
                                  "diag": {"branch_counts": diag.get("branch_counts")}}, get_settings().cache_ttl_seconds)
        except Exception as exc:  # cache is an optimisation; retrieval continues without it
            log.warning("retrieval cache write failed: %s", type(exc).__name__)


def local_rerank(query: str, chunks: list[RetrievedChunk]) -> list[float]:
    return LexicalOverlapReranker().score(query, [c.content for c in chunks])
