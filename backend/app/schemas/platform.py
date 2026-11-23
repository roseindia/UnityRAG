"""Platform administration schemas (extension 6, 9)."""
from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import ApiModel


class TenantCreate(ApiModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,39}$")
    name: str = Field(min_length=2, max_length=200)
    legal_entity: str | None = None
    plan_code: str = "trial"
    home_region: str = "default"
    branding: dict[str, Any] | None = None
    admin_email: str | None = Field(None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    admin_name: str | None = None
    admin_password: str | None = Field(None, min_length=12)


class TenantUpdate(ApiModel):
    name: str | None = None
    legal_entity: str | None = None
    home_region: str | None = None
    branding: dict[str, Any] | None = None


class LifecycleAction(ApiModel):
    reason: str = Field(min_length=10, max_length=1000)
    confirm: bool = Field(description="must be true: explicit confirmation of a sensitive operation")


class QuotaUpdate(ApiModel):
    max_users: int | None = Field(None, ge=0)
    max_documents: int | None = Field(None, ge=0)
    max_storage_bytes: int | None = Field(None, ge=0)
    max_document_size_bytes: int | None = Field(None, gt=0)
    monthly_ai_tokens: int | None = Field(None, ge=0)
    monthly_ai_requests: int | None = Field(None, ge=0)
    max_concurrent_chats: int | None = Field(None, ge=0)
    max_ingestion_jobs: int | None = Field(None, ge=0)
    max_collections: int | None = Field(None, ge=0)
    reason: str | None = None


class FeatureFlag(ApiModel):
    flag: str = Field(pattern=r"^[a-z0-9_.]{2,60}$")
    enabled: bool


class PlanChange(ApiModel):
    plan_code: str
    apply_quotas: bool = True


class PlanUpsert(ApiModel):
    code: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    name: str
    description: str | None = None
    max_users: int = Field(ge=0)
    max_documents: int = Field(ge=0)
    max_storage_bytes: int = Field(ge=0)
    max_document_size_bytes: int = Field(gt=0)
    monthly_ai_tokens: int = Field(ge=0)
    monthly_ai_requests: int = Field(ge=0)
    max_concurrent_chats: int = Field(ge=0)
    max_ingestion_jobs: int = Field(ge=0)
    max_collections: int = Field(ge=0)
    features: dict[str, Any] = {}
    monthly_price: float = 0
    is_active: bool = True


class TenantAdminCreate(ApiModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str
    password: str | None = Field(None, min_length=12)


class ProviderUpsert(ApiModel):
    code: str = Field(pattern=r"^[a-z0-9_-]{2,40}$")
    name: str
    provider_type: Literal["openai", "azure_openai", "ollama", "huggingface", "openai_compatible", "local"]
    base_url: str | None = None
    api_version: str | None = None
    api_key: str | None = Field(None, description="write-only; stored encrypted, returned masked")
    region: str = "default"
    is_enabled: bool = True
    allow_tenant_override: bool = False
    rate_limit_per_min: int | None = None


class ProviderUpdate(ApiModel):
    name: str | None = None
    base_url: str | None = None
    api_version: str | None = None
    api_key: str | None = None
    region: str | None = None
    is_enabled: bool | None = None
    allow_tenant_override: bool | None = None
    rate_limit_per_min: int | None = None


class ModelCreate(ApiModel):
    provider_id: uuid.UUID
    model_name: str
    model_version: str = "latest"
    purpose: Literal["chat", "embedding", "rerank", "rewrite", "judge"]
    dimensions: int | None = None
    context_window: int | None = None
    input_cost_per_1k: float = 0
    output_cost_per_1k: float = 0
    risk_class: Literal["low", "medium", "high"] = "medium"


class ModelUpdate(ApiModel):
    status: Literal["proposed", "approved", "active", "deprecated", "retired"] | None = None
    input_cost_per_1k: float | None = None
    output_cost_per_1k: float | None = None
    risk_class: Literal["low", "medium", "high"] | None = None
    context_window: int | None = None
    is_default: bool | None = None


class PlatformUserSet(ApiModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str | None = None
    role: Literal["platform_super_admin", "platform_admin", "platform_operator", "platform_security", "platform_support"]
    password: str | None = Field(None, min_length=12)
    status: Literal["active", "disabled"] = "active"


class BreakGlassRequest(ApiModel):
    tenant_id: uuid.UUID
    reason: str = Field(min_length=15, max_length=2000)
    minutes: int = Field(60, ge=5, le=480)
    scope: list[Literal["documents:read", "conversations:read"]] = ["documents:read"]
    confirm: bool


class PlatformSetting(ApiModel):
    value: Any
