"""Resolution of AI provider endpoints and credentials (FR-169, FR-134, extension 6.5).

Provider records live in platform.ai_providers (keys encrypted, masked on read).
A tenant may use its own credentials only when the platform marks the provider
`allow_tenant_override` AND the tenant has the `tenant_ai_providers` feature.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.security.crypto import decrypt_secret


@dataclass(frozen=True)
class ProviderEndpoint:
    code: str
    provider_type: str          # local | openai | azure_openai | ollama | huggingface | openai_compatible
    base_url: str | None
    api_key: str | None
    api_version: str | None
    region: str


LOCAL = ProviderEndpoint("local", "local", None, None, None, "default")


def resolve_provider(db: Session, code: str) -> ProviderEndpoint:
    if code == "local":
        return LOCAL
    row = db.execute(text("""SELECT code, provider_type, base_url, api_key_enc, api_version, region, is_enabled,
                                    allow_tenant_override FROM platform.ai_providers WHERE code = :c"""),
                     {"c": code}).mappings().first()
    if row is None or not row["is_enabled"]:
        raise ValidationFailed(f"AI provider '{code}' is not available")
    base_url, key = row["base_url"], decrypt_secret(row["api_key_enc"])
    if row["allow_tenant_override"]:
        enabled = db.execute(text("""SELECT enabled FROM platform.tenant_feature_flags
                                      WHERE tenant_id = app.current_tenant_id() AND flag = 'tenant_ai_providers'""")).scalar()
        if enabled:
            cred = db.execute(text("SELECT base_url, api_key_enc FROM ai.tenant_provider_credentials WHERE provider_code = :c"),
                              {"c": code}).mappings().first()
            if cred:
                base_url = cred["base_url"] or base_url
                key = decrypt_secret(cred["api_key_enc"]) or key
    return ProviderEndpoint(row["code"], row["provider_type"], base_url, key, row["api_version"], row["region"])


def model_pricing(db: Session, provider_code: str, model: str) -> tuple[float, float]:
    row = db.execute(text("""SELECT m.input_cost_per_1k, m.output_cost_per_1k FROM platform.model_catalogue m
                              JOIN platform.ai_providers p ON p.provider_id = m.provider_id
                             WHERE p.code = :p AND m.model_name = :m ORDER BY m.created_at DESC LIMIT 1"""),
                     {"p": provider_code, "m": model}).first()
    return (float(row[0]), float(row[1])) if row else (0.0, 0.0)


def assert_model_allowed(db: Session, provider_code: str, model: str, purpose: str) -> dict:
    """Models may only be selected from the approved catalogue (FR-169)."""
    row = db.execute(text("""SELECT m.model_name, m.dimensions, m.status FROM platform.model_catalogue m
                              JOIN platform.ai_providers p ON p.provider_id = m.provider_id
                             WHERE p.code = :p AND m.model_name = :m AND m.purpose = :u"""),
                     {"p": provider_code, "m": model, "u": purpose}).mappings().first()
    if row is None or row["status"] not in ("approved", "active"):
        raise ValidationFailed(f"Model '{model}' ({purpose}) is not an approved catalogue model for provider '{provider_code}'")
    return dict(row)
