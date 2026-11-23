"""FastAPI dependencies: authentication, tenant context, RBAC and platform RBAC.

Navigation visibility in the UI is a convenience only; every endpoint enforces
its permission here, server side (NFR-033, extension 8).
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.context import set_log_tenant
from app.core.errors import AuthenticationError, PermissionDenied
from app.middleware.rate_limit import enforce_rate_limit
from app.security.context import RequestContext
from app.services import auth_service
from app.services.audit import audit_out_of_band, platform_audit_out_of_band

_bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str | None:
    """Client IP (first X-Forwarded-For hop when behind the trusted proxy); invalid values are dropped."""
    import ipaddress

    fwd = request.headers.get("x-forwarded-for")
    candidate = fwd.split(",")[0].strip()[:64] if fwd else (request.client.host if request.client else None)
    try:
        return str(ipaddress.ip_address(candidate)) if candidate else None
    except ValueError:
        return None


def get_context(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> RequestContext:
    if creds is None or creds.scheme.lower() != "bearer":
        raise AuthenticationError("Authentication required", code="authentication_required")
    ctx = auth_service.resolve_request_context(creds.credentials, ip=client_ip(request))
    set_log_tenant(str(ctx.tenant_id) if ctx.tenant_id else None)
    request.state.ctx = ctx
    enforce_rate_limit(f"{ctx.tenant_id}:{ctx.account_id}", kind="api")
    return ctx


def get_tenant_context(ctx: RequestContext = Depends(get_context)) -> RequestContext:
    if ctx.tenant_id is None or ctx.user_id is None:
        raise PermissionDenied("This operation requires an active tenant context", code="tenant_context_required")
    return ctx


def require(*permissions: str) -> Callable[..., RequestContext]:
    """Tenant RBAC: the caller must hold every listed permission in the active tenant."""

    def _dep(ctx: RequestContext = Depends(get_tenant_context)) -> RequestContext:
        missing = [p for p in permissions if p not in ctx.permissions]
        if missing:
            audit_out_of_band(ctx.security("user"), tenant_id=ctx.tenant_id, category="authorization",
                              event_type="permission_denied", outcome="denied", actor_user_id=ctx.user_id,
                              actor_account_id=ctx.account_id, detail={"required": list(permissions)})
            raise PermissionDenied("You do not have permission to perform this action")
        return ctx

    return _dep


def require_any(*permissions: str) -> Callable[..., RequestContext]:
    def _dep(ctx: RequestContext = Depends(get_tenant_context)) -> RequestContext:
        if not any(p in ctx.permissions for p in permissions):
            audit_out_of_band(ctx.security("user"), tenant_id=ctx.tenant_id, category="authorization",
                              event_type="permission_denied", outcome="denied", actor_user_id=ctx.user_id,
                              actor_account_id=ctx.account_id, detail={"required_any": list(permissions)})
            raise PermissionDenied("You do not have permission to perform this action")
        return ctx

    return _dep


def require_platform(*permissions: str) -> Callable[..., RequestContext]:
    """Platform RBAC.  Tenant administrators never pass this check."""

    def _dep(ctx: RequestContext = Depends(get_context)) -> RequestContext:
        if ctx.platform_role is None or any(p not in ctx.platform_permissions for p in permissions):
            platform_audit_out_of_band(category="authorization", action="platform_permission_denied",
                                       outcome="denied", severity="medium", actor_account_id=ctx.account_id,
                                       target_tenant_id=ctx.tenant_id, detail={"required": list(permissions)})
            raise PermissionDenied("Platform permission required")
        return ctx

    return _dep
