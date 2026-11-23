"""Authentication endpoints (FR-002..FR-006, FR-012, FR-181; extension 1.2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from app.database.session import scoped_session
from app.dependencies.auth import client_ip, get_context
from app.schemas.auth import (
    LoginRequest,
    MfaCode,
    OidcExchangeRequest,
    PasswordChange,
    PasswordResetConsume,
    Profile,
    RefreshRequest,
    SelectTenantRequest,
    TokenResponse,
)
from app.schemas.common import ERROR_RESPONSES, Message
from app.security.context import RequestContext
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"], responses=ERROR_RESPONSES)


def _tokens(b: auth_service.TokenBundle) -> TokenResponse:
    return TokenResponse(access_token=b.access_token, refresh_token=b.refresh_token, expires_at=b.expires_at,
                         session_id=b.session_id, tenant_id=b.tenant_id, platform_role=b.platform_role,
                         memberships=b.memberships)


@router.post("/login", response_model=TokenResponse, summary="Password login (local accounts)")
def login(body: LoginRequest, request: Request) -> TokenResponse:
    return _tokens(auth_service.login(body.email, body.password, tenant_id=body.tenant_id, mfa_code=body.mfa_code,
                                      ip=client_ip(request), user_agent=request.headers.get("user-agent")))


@router.post("/oidc/exchange", response_model=TokenResponse, summary="Exchange a corporate IdP (OIDC) token for a session")
def oidc_exchange(body: OidcExchangeRequest, request: Request) -> TokenResponse:
    return _tokens(auth_service.exchange_oidc(body.id_token, tenant_id=body.tenant_id, ip=client_ip(request),
                                              user_agent=request.headers.get("user-agent")))


@router.post("/refresh", response_model=TokenResponse, summary="Rotate the refresh token and issue a new access token")
def refresh(body: RefreshRequest) -> TokenResponse:
    return _tokens(auth_service.refresh(body.refresh_token))


@router.post("/logout", response_model=Message)
def logout(ctx: RequestContext = Depends(get_context)) -> Message:
    auth_service.logout(ctx)
    return Message(message="Signed out")


@router.get("/me", response_model=Profile, summary="Current identity, active tenant, roles and effective permissions")
def me(ctx: RequestContext = Depends(get_context)) -> Profile:
    console = ("platform_admin" if ctx.platform_role and ctx.tenant_id is None else
               "tenant_admin" if ctx.is_tenant_admin and not ctx.is_department_admin else
               "department_admin" if ctx.is_department_admin else "user")
    return Profile(account_id=ctx.account_id, email=ctx.email, display_name=ctx.display_name, tenant_id=ctx.tenant_id,
                   user_id=ctx.user_id, user_type=ctx.user_type, department_id=ctx.department_id,
                   platform_role=ctx.platform_role, roles=list(ctx.role_codes), permissions=sorted(ctx.permissions),
                   platform_permissions=sorted(ctx.platform_permissions), lines_of_business=list(ctx.lines_of_business),
                   jurisdictions=list(ctx.jurisdictions), clearance_rank=ctx.clearance_rank,
                   mfa_verified=ctx.mfa_verified_at is not None, console=console)


@router.get("/tenants", summary="Tenants the caller is a member of")
def my_tenants(ctx: RequestContext = Depends(get_context)) -> list[dict]:
    return auth_service._public_memberships(auth_service.list_memberships(ctx.account_id))


@router.post("/select-tenant", response_model=TokenResponse,
             summary="Switch the active tenant (validated server-side against active memberships)")
def select_tenant(body: SelectTenantRequest, request: Request, ctx: RequestContext = Depends(get_context)) -> TokenResponse:
    return _tokens(auth_service.switch_tenant(ctx, body.tenant_id, client_ip(request), request.headers.get("user-agent")))


@router.get("/sessions", summary="The caller's own sessions")
def my_sessions(ctx: RequestContext = Depends(get_context)) -> list[dict]:
    with scoped_session(ctx.security("user")) as db:
        rows = db.execute(text("""SELECT session_id, tenant_id, created_at, last_seen_at, absolute_expires_at, auth_method,
                                         host(ip) AS ip, revoked_at, revoked_reason FROM iam.sessions
                                   WHERE account_id = :a ORDER BY created_at DESC LIMIT 50"""),
                          {"a": ctx.account_id}).mappings().all()
        return [dict(r) | {"current": r["session_id"] == ctx.session_id} for r in rows]


@router.post("/mfa/enroll", summary="Start TOTP enrolment (returns secret + otpauth URI once)")
def mfa_enroll(ctx: RequestContext = Depends(get_context)) -> dict:
    return auth_service.mfa_enroll(ctx)


@router.post("/mfa/verify", response_model=Message, summary="Confirm enrolment or perform step-up verification")
def mfa_verify(body: MfaCode, ctx: RequestContext = Depends(get_context)) -> Message:
    auth_service.mfa_verify(ctx, body.code, enable=True)
    return Message(message="Multi-factor verification successful")


@router.post("/password/change", response_model=Message)
def change_password(body: PasswordChange, ctx: RequestContext = Depends(get_context)) -> Message:
    auth_service.change_password(ctx, body.current_password, body.new_password)
    return Message(message="Password changed")


@router.post("/password/reset", response_model=Message, summary="Complete a password reset with a single-use token")
def reset_password(body: PasswordResetConsume) -> Message:
    auth_service.consume_password_reset(body.token, body.new_password)
    return Message(message="Password reset; all sessions were revoked")
