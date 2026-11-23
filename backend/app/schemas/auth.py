from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel


class LoginRequest(ApiModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)
    tenant_id: uuid.UUID | None = Field(None, description="Optional tenant to activate; validated against memberships")
    mfa_code: str | None = Field(None, min_length=6, max_length=8)


class OidcExchangeRequest(ApiModel):
    id_token: str = Field(min_length=20)
    tenant_id: uuid.UUID | None = None


class RefreshRequest(ApiModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class SelectTenantRequest(ApiModel):
    tenant_id: uuid.UUID


class Membership(ApiModel):
    tenant_id: uuid.UUID
    tenant_code: str
    tenant_name: str
    tenant_status: str
    membership_status: str
    is_default: bool


class TokenResponse(ApiModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_at: datetime
    session_id: uuid.UUID
    tenant_id: uuid.UUID | None
    platform_role: str | None
    memberships: list[Membership]


class MfaCode(ApiModel):
    code: str = Field(min_length=6, max_length=8)


class PasswordChange(ApiModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)


class PasswordResetConsume(ApiModel):
    token: str = Field(min_length=20)
    new_password: str = Field(min_length=12, max_length=256)


class Profile(ApiModel):
    account_id: uuid.UUID
    email: str
    display_name: str
    tenant_id: uuid.UUID | None
    user_id: uuid.UUID | None
    user_type: str | None
    department_id: uuid.UUID | None
    platform_role: str | None
    roles: list[str]
    permissions: list[str]
    platform_permissions: list[str]
    lines_of_business: list[str]
    jurisdictions: list[str]
    clearance_rank: int
    mfa_verified: bool
    console: str = Field(description="platform_admin | tenant_admin | department_admin | user")


