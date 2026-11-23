"""Helpers shared by the routers: transaction scopes and administrative guards."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.session import AccessMode, SecurityContext, scoped_session
from app.dependencies.auth import get_tenant_context, require
from app.security.context import RequestContext
from app.services.auth_service import require_step_up


@contextmanager
def tx(ctx: RequestContext, mode: AccessMode = "user") -> Iterator[Session]:
    """One database transaction under the caller's validated tenant context."""
    with scoped_session(ctx.security(mode)) as db:
        yield db


@contextmanager
def platform_tx(ctx: RequestContext) -> Iterator[Session]:
    with scoped_session(ctx.platform_security()) as db:
        yield db


@contextmanager
def worker_tx(ctx: RequestContext) -> Iterator[Session]:
    """Aggregate-only analytics over owner-scoped tables for the caller's OWN
    tenant (ADR-012).  Never used to return row-level content."""
    with scoped_session(SecurityContext.worker(ctx.tenant_id, ctx.user_id), role="worker") as db:  # type: ignore[arg-type]
        yield db


def admin(*permissions: str, write: bool = True) -> Callable[..., RequestContext]:
    """Tenant-admin guard: RBAC permission + (when the tenant requires it) recent MFA step-up."""
    base = require(*permissions)

    def _dep(ctx: RequestContext = Depends(base)) -> RequestContext:
        if write:
            with scoped_session(ctx.security("user")) as db:
                need = db.execute(text("SELECT require_mfa_for_admin FROM platform.tenant_settings WHERE tenant_id = :t"),
                                  {"t": ctx.tenant_id}).scalar()
            if need:
                require_step_up(ctx)
        return ctx

    return _dep


def tenant_user(ctx: RequestContext = Depends(get_tenant_context)) -> RequestContext:
    return ctx
