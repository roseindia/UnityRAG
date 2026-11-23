"""Request-scoped context variables (correlation IDs - FR-199, NFR-074)."""
from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")
_tenant_id: ContextVar[str] = ContextVar("log_tenant_id", default="-")
_SAFE = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")


def new_correlation_id(candidate: str | None = None) -> str:
    """Accept a caller-supplied correlation id only if it is well-formed."""
    cid = candidate if candidate and _SAFE.match(candidate) else uuid.uuid4().hex
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    return _correlation_id.get()


def set_correlation_id(cid: str) -> None:
    _correlation_id.set(cid)


def set_log_tenant(tenant_id: str | None) -> None:
    _tenant_id.set(tenant_id or "-")


def get_log_tenant() -> str:
    return _tenant_id.get()
