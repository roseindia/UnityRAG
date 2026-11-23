"""Database engines and the transaction-scoped security context (extension 2.1).

Every unit of work follows the mandated sequence:
    authenticate -> resolve membership -> validate tenant -> BEGIN ->
    set_config(..., is_local => true)  (== SET LOCAL) -> work -> COMMIT/ROLLBACK
Settings applied with is_local=true vanish at COMMIT/ROLLBACK, so a pooled
connection can never carry one request's tenant into the next request.  As a
second safety net, every connection checked into the pool is reset.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Literal

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_log = logging.getLogger("app.database")

DbRole = Literal["app", "worker", "readonly"]
AccessMode = Literal["none", "user", "tenant_admin", "auditor", "worker", "scheduler", "platform",
                     "platform_provisioning", "break_glass"]

_CONTEXT_KEYS = ("app.current_tenant_id", "app.current_user_id", "app.current_account_id",
                 "app.current_platform_role", "app.current_access_mode", "app.current_principals",
                 "app.current_lobs", "app.current_jurisdictions", "app.current_max_class")


@dataclass(frozen=True)
class SecurityContext:
    """The server-derived identity that RLS policies evaluate."""

    access_mode: AccessMode
    tenant_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    platform_role: str | None = None
    principals: tuple[uuid.UUID, ...] = field(default_factory=tuple)
    lobs: tuple[str, ...] = field(default_factory=tuple)
    jurisdictions: tuple[str, ...] = field(default_factory=tuple)
    max_class: int = -1

    def with_mode(self, mode: AccessMode) -> SecurityContext:
        return replace(self, access_mode=mode)

    def settings(self) -> dict[str, str]:
        return {
            "app.current_tenant_id": str(self.tenant_id) if self.tenant_id else "",
            "app.current_user_id": str(self.user_id) if self.user_id else "",
            "app.current_account_id": str(self.account_id) if self.account_id else "",
            "app.current_platform_role": self.platform_role or "",
            "app.current_access_mode": self.access_mode,
            "app.current_principals": ",".join(str(p) for p in self.principals),
            "app.current_lobs": ",".join(self.lobs),
            "app.current_jurisdictions": ",".join(self.jurisdictions),
            "app.current_max_class": str(self.max_class),
        }

    @staticmethod
    def worker(tenant_id: uuid.UUID, initiated_by: uuid.UUID | None = None) -> SecurityContext:
        return SecurityContext(access_mode="worker", tenant_id=tenant_id, user_id=initiated_by)

    @staticmethod
    def anonymous() -> SecurityContext:
        return SecurityContext(access_mode="none")


def apply_security_context(session: Session, ctx: SecurityContext) -> None:
    """Set the context transaction-locally.  Values are bound parameters -
    never string-interpolated into SQL."""
    params = ctx.settings()
    clauses = ", ".join(f"set_config('{k}', :p{i}, true)" for i, k in enumerate(_CONTEXT_KEYS))
    session.execute(text(f"SELECT {clauses}"), {f"p{i}": params[k] for i, k in enumerate(_CONTEXT_KEYS)})


def _make_engine(role: DbRole) -> Engine:
    s = get_settings()
    engine = create_engine(
        s.dsn(role), pool_size=s.db_pool_size, max_overflow=s.db_max_overflow, pool_pre_ping=True,
        pool_reset_on_return="rollback", future=True,
        connect_args={"application_name": f"unityrag-{role}", "options": "-c timezone=UTC"},
    )

    @event.listens_for(engine, "checkin")
    def _reset_on_checkin(dbapi_conn, _record):  # pragma: no cover - exercised via pool tests
        # Defence in depth: clear any session-level custom setting that a buggy
        # code path might have created with a non-local SET.
        try:
            cur = dbapi_conn.cursor()
            cur.execute("RESET ALL")
            cur.close()
            dbapi_conn.commit()
        except Exception as exc:  # connection is broken - the pool will discard it
            _log.debug("connection reset on check-in failed: %s", type(exc).__name__)

    return engine


@lru_cache(maxsize=3)
def get_engine(role: DbRole = "app") -> Engine:
    return _make_engine(role)


@lru_cache(maxsize=3)
def _factory(role: DbRole) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(role), autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def scoped_session(ctx: SecurityContext, role: DbRole = "app") -> Iterator[Session]:
    """One transaction with the given security context.  Commits on success,
    rolls back on any exception (which is re-raised, never swallowed)."""
    session = _factory(role)()
    try:
        with session.begin():
            apply_security_context(session, ctx)
            yield session
    finally:
        session.close()


_ROLE_SAFETY_SQL = text("""
SELECT r.rolname, r.rolsuper, r.rolbypassrls,
       EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname IN ('platform', 'iam', 'content', 'ingest', 'rag', 'ai', 'eval', 'audit', 'ops')
                  AND c.relkind = 'r' AND pg_has_role(r.oid, c.relowner, 'USAGE')) AS owns_tables
  FROM pg_roles r WHERE r.rolname = current_user""")


def verify_role_safety(role: DbRole = "app") -> list[str]:
    """Return the reasons why the configured service credential would bypass RLS
    (superuser, BYPASSRLS, or owner / member of the owner of application tables).
    Called at API and worker start-up; production refuses to start when non-empty."""
    with get_engine(role).connect() as conn:
        name, is_super, bypass, owns = conn.execute(_ROLE_SAFETY_SQL).one()
    problems = []
    if is_super:
        problems.append(f"{name} is a superuser")
    if bypass:
        problems.append(f"{name} has BYPASSRLS")
    if owns:
        problems.append(f"{name} owns (or is a member of the owner of) application tables")
    return problems


def enforce_role_safety(roles: tuple[DbRole, ...]) -> None:
    import logging

    log = logging.getLogger("app.database")
    problems = [p for r in roles for p in verify_role_safety(r)]
    if not problems:
        return
    if get_settings().environment == "production":
        raise RuntimeError("Refusing to start: database credentials would bypass row-level security: " + "; ".join(problems))
    log.warning("database credentials would bypass row-level security: %s", "; ".join(problems))


def dispose_engines() -> None:
    for role in ("app", "worker", "readonly"):
        if get_engine.cache_info().currsize:
            try:
                get_engine(role).dispose()  # type: ignore[arg-type]
            except Exception as exc:
                _log.warning("engine dispose failed for %s: %s", role, type(exc).__name__)
    get_engine.cache_clear()
    _factory.cache_clear()
