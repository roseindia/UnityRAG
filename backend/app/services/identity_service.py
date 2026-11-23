"""Tenant identity administration: users, memberships, roles, departments, teams,
groups (FR-007, FR-009, FR-163..FR-165, FR-190, FR-191, extension 7.2-7.4).

All functions take a Session already bound to a validated tenant context in
mode `tenant_admin` (or `platform_provisioning` for platform-managed tenant
administrators).  The tenant id used for writes is always the context's tenant,
never a client-supplied value.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.database.session import SecurityContext
from app.security.passwords import hash_password, password_policy_errors
from app.services import quota_service
from app.services.audit import tenant_audit
from app.services.roles_catalog import SYSTEM_ROLE_CODES, SYSTEM_ROLES


def _audit(db: Session, sec: SecurityContext, event: str, rtype: str, rid: Any, detail: dict | None = None,
           category: str = "administration") -> None:
    assert sec.tenant_id
    tenant_audit(db, tenant_id=sec.tenant_id, category=category, event_type=event,
                 actor_type="platform_admin" if sec.access_mode == "platform_provisioning" else "user",
                 actor_user_id=sec.user_id, actor_account_id=sec.account_id, resource_type=rtype, resource_id=rid,
                 detail=detail)


# --- system roles ---------------------------------------------------------------------
def install_system_roles(db: Session, tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for role in SYSTEM_ROLES:
        rid = db.execute(text("SELECT role_id FROM iam.roles WHERE code = :c"), {"c": role["code"]}).scalar()
        if rid is None:
            rid = uuid.uuid4()
            db.execute(text("""INSERT INTO iam.roles (tenant_id, role_id, code, name, is_system, is_admin, conflicts_with)
                               VALUES (:t, :r, :c, :n, true, :a, :cw)"""),
                       {"t": tenant_id, "r": rid, "c": role["code"], "n": role["name"], "a": role["is_admin"],
                        "cw": role["conflicts_with"]})
        for perm in role["permissions"]:
            db.execute(text("""INSERT INTO iam.role_permissions (tenant_id, role_id, permission_code)
                               VALUES (:t, :r, :p) ON CONFLICT DO NOTHING"""), {"t": tenant_id, "r": rid, "p": perm})
        ids[role["code"]] = rid
    return ids


# --- users -------------------------------------------------------------------------------
def create_user(db: Session, sec: SecurityContext, *, email: str, display_name: str, password: str | None = None,
                auth_provider: str = "local", external_subject: str | None = None, user_type: str = "employee",
                department_id: uuid.UUID | None = None, business_unit: str | None = None,
                country: str | None = None, lines_of_business: list[str] | None = None,
                jurisdictions: list[str] | None = None, clearance_rank: int = 1,
                role_codes: list[str] | None = None, group_ids: list[uuid.UUID] | None = None) -> dict[str, Any]:
    tenant_id = sec.tenant_id
    assert tenant_id
    email = email.strip().lower()
    if db.execute(text("SELECT 1 FROM iam.users WHERE email = :e"), {"e": email}).first():
        raise Conflict("A user with this e-mail already exists in the tenant")
    quota_service.consume(db, sec, "users")
    account_id = db.execute(text("SELECT app.account_id_for_email(:e)"), {"e": email}).scalar()
    if account_id is None:
        if auth_provider == "local":
            if not password:
                raise ValidationFailed("A password is required for local accounts")
            errs = password_policy_errors(password, get_settings().password_min_length)
            if errs:
                raise ValidationFailed("Password does not meet policy",
                                       details=[{"field": "password", "message": e} for e in errs])
        account_id = uuid.uuid4()
        db.execute(text("""INSERT INTO iam.user_accounts (account_id, email, display_name, password_hash, auth_provider,
                                                          external_subject)
                           VALUES (:a, :e, :n, :h, :p, :s)"""),
                   {"a": account_id, "e": email, "n": display_name,
                    "h": hash_password(password) if (password and auth_provider == "local") else None,
                    "p": auth_provider, "s": external_subject})
    user_id = uuid.uuid4()
    db.execute(text("""INSERT INTO iam.users (tenant_id, user_id, account_id, email, display_name, user_type, department_id,
                                              business_unit, country, lines_of_business, jurisdictions, clearance_rank,
                                              created_by)
                       VALUES (:t, :u, :a, :e, :n, :ut, :d, :bu, :c, :lob, :j, :cr, :by)"""),
               {"t": tenant_id, "u": user_id, "a": account_id, "e": email, "n": display_name, "ut": user_type,
                "d": department_id, "bu": business_unit, "c": country, "lob": lines_of_business or [],
                "j": jurisdictions or [], "cr": clearance_rank, "by": sec.user_id})
    first = not db.execute(text("SELECT 1 FROM iam.tenant_memberships WHERE account_id = :a AND tenant_id <> :t"),
                           {"a": account_id, "t": tenant_id}).first()
    db.execute(text("""INSERT INTO iam.tenant_memberships (tenant_id, account_id, user_id, is_default, created_by)
                       VALUES (:t, :a, :u, :d, :by)"""),
               {"t": tenant_id, "a": account_id, "u": user_id, "d": first, "by": sec.user_id})
    for code in role_codes or ["member"]:
        assign_role(db, sec, user_id, role_code=code, audit=False)
    for gid in group_ids or []:
        add_group_member(db, sec, gid, user_id, audit=False)
    _audit(db, sec, "user_created", "user", user_id, {"roles": role_codes or ["member"], "user_type": user_type})
    return get_user(db, user_id)


def get_user(db: Session, user_id: uuid.UUID) -> dict[str, Any]:
    row = db.execute(text("""
        SELECT u.user_id, u.account_id, u.email::text AS email, u.display_name, u.user_type, u.department_id,
               u.business_unit, u.country, u.lines_of_business, u.jurisdictions, u.clearance_rank, u.status,
               u.created_at, u.last_active_at, m.status AS membership_status,
               ARRAY(SELECT r.code FROM iam.user_roles ur JOIN iam.roles r ON r.role_id = ur.role_id
                      WHERE ur.user_id = u.user_id AND (ur.valid_to IS NULL OR ur.valid_to > now())) AS roles,
               ARRAY(SELECT g.group_id FROM iam.user_group_members g WHERE g.user_id = u.user_id) AS group_ids,
               ARRAY(SELECT t.team_id FROM iam.team_members t WHERE t.user_id = u.user_id) AS team_ids
          FROM iam.users u LEFT JOIN iam.tenant_memberships m ON m.user_id = u.user_id
         WHERE u.user_id = :u"""), {"u": user_id}).mappings().first()
    if row is None:
        raise NotFound("User not found")
    return dict(row)


_USER_FIELDS = {"display_name", "user_type", "department_id", "business_unit", "country", "lines_of_business",
                "jurisdictions", "clearance_rank"}


def update_user(db: Session, sec: SecurityContext, user_id: uuid.UUID, changes: dict[str, Any]) -> dict[str, Any]:
    before = get_user(db, user_id)
    fields = {k: v for k, v in changes.items() if k in _USER_FIELDS and v is not None}
    if fields:
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        db.execute(text(f"UPDATE iam.users SET {sets} WHERE user_id = :uid"), {**fields, "uid": user_id})
    _audit(db, sec, "user_updated", "user", user_id,
           {"changed": sorted(fields), "before": {k: before.get(k) for k in fields}})
    return get_user(db, user_id)


def set_user_status(db: Session, sec: SecurityContext, user_id: uuid.UUID, active: bool) -> dict[str, Any]:
    user = get_user(db, user_id)
    if user_id == sec.user_id and not active:
        raise ValidationFailed("Administrators cannot deactivate themselves")
    status = "active" if active else "inactive"
    db.execute(text("UPDATE iam.users SET status = :s WHERE user_id = :u"), {"s": status, "u": user_id})
    db.execute(text("UPDATE iam.tenant_memberships SET status = :s WHERE user_id = :u"),
               {"s": "active" if active else "suspended", "u": user_id})
    if not active:
        db.execute(text("SELECT app.auth_revoke_account_sessions(:a, 'user_deactivated')"), {"a": user["account_id"]})
        quota_service.release(db, sec.tenant_id, "users")  # type: ignore[arg-type]
    else:
        quota_service.consume(db, sec, "users")
    _audit(db, sec, "user_activated" if active else "user_deactivated", "user", user_id)
    return get_user(db, user_id)


def revoke_sessions(db: Session, sec: SecurityContext, user_id: uuid.UUID) -> int:
    user = get_user(db, user_id)
    n = db.execute(text("SELECT app.auth_revoke_account_sessions(:a, 'admin_revoked')"), {"a": user["account_id"]}).scalar()
    _audit(db, sec, "sessions_revoked", "user", user_id, {"count": n}, category="security")
    return int(n or 0)


def list_users(db: Session, *, q: str | None, status: str | None, department_id: uuid.UUID | None,
               limit: int, offset: int, sort: str = "display_name") -> tuple[list[dict[str, Any]], int]:
    where, params = ["true"], {"limit": limit, "offset": offset}
    if q:
        where.append("(u.display_name ILIKE :q OR u.email::text ILIKE :q)")
        params["q"] = f"%{q}%"
    if status:
        where.append("u.status = :status")
        params["status"] = status
    if department_id:
        where.append("u.department_id = :dep")
        params["dep"] = department_id
    order = {"display_name": "u.display_name", "email": "u.email", "created_at": "u.created_at DESC",
             "last_active_at": "u.last_active_at DESC NULLS LAST"}.get(sort, "u.display_name")
    w = " AND ".join(where)
    total = db.execute(text(f"SELECT count(*) FROM iam.users u WHERE {w}"), params).scalar_one()
    rows = db.execute(text(f"""
        SELECT u.user_id, u.email::text AS email, u.display_name, u.user_type, u.department_id, u.status,
               u.clearance_rank, u.lines_of_business, u.jurisdictions, u.created_at, u.last_active_at,
               ARRAY(SELECT r.code FROM iam.user_roles ur JOIN iam.roles r ON r.role_id = ur.role_id
                      WHERE ur.user_id = u.user_id) AS roles
          FROM iam.users u WHERE {w} ORDER BY {order} LIMIT :limit OFFSET :offset"""), params).mappings().all()
    return [dict(r) for r in rows], int(total)


# --- roles ---------------------------------------------------------------------------------
def assign_role(db: Session, sec: SecurityContext, user_id: uuid.UUID, *, role_code: str | None = None,
                role_id: uuid.UUID | None = None, valid_to: Any = None, audit: bool = True) -> None:
    if role_id is None:
        role_id = db.execute(text("SELECT role_id FROM iam.roles WHERE code = :c"), {"c": role_code}).scalar()
    if role_id is None:
        raise NotFound(f"Role {role_code} not found")
    db.execute(text("""INSERT INTO iam.user_roles (tenant_id, user_id, role_id, granted_by, valid_to)
                       VALUES (:t, :u, :r, :g, :vt)
                       ON CONFLICT (user_id, role_id) DO UPDATE SET valid_to = EXCLUDED.valid_to,
                              granted_by = EXCLUDED.granted_by, granted_at = now()"""),
               {"t": sec.tenant_id, "u": user_id, "r": role_id, "g": sec.user_id, "vt": valid_to})
    if audit:
        _audit(db, sec, "role_assigned", "user", user_id, {"role_id": str(role_id)}, category="authorization")


def unassign_role(db: Session, sec: SecurityContext, user_id: uuid.UUID, role_id: uuid.UUID) -> None:
    db.execute(text("DELETE FROM iam.user_roles WHERE user_id = :u AND role_id = :r"), {"u": user_id, "r": role_id})
    _audit(db, sec, "role_unassigned", "user", user_id, {"role_id": str(role_id)}, category="authorization")


def list_roles(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(text("""
        SELECT r.role_id, r.code, r.name, r.description, r.is_system, r.is_admin, r.conflicts_with, r.created_at,
               ARRAY(SELECT permission_code FROM iam.role_permissions p WHERE p.role_id = r.role_id ORDER BY 1) AS permissions,
               (SELECT count(*) FROM iam.user_roles ur WHERE ur.role_id = r.role_id) AS user_count
          FROM iam.roles r ORDER BY r.is_system DESC, r.name""")).mappings().all()
    return [dict(r) for r in rows]


def _validate_permissions(db: Session, permissions: list[str]) -> None:
    known = set(db.execute(text("SELECT permission_code FROM iam.permissions")).scalars())
    unknown = sorted(set(permissions) - known)
    if unknown:
        raise ValidationFailed("Unknown permissions", details=[{"field": "permissions", "message": p} for p in unknown])


def create_role(db: Session, sec: SecurityContext, *, code: str, name: str, description: str | None,
                permissions: list[str], conflicts_with: list[str] | None = None) -> dict[str, Any]:
    if code in SYSTEM_ROLE_CODES:
        raise Conflict("Role code is reserved for a system role")
    _validate_permissions(db, permissions)
    rid = uuid.uuid4()
    db.execute(text("""INSERT INTO iam.roles (tenant_id, role_id, code, name, description, is_system, is_admin, conflicts_with)
                       VALUES (:t, :r, :c, :n, :d, false, :a, :cw)"""),
               {"t": sec.tenant_id, "r": rid, "c": code, "n": name, "d": description,
                "a": any(p.startswith("admin.") for p in permissions), "cw": conflicts_with or []})
    for p in permissions:
        db.execute(text("INSERT INTO iam.role_permissions (tenant_id, role_id, permission_code) VALUES (:t, :r, :p)"),
                   {"t": sec.tenant_id, "r": rid, "p": p})
    _audit(db, sec, "role_created", "role", rid, {"code": code, "permissions": permissions}, category="authorization")
    return next(r for r in list_roles(db) if r["role_id"] == rid)


def update_role(db: Session, sec: SecurityContext, role_id: uuid.UUID, *, name: str | None, description: str | None,
                permissions: list[str] | None) -> dict[str, Any]:
    role = db.execute(text("SELECT * FROM iam.roles WHERE role_id = :r"), {"r": role_id}).mappings().first()
    if role is None:
        raise NotFound("Role not found")
    if role["is_system"]:
        raise PermissionDenied("System-defined roles cannot be modified", code="system_role_protected")
    if name or description is not None:
        db.execute(text("UPDATE iam.roles SET name = COALESCE(:n, name), description = COALESCE(:d, description) "
                        "WHERE role_id = :r"), {"n": name, "d": description, "r": role_id})
    if permissions is not None:
        _validate_permissions(db, permissions)
        db.execute(text("DELETE FROM iam.role_permissions WHERE role_id = :r"), {"r": role_id})
        for p in permissions:
            db.execute(text("INSERT INTO iam.role_permissions (tenant_id, role_id, permission_code) VALUES (:t, :r, :p)"),
                       {"t": sec.tenant_id, "r": role_id, "p": p})
        db.execute(text("UPDATE iam.roles SET is_admin = :a WHERE role_id = :r"),
                   {"a": any(p.startswith("admin.") for p in permissions), "r": role_id})
    _audit(db, sec, "role_updated", "role", role_id, {"permissions": permissions}, category="authorization")
    return next(r for r in list_roles(db) if r["role_id"] == role_id)


def delete_role(db: Session, sec: SecurityContext, role_id: uuid.UUID) -> None:
    role = db.execute(text("SELECT is_system FROM iam.roles WHERE role_id = :r"), {"r": role_id}).scalar()
    if role is None:
        raise NotFound("Role not found")
    if role:
        raise PermissionDenied("System-defined roles cannot be deleted", code="system_role_protected")
    db.execute(text("DELETE FROM iam.roles WHERE role_id = :r"), {"r": role_id})
    _audit(db, sec, "role_deleted", "role", role_id, category="authorization")


def effective_permissions(db: Session, user_id: uuid.UUID) -> list[str]:
    return list(db.execute(text("""SELECT DISTINCT rp.permission_code FROM iam.user_roles ur
                                   JOIN iam.role_permissions rp ON rp.role_id = ur.role_id
                                  WHERE ur.user_id = :u AND ur.valid_from <= now()
                                    AND (ur.valid_to IS NULL OR ur.valid_to > now()) ORDER BY 1"""),
                              {"u": user_id}).scalars())


# --- departments, teams, groups ---------------------------------------------------------------
def create_department(db: Session, sec: SecurityContext, code: str, name: str, description: str | None,
                      parent_id: uuid.UUID | None) -> dict[str, Any]:
    did = uuid.uuid4()
    db.execute(text("""INSERT INTO iam.departments (tenant_id, department_id, code, name, description, parent_department_id)
                       VALUES (:t, :d, :c, :n, :ds, :p)"""),
               {"t": sec.tenant_id, "d": did, "c": code, "n": name, "ds": description, "p": parent_id})
    _audit(db, sec, "department_created", "department", did, {"code": code})
    return dict(db.execute(text("SELECT * FROM iam.departments WHERE department_id = :d"), {"d": did}).mappings().one())


def update_department(db: Session, sec: SecurityContext, department_id: uuid.UUID, changes: dict[str, Any]) -> dict[str, Any]:
    allowed = {k: v for k, v in changes.items() if k in {"name", "description", "status"} and v is not None}
    if allowed:
        sets = ", ".join(f"{k} = :{k}" for k in allowed)
        res = db.execute(text(f"UPDATE iam.departments SET {sets} WHERE department_id = :id"), {**allowed, "id": department_id})
        if res.rowcount == 0:
            raise NotFound("Department not found")
    _audit(db, sec, "department_updated", "department", department_id, {"changed": sorted(allowed)})
    return dict(db.execute(text("SELECT * FROM iam.departments WHERE department_id = :d"), {"d": department_id}).mappings().one())


def create_team(db: Session, sec: SecurityContext, department_id: uuid.UUID, name: str, description: str | None) -> dict[str, Any]:
    tid = uuid.uuid4()
    db.execute(text("INSERT INTO iam.teams (tenant_id, team_id, department_id, name, description) VALUES (:t, :id, :d, :n, :ds)"),
               {"t": sec.tenant_id, "id": tid, "d": department_id, "n": name, "ds": description})
    _audit(db, sec, "team_created", "team", tid)
    return dict(db.execute(text("SELECT * FROM iam.teams WHERE team_id = :id"), {"id": tid}).mappings().one())


def add_team_member(db: Session, sec: SecurityContext, team_id: uuid.UUID, user_id: uuid.UUID) -> None:
    db.execute(text("INSERT INTO iam.team_members (tenant_id, team_id, user_id) VALUES (:t, :g, :u) ON CONFLICT DO NOTHING"),
               {"t": sec.tenant_id, "g": team_id, "u": user_id})
    _audit(db, sec, "team_member_added", "team", team_id, {"user_id": str(user_id)}, category="authorization")


def create_group(db: Session, sec: SecurityContext, name: str, description: str | None) -> dict[str, Any]:
    gid = uuid.uuid4()
    db.execute(text("INSERT INTO iam.user_groups (tenant_id, group_id, name, description) VALUES (:t, :g, :n, :d)"),
               {"t": sec.tenant_id, "g": gid, "n": name, "d": description})
    _audit(db, sec, "group_created", "group", gid, {"name": name})
    return dict(db.execute(text("SELECT * FROM iam.user_groups WHERE group_id = :g"), {"g": gid}).mappings().one())


def add_group_member(db: Session, sec: SecurityContext, group_id: uuid.UUID, user_id: uuid.UUID,
                     audit: bool = True) -> None:
    db.execute(text("""INSERT INTO iam.user_group_members (tenant_id, group_id, user_id, added_by)
                       VALUES (:t, :g, :u, :by) ON CONFLICT DO NOTHING"""),
               {"t": sec.tenant_id, "g": group_id, "u": user_id, "by": sec.user_id})
    if audit:
        _audit(db, sec, "group_member_added", "group", group_id, {"user_id": str(user_id)}, category="authorization")


def remove_group_member(db: Session, sec: SecurityContext, group_id: uuid.UUID, user_id: uuid.UUID) -> None:
    db.execute(text("DELETE FROM iam.user_group_members WHERE group_id = :g AND user_id = :u"), {"g": group_id, "u": user_id})
    _audit(db, sec, "group_member_removed", "group", group_id, {"user_id": str(user_id)}, category="authorization")
