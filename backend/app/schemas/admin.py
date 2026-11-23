"""Request schemas for tenant administration and document management."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ApiModel

PrincipalType = Literal["user", "group", "role", "department", "team", "everyone"]


class UserCreate(ApiModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str = Field(min_length=1, max_length=200)
    password: str | None = Field(None, min_length=12, max_length=256)
    auth_provider: Literal["local", "oidc"] = "local"
    external_subject: str | None = None
    user_type: Literal["employee", "broker", "agent", "service"] = "employee"
    department_id: uuid.UUID | None = None
    business_unit: str | None = None
    country: str | None = None
    lines_of_business: list[str] = []
    jurisdictions: list[str] = []
    clearance_rank: int = Field(1, ge=0, le=3)
    roles: list[str] = ["member"]
    group_ids: list[uuid.UUID] = []


class UserUpdate(ApiModel):
    display_name: str | None = None
    user_type: Literal["employee", "broker", "agent", "service"] | None = None
    department_id: uuid.UUID | None = None
    business_unit: str | None = None
    country: str | None = None
    lines_of_business: list[str] | None = None
    jurisdictions: list[str] | None = None
    clearance_rank: int | None = Field(None, ge=0, le=3)


class RoleAssign(ApiModel):
    role_id: uuid.UUID | None = None
    role_code: str | None = None
    valid_to: datetime | None = None


class RoleCreate(ApiModel):
    code: str = Field(pattern=r"^[a-z0-9_]{2,60}$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    permissions: list[str]
    conflicts_with: list[str] = []


class RoleUpdate(ApiModel):
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None


class DepartmentCreate(ApiModel):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{2,40}$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    parent_department_id: uuid.UUID | None = None


class DepartmentUpdate(ApiModel):
    name: str | None = None
    description: str | None = None
    status: Literal["active", "inactive"] | None = None


class TeamCreate(ApiModel):
    department_id: uuid.UUID
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None


class GroupCreate(ApiModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None


class MemberRef(ApiModel):
    user_id: uuid.UUID


class AccessEntry(ApiModel):
    principal_type: PrincipalType
    principal_id: uuid.UUID | None = None
    effect: Literal["allow", "deny"] = "allow"


class CollectionGrant(AccessEntry):
    permission: Literal["read", "write", "manage"] = "read"


class CollectionCreate(ApiModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,59}$")
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    department_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    line_of_business: str | None = None
    jurisdictions: list[str] = []
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    retention_days: int | None = Field(None, gt=0)
    auto_publish: bool = True
    access: list[CollectionGrant] = []


class CollectionUpdate(ApiModel):
    name: str | None = None
    description: str | None = None
    department_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    line_of_business: str | None = None
    jurisdictions: list[str] | None = None
    classification: Literal["public", "internal", "confidential", "restricted"] | None = None
    retention_days: int | None = None
    auto_publish: bool | None = None
    status: Literal["active", "archived"] | None = None


class DocumentMetadataUpdate(ApiModel):
    title: str | None = Field(None, max_length=300)
    document_type: str | None = None
    insurance_line: str | None = None
    product: str | None = None
    jurisdictions: list[str] | None = None
    classification: Literal["public", "internal", "confidential", "restricted"] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    review_due_at: date | None = None
    language: str | None = None
    owner_user_id: uuid.UUID | None = None
    legally_privileged: bool | None = None


class LifecycleChange(ApiModel):
    state: Literal["published", "archived", "withdrawn", "expired", "in_review", "approved"]
    reason: str | None = None


class LegalHold(ApiModel):
    hold: bool
    reason: str = Field(min_length=10)


class AiConfigUpdate(ApiModel):
    llm_provider: str | None = None
    chat_model: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    reranker_provider: str | None = None
    reranker_model: str | None = None
    rewrite_model: str | None = None
    temperature: float | None = Field(None, ge=0, le=2)
    max_output_tokens: int | None = Field(None, ge=16, le=16000)
    distance_metric: Literal["cosine", "inner_product", "l2"] | None = None
    reason: str | None = None


class RagConfigUpdate(ApiModel):
    chunking_strategy: Literal["fixed", "recursive", "structure_aware"] | None = None
    chunk_size: int | None = Field(None, ge=64, le=4000)
    chunk_overlap: int | None = Field(None, ge=0)
    parent_child: bool | None = None
    vector_top_k: int | None = Field(None, ge=1, le=500)
    fts_top_k: int | None = Field(None, ge=1, le=500)
    exact_top_k: int | None = Field(None, ge=0, le=100)
    vector_weight: float | None = Field(None, ge=0)
    fts_weight: float | None = Field(None, ge=0)
    exact_weight: float | None = Field(None, ge=0)
    rrf_k: int | None = Field(None, ge=1, le=1000)
    rerank_enabled: bool | None = None
    rerank_top_n: int | None = Field(None, ge=1, le=200)
    final_top_k: int | None = Field(None, ge=1, le=50)
    max_context_tokens: int | None = Field(None, ge=256, le=128000)
    min_relevance: float | None = Field(None, ge=0)
    hnsw_ef_search: int | None = Field(None, ge=10, le=1000)
    citation_required: bool | None = None
    query_rewriting: bool | None = None
    guardrails: dict[str, Any] | None = None
    reason: str | None = None


class TenantSettingsUpdate(ApiModel):
    require_mfa_for_admin: bool | None = None
    session_idle_minutes: int | None = Field(None, ge=5, le=1440)
    session_absolute_hours: int | None = Field(None, ge=1, le=168)
    conversation_retention_days: int | None = Field(None, gt=0)
    store_query_text: bool | None = None
    default_language: str | None = None


class FeedbackUpdate(ApiModel):
    status: Literal["new", "triaged", "in_progress", "resolved", "rejected"] | None = None
    assigned_to: uuid.UUID | None = None
    resolution: str | None = None
    golden_candidate: bool | None = None


class DatasetCreate(ApiModel):
    name: str = Field(min_length=2, max_length=200)
    purpose: Literal["retrieval", "generation", "safety", "access", "regression"] = "retrieval"
    description: str | None = None


class QuestionIn(ApiModel):
    question: str = Field(min_length=3, max_length=2000)
    expected_answer: str | None = None
    expected_document_ids: list[uuid.UUID] = []
    expected_chunk_ids: list[uuid.UUID] = []
    answerable: bool = True
    category: str | None = None
    line_of_business: str | None = None
    jurisdiction: str | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    is_critical: bool = False


class EvaluationRunRequest(ApiModel):
    mode: Literal["retrieval", "end_to_end"] = "retrieval"
    k: int = Field(10, ge=1, le=50)
    gates: dict[str, float] | None = None
