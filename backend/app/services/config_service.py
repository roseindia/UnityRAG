"""Tenant AI / RAG configuration with versioning and platform guard-rails
(FR-079, FR-095, FR-170..FR-172, NFR-088, NFR-090, extension 7.7).

A change never edits a row: it inserts version N+1 and activates it (the
previous version stays for audit and rollback).  Tenant administrators may
change only the settings listed in tenant_settings.tenant_overridable_ai_settings
(set by the platform) and may select models only from the approved catalogue.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.database.session import SecurityContext
from app.integrations.provider_registry import assert_model_allowed
from app.services.audit import tenant_audit


@dataclass(frozen=True)
class AiConfig:
    version: int
    llm_provider: str
    chat_model: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    reranker_provider: str
    reranker_model: str
    rewrite_model: str | None
    temperature: float
    max_output_tokens: int
    distance_metric: str


@dataclass(frozen=True)
class RagConfig:
    version: int
    chunking_strategy: str
    chunk_size: int
    chunk_overlap: int
    parent_child: bool
    vector_top_k: int
    fts_top_k: int
    exact_top_k: int
    vector_weight: float
    fts_weight: float
    exact_weight: float
    rrf_k: int
    rerank_enabled: bool
    rerank_top_n: int
    final_top_k: int
    max_context_tokens: int
    min_relevance: float
    hnsw_ef_search: int
    citation_required: bool
    query_rewriting: bool
    guardrails: dict[str, Any]


AI_FIELDS = [f.name for f in fields(AiConfig) if f.name != "version"]
RAG_FIELDS = [f.name for f in fields(RagConfig) if f.name != "version"]
_MODEL_FIELDS = {"llm_provider", "chat_model", "embedding_provider", "embedding_model", "embedding_dimensions",
                 "reranker_provider", "reranker_model", "rewrite_model", "distance_metric"}


def _load(db: Session, table: str, cls: type) -> Any:
    row = db.execute(text(f"SELECT * FROM ai.{table} WHERE is_active")).mappings().first()
    if row is None:
        raise NotFound(f"No active {table} for tenant")
    return cls(**{f.name: row[f.name] for f in fields(cls)})


def active_ai_config(db: Session) -> AiConfig:
    return _load(db, "tenant_ai_configurations", AiConfig)


def active_rag_config(db: Session) -> RagConfig:
    return _load(db, "tenant_rag_configurations", RagConfig)


def _overridable(db: Session) -> set[str]:
    return set(db.execute(text("SELECT tenant_overridable_ai_settings FROM platform.tenant_settings "
                               "WHERE tenant_id = app.current_tenant_id()")).scalar() or [])


def _new_version(db: Session, sec: SecurityContext, table: str, allowed_fields: list[str], changes: dict[str, Any],
                 reason: str | None, *, platform_override: bool) -> dict[str, Any]:
    current = db.execute(text(f"SELECT * FROM ai.{table} WHERE is_active FOR UPDATE")).mappings().first()
    if current is None:
        raise NotFound("No active configuration")
    unknown = set(changes) - set(allowed_fields)
    if unknown:
        raise ValidationFailed("Unknown configuration fields", details=[{"field": f, "message": "unknown"} for f in unknown])
    if not platform_override:
        permitted = _overridable(db)
        blocked = [k for k, v in changes.items() if v != current[k] and k not in permitted and k not in _MODEL_FIELDS]
        if blocked:
            raise PermissionDenied("These settings are not permitted for tenant administrators: " + ", ".join(sorted(blocked)),
                                   code="setting_not_overridable")
    merged = {k: (changes[k] if k in changes else current[k]) for k in allowed_fields}
    version = int(current["version"]) + 1
    cols = ", ".join(allowed_fields)
    vals = ", ".join(f"CAST(:{k} AS jsonb)" if k == "guardrails" else f":{k}" for k in allowed_fields)
    params = dict(merged)
    if "guardrails" in params:
        import json

        params["guardrails"] = json.dumps(params["guardrails"])
    db.execute(text(f"UPDATE ai.{table} SET is_active = false WHERE is_active"))
    db.execute(text(f"INSERT INTO ai.{table} (tenant_id, version, {cols}, is_active, change_reason, created_by) "
                    f"VALUES (:tenant_id, :version, {vals}, true, :reason, :by)"),
               {**params, "tenant_id": sec.tenant_id, "version": version, "reason": reason, "by": sec.user_id})
    diff = {k: {"before": current[k], "after": merged[k]} for k in allowed_fields if current[k] != merged[k]}
    tenant_audit(db, tenant_id=sec.tenant_id, category="configuration", event_type=f"{table}_changed",  # type: ignore[arg-type]
                 actor_user_id=sec.user_id, actor_account_id=sec.account_id, resource_type=table,
                 resource_id=version, detail={"diff": diff, "reason": reason})
    return dict(db.execute(text(f"SELECT * FROM ai.{table} WHERE is_active")).mappings().one())


def update_ai_config(db: Session, sec: SecurityContext, changes: dict[str, Any], reason: str | None,
                     platform_override: bool = False) -> dict[str, Any]:
    current = active_ai_config(db)
    merged = {**{k: getattr(current, k) for k in AI_FIELDS}, **changes}
    assert_model_allowed(db, merged["llm_provider"], merged["chat_model"], "chat")
    emb = assert_model_allowed(db, merged["embedding_provider"], merged["embedding_model"], "embedding")
    if emb.get("dimensions") and int(emb["dimensions"]) != int(merged["embedding_dimensions"]):
        raise ValidationFailed(f"Embedding model {merged['embedding_model']} produces {emb['dimensions']} dimensions, "
                               f"not {merged['embedding_dimensions']}")
    from app.rag.retrieval.hybrid import SUPPORTED_DIMS  # local import: avoids a service <-> retrieval cycle

    if int(merged["embedding_dimensions"]) not in SUPPORTED_DIMS:
        raise ValidationFailed(f"No vector index exists for {merged['embedding_dimensions']} dimensions; "
                               f"supported: {sorted(SUPPORTED_DIMS)}")
    if merged["reranker_provider"] != "local" or merged["reranker_model"] != "lexical-overlap-v1":
        assert_model_allowed(db, merged["reranker_provider"], merged["reranker_model"], "rerank")
    return _new_version(db, sec, "tenant_ai_configurations", AI_FIELDS, changes, reason,
                        platform_override=platform_override)


def update_rag_config(db: Session, sec: SecurityContext, changes: dict[str, Any], reason: str | None,
                      platform_override: bool = False) -> dict[str, Any]:
    cur = active_rag_config(db)
    size = changes.get("chunk_size", cur.chunk_size)
    overlap = changes.get("chunk_overlap", cur.chunk_overlap)
    if overlap >= size:
        raise ValidationFailed("chunk_overlap must be smaller than chunk_size")
    return _new_version(db, sec, "tenant_rag_configurations", RAG_FIELDS, changes, reason,
                        platform_override=platform_override)


def rollback(db: Session, sec: SecurityContext, table: str, version: int) -> dict[str, Any]:
    if table not in ("tenant_ai_configurations", "tenant_rag_configurations"):
        raise ValidationFailed("unknown configuration type")
    target = db.execute(text(f"SELECT * FROM ai.{table} WHERE version = :v"), {"v": version}).mappings().first()
    if target is None:
        raise NotFound("Configuration version not found")
    allowed = AI_FIELDS if table == "tenant_ai_configurations" else RAG_FIELDS
    return _new_version(db, sec, table, allowed, {k: target[k] for k in allowed}, f"rollback to v{version}",
                        platform_override=True)


def history(db: Session, table: str, limit: int = 50) -> list[dict[str, Any]]:
    if table not in ("tenant_ai_configurations", "tenant_rag_configurations"):
        raise ValidationFailed("unknown configuration type")
    return [dict(r) for r in db.execute(text(f"SELECT * FROM ai.{table} ORDER BY version DESC LIMIT :l"),
                                        {"l": limit}).mappings().all()]
