"""Request identity: who the caller is, which tenant they act in and what they may do.

Built server-side on every request (no cross-request caching, so role, group,
membership and tenant-status changes take effect on the next request -
FR-009, FR-010, NFR-109).
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.database.session import AccessMode, SecurityContext


@dataclass(frozen=True)
class RequestContext:
    account_id: uuid.UUID
    session_id: uuid.UUID
    email: str
    display_name: str
    tenant_id: uuid.UUID | None
    tenant_status: str | None
    user_id: uuid.UUID | None
    user_type: str | None = None
    department_id: uuid.UUID | None = None
    business_unit: str | None = None
    platform_role: str | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    platform_permissions: frozenset[str] = field(default_factory=frozenset)
    group_ids: tuple[uuid.UUID, ...] = ()
    role_ids: tuple[uuid.UUID, ...] = ()
    team_ids: tuple[uuid.UUID, ...] = ()
    role_codes: tuple[str, ...] = ()
    lines_of_business: tuple[str, ...] = ()
    jurisdictions: tuple[str, ...] = ()
    clearance_rank: int = -1
    mfa_verified_at: datetime | None = None
    mfa_in_token: bool = False
    ip: str | None = None

    # -- derived -------------------------------------------------------------------
    @property
    def principals(self) -> tuple[uuid.UUID, ...]:
        """User, tenant-wide 'everyone' principal, department, groups, roles, teams."""
        out: list[uuid.UUID] = []
        if self.user_id:
            out.append(self.user_id)
        if self.tenant_id:
            out.append(self.tenant_id)
        if self.department_id:
            out.append(self.department_id)
        out.extend(self.group_ids)
        out.extend(self.role_ids)
        out.extend(self.team_ids)
        return tuple(dict.fromkeys(out))

    @property
    def is_tenant_admin(self) -> bool:
        return any(p.startswith("admin.") for p in self.permissions)

    @property
    def is_department_admin(self) -> bool:
        return "department.analytics.view" in self.permissions and "admin.analytics.view" not in self.permissions

    def has(self, *permissions: str) -> bool:
        return all(p in self.permissions for p in permissions)

    def has_platform(self, *permissions: str) -> bool:
        return all(p in self.platform_permissions for p in permissions)

    def security(self, mode: AccessMode = "user") -> SecurityContext:
        return SecurityContext(
            access_mode=mode, tenant_id=self.tenant_id, user_id=self.user_id, account_id=self.account_id,
            platform_role=self.platform_role if mode in ("platform", "platform_provisioning", "break_glass") else None,
            principals=self.principals, lobs=self.lines_of_business, jurisdictions=self.jurisdictions,
            max_class=self.clearance_rank)

    def platform_security(self, tenant_id: uuid.UUID | None = None, mode: AccessMode = "platform") -> SecurityContext:
        return SecurityContext(access_mode=mode, tenant_id=tenant_id, account_id=self.account_id,
                               platform_role=self.platform_role)

    def permission_fingerprint(self) -> str:
        """Stable hash of everything that influences what the caller may retrieve.
        Used in cache keys and recorded with each query (FR-108, FR-226)."""
        parts = [str(self.tenant_id), str(self.user_id), ",".join(sorted(map(str, self.principals))),
                 ",".join(sorted(self.lines_of_business)), ",".join(sorted(self.jurisdictions)),
                 str(self.clearance_rank)]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]
