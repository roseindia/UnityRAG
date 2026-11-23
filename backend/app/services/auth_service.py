"""Authentication, session and tenant-context resolution (FR-001..FR-012, FR-181).

Tenant identity comes exclusively from (validated token) -> (live session) ->
(active membership) -> (operational tenant) -> (active tenant user).  Nothing
supplied in a URL, query string or body is trusted as tenant identity.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.core.errors import AppError, AuthenticationError, PermissionDenied, TenantUnavailable, ValidationFailed
from app.database.session import SecurityContext, scoped_session
from app.security import totp
from app.security.context import RequestContext
from app.security.crypto import decrypt_secret, encrypt_secret
from app.security.oidc import validate_oidc_token
from app.security.passwords import hash_password, password_policy_errors, verify_password
from app.security.tokens import decode_access_token, hash_token, issue_access_token, new_refresh_token
from app.services.audit import audit_out_of_band, platform_audit_out_of_band

log = logging.getLogger("app.auth")
_ANON = SecurityContext.anonymous()
OPERATIONAL = ("active", "trial")


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_at: datetime
    tenant_id: uuid.UUID | None
    session_id: uuid.UUID
    memberships: list[dict[str, Any]]
    platform_role: str | None


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:24]


def list_memberships(account_id: uuid.UUID) -> list[dict[str, Any]]:
    with scoped_session(_ANON) as db:
        rows = db.execute(text("SELECT * FROM app.auth_list_memberships(:a)"), {"a": account_id}).mappings().all()
    return [dict(r) for r in rows]


def platform_role_of(account_id: uuid.UUID) -> str | None:
    with scoped_session(_ANON) as db:
        return db.execute(text("SELECT app.auth_platform_role(:a)"), {"a": account_id}).scalar()


def _pick_tenant(memberships: list[dict[str, Any]], requested: uuid.UUID | None) -> dict[str, Any] | None:
    usable = [m for m in memberships if m["membership_status"] == "active" and m["user_status"] == "active"
              and m["tenant_status"] in OPERATIONAL]
    if requested is not None:
        for m in memberships:
            if m["tenant_id"] == requested:
                if m not in usable:
                    raise TenantUnavailable("The selected tenant is not available for this account")
                return m
        raise PermissionDenied("The account is not a member of the selected tenant", code="tenant_not_authorized")
    return usable[0] if usable else None


def _create_session(settings: Settings, account_id: uuid.UUID, tenant: dict[str, Any] | None, *, mfa: bool,
                    method: str, ip: str | None, ua: str | None, memberships: list[dict[str, Any]],
                    platform_role: str | None) -> TokenBundle:
    refresh, refresh_hash = new_refresh_token()
    now = datetime.now(UTC)
    absolute = now + timedelta(hours=settings.refresh_token_hours)
    tenant_id = tenant["tenant_id"] if tenant else None
    with scoped_session(_ANON) as db:
        session_id = db.execute(text(
            "SELECT app.auth_create_session(:a, :t, :h, :abs, :rexp, :mfa, :m, CAST(:ip AS inet), :ua)"),
            {"a": account_id, "t": tenant_id, "h": refresh_hash, "abs": absolute, "rexp": absolute, "mfa": mfa,
             "m": method, "ip": ip, "ua": ua}).scalar_one()
    access, exp = issue_access_token(settings, account_id=account_id, session_id=session_id, tenant_id=tenant_id, mfa=mfa)
    return TokenBundle(access, refresh, exp, tenant_id, session_id, _public_memberships(memberships), platform_role)


def _public_memberships(memberships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"tenant_id": m["tenant_id"], "tenant_code": m["tenant_code"], "tenant_name": m["tenant_name"],
             "tenant_status": m["tenant_status"], "membership_status": m["membership_status"],
             "is_default": m["is_default"]} for m in memberships]


def login(email: str, password: str, *, tenant_id: uuid.UUID | None = None, mfa_code: str | None = None,
          ip: str | None = None, user_agent: str | None = None) -> TokenBundle:
    settings = get_settings()
    if settings.auth_mode == "oidc":
        raise AuthenticationError("Password login is disabled; use single sign-on", code="password_login_disabled")
    with scoped_session(_ANON) as db:
        acct = db.execute(text("SELECT * FROM app.auth_lookup_account(:e)"), {"e": email.strip().lower()}).mappings().first()

    def fail(reason: str, account_id: uuid.UUID | None) -> None:
        with scoped_session(_ANON) as db2:
            db2.execute(text("SELECT app.auth_record_login(:a, false, :r, 'password', CAST(:ip AS inet), :ua, :eh, :th, :lm)"),
                        {"a": account_id, "r": reason, "ip": ip, "ua": user_agent, "eh": _email_hash(email),
                         "th": settings.lockout_threshold, "lm": settings.lockout_minutes})

    if acct is None or acct["auth_provider"] != "local":
        verify_password(password, None)  # constant-time behaviour for unknown accounts
        fail("unknown_account" if acct is None else "sso_account", acct["account_id"] if acct else None)
        raise AuthenticationError("Invalid credentials", code="invalid_credentials")
    if acct["status"] != "active":
        fail("account_" + acct["status"], acct["account_id"])
        raise AuthenticationError("Account is not active", code="account_inactive")
    if acct["locked_until"] and acct["locked_until"] > datetime.now(UTC):
        fail("locked", acct["account_id"])
        raise AuthenticationError("Account temporarily locked", code="account_locked")
    if not verify_password(password, acct["password_hash"]):
        fail("bad_password", acct["account_id"])
        raise AuthenticationError("Invalid credentials", code="invalid_credentials")
    mfa = False
    if acct["mfa_enabled"]:
        secret = decrypt_secret(acct["mfa_secret_enc"])
        if not mfa_code:
            raise AuthenticationError("Multi-factor code required", code="mfa_required")
        if not secret or not totp.verify(secret, mfa_code):
            fail("bad_mfa", acct["account_id"])
            raise AuthenticationError("Invalid multi-factor code", code="invalid_mfa")
        mfa = True

    account_id = acct["account_id"]
    memberships = list_memberships(account_id)
    platform_role = platform_role_of(account_id)
    tenant = _pick_tenant(memberships, tenant_id)
    if tenant is None and platform_role is None:
        fail("no_active_tenant", account_id)
        raise TenantUnavailable("No active tenant membership is available for this account")
    with scoped_session(_ANON) as db:
        db.execute(text("SELECT app.auth_record_login(:a, true, 'ok', 'password', CAST(:ip AS inet), :ua, :eh, :th, :lm)"),
                   {"a": account_id, "ip": ip, "ua": user_agent, "eh": _email_hash(email),
                    "th": settings.lockout_threshold, "lm": settings.lockout_minutes})
    bundle = _create_session(settings, account_id, tenant, mfa=mfa, method="password", ip=ip, ua=user_agent,
                             memberships=memberships, platform_role=platform_role)
    if tenant:
        audit_out_of_band(SecurityContext(access_mode="user", tenant_id=tenant["tenant_id"], user_id=tenant["user_id"],
                                          account_id=account_id),
                          tenant_id=tenant["tenant_id"], category="authentication", event_type="login",
                          actor_user_id=tenant["user_id"], actor_account_id=account_id, source_ip=ip,
                          detail={"method": "password", "mfa": mfa, "session_id": str(bundle.session_id)})
    else:
        platform_audit_out_of_band(category="authentication", action="platform_login", actor_account_id=account_id,
                                   source_ip=ip, detail={"mfa": mfa})
    return bundle


def exchange_oidc(id_token: str, *, tenant_id: uuid.UUID | None = None, ip: str | None = None,
                  user_agent: str | None = None, signing_key: Any | None = None) -> TokenBundle:
    settings = get_settings()
    identity = validate_oidc_token(settings, id_token, signing_key=signing_key)
    with scoped_session(_ANON) as db:
        acct = db.execute(text("SELECT * FROM app.auth_lookup_external('oidc', :s, :e)"),
                          {"s": identity.subject, "e": identity.email}).mappings().first()
    if acct is None or acct["status"] != "active":
        raise AuthenticationError("This identity has not been provisioned for the platform", code="not_provisioned")
    memberships = list_memberships(acct["account_id"])
    platform_role = platform_role_of(acct["account_id"])
    tenant = _pick_tenant(memberships, tenant_id)
    if tenant is None and platform_role is None:
        raise TenantUnavailable("No active tenant membership is available for this account")
    return _create_session(settings, acct["account_id"], tenant, mfa=identity.mfa, method="oidc", ip=ip,
                           ua=user_agent, memberships=memberships, platform_role=platform_role)


def refresh(refresh_token: str) -> TokenBundle:
    settings = get_settings()
    new_token, new_hash = new_refresh_token()
    with scoped_session(_ANON) as db:
        row = db.execute(text("SELECT * FROM app.auth_rotate_refresh(:o, :n, :e)"),
                         {"o": hash_token(refresh_token), "n": new_hash,
                          "e": datetime.now(UTC) + timedelta(hours=settings.refresh_token_hours)}).mappings().one()
    if row["result"] == "reuse_detected":
        platform_audit_out_of_band(category="security", action="refresh_token_reuse", severity="high",
                                   actor_account_id=row["account_id"], target_tenant_id=row["tenant_id"],
                                   detail={"session_id": str(row["session_id"])})
        raise AuthenticationError("Refresh token reuse detected; session revoked", code="token_reuse")
    if row["result"] != "ok":
        raise AuthenticationError("Refresh token invalid or expired", code="invalid_refresh_token")
    # Membership / tenant status are re-validated before a new access token is issued.
    if row["tenant_id"] is not None:
        memberships = list_memberships(row["account_id"])
        _pick_tenant(memberships, row["tenant_id"])
    else:
        memberships = list_memberships(row["account_id"])
    access, exp = issue_access_token(settings, account_id=row["account_id"], session_id=row["session_id"],
                                     tenant_id=row["tenant_id"], mfa=row["mfa_verified_at"] is not None)
    return TokenBundle(access, new_token, exp, row["tenant_id"], row["session_id"], _public_memberships(memberships),
                       platform_role_of(row["account_id"]))


def switch_tenant(ctx: RequestContext, tenant_id: uuid.UUID, ip: str | None, user_agent: str | None) -> TokenBundle:
    memberships = list_memberships(ctx.account_id)
    tenant = _pick_tenant(memberships, tenant_id)
    with scoped_session(_ANON) as db:
        db.execute(text("SELECT app.auth_revoke_session(:s, :a, 'tenant_switch')"),
                   {"s": ctx.session_id, "a": ctx.account_id})
    return _create_session(get_settings(), ctx.account_id, tenant, mfa=ctx.mfa_verified_at is not None,
                           method="tenant_switch", ip=ip, ua=user_agent, memberships=memberships,
                           platform_role=platform_role_of(ctx.account_id))


def logout(ctx: RequestContext) -> None:
    with scoped_session(_ANON) as db:
        db.execute(text("SELECT app.auth_revoke_session(:s, :a, 'logout')"), {"s": ctx.session_id, "a": ctx.account_id})
    if ctx.tenant_id:
        audit_out_of_band(ctx.security("user"), tenant_id=ctx.tenant_id, category="authentication",
                          event_type="logout", actor_user_id=ctx.user_id, actor_account_id=ctx.account_id)


# --- MFA -------------------------------------------------------------------------------
def mfa_enroll(ctx: RequestContext) -> dict[str, str]:
    secret = totp.new_secret()
    with scoped_session(SecurityContext(access_mode="user", account_id=ctx.account_id)) as db:
        db.execute(text("UPDATE iam.user_accounts SET mfa_secret_enc = :s, mfa_enabled = false WHERE account_id = :a"),
                   {"s": encrypt_secret(secret), "a": ctx.account_id})
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, ctx.email)}


def mfa_verify(ctx: RequestContext, code: str, *, enable: bool) -> None:
    with scoped_session(SecurityContext(access_mode="user", account_id=ctx.account_id)) as db:
        enc = db.execute(text("SELECT mfa_secret_enc FROM iam.user_accounts WHERE account_id = :a"),
                         {"a": ctx.account_id}).scalar()
        secret = decrypt_secret(enc)
        if not secret or not totp.verify(secret, code):
            raise AuthenticationError("Invalid multi-factor code", code="invalid_mfa")
        if enable:
            db.execute(text("UPDATE iam.user_accounts SET mfa_enabled = true WHERE account_id = :a"), {"a": ctx.account_id})
        db.execute(text("SELECT app.auth_mark_mfa(:s, :a)"), {"s": ctx.session_id, "a": ctx.account_id})


# --- Password management ---------------------------------------------------------------
def change_password(ctx: RequestContext, current: str, new: str) -> None:
    settings = get_settings()
    errors = password_policy_errors(new, settings.password_min_length)
    if errors:
        raise ValidationFailed("Password does not meet policy", details=[{"field": "new_password", "message": e} for e in errors])
    with scoped_session(_ANON) as db:
        acct = db.execute(text("SELECT * FROM app.auth_lookup_account(:e)"), {"e": ctx.email}).mappings().first()
    if not acct or not verify_password(current, acct["password_hash"]):
        raise AuthenticationError("Current password is incorrect", code="invalid_credentials")
    with scoped_session(SecurityContext(access_mode="user", account_id=ctx.account_id)) as db:
        db.execute(text("UPDATE iam.user_accounts SET password_hash = :h, password_changed_at = now() WHERE account_id = :a"),
                   {"h": hash_password(new), "a": ctx.account_id})


def create_password_reset(sec: SecurityContext, account_id: uuid.UUID) -> str:
    """Issue a single-use reset token.  Delivery happens out of band (e-mail /
    notification integration); the token is returned to the authorised caller only."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(minutes=get_settings().password_reset_minutes)
    with scoped_session(sec) as db:
        db.execute(text("SELECT app.auth_create_reset_token(:a, :h, :e)"),
                   {"a": account_id, "h": hash_token(token), "e": expires})
    return token


def consume_password_reset(token: str, new_password: str) -> None:
    errors = password_policy_errors(new_password, get_settings().password_min_length)
    if errors:
        raise ValidationFailed("Password does not meet policy", details=[{"field": "new_password", "message": e} for e in errors])
    with scoped_session(_ANON) as db:
        account = db.execute(text("SELECT app.auth_consume_reset_token(:h, :p)"),
                             {"h": hash_token(token), "p": hash_password(new_password)}).scalar()
    if account is None:
        raise AuthenticationError("Reset token invalid or expired", code="invalid_reset_token")


# --- Per-request resolution --------------------------------------------------------------
_CONTEXT_SQL = text("""
    SELECT u.user_id, u.email, u.display_name, u.user_type, u.department_id, u.business_unit,
           u.lines_of_business, u.jurisdictions, u.clearance_rank,
           ARRAY(SELECT g.group_id FROM iam.user_group_members g WHERE g.user_id = u.user_id
                  AND g.valid_from <= now() AND (g.valid_to IS NULL OR g.valid_to > now())) AS group_ids,
           ARRAY(SELECT r.role_id FROM iam.user_roles r WHERE r.user_id = u.user_id
                  AND r.valid_from <= now() AND (r.valid_to IS NULL OR r.valid_to > now())) AS role_ids,
           ARRAY(SELECT t.team_id FROM iam.team_members t WHERE t.user_id = u.user_id) AS team_ids,
           ARRAY(SELECT DISTINCT ro.code FROM iam.user_roles r JOIN iam.roles ro ON ro.role_id = r.role_id
                  WHERE r.user_id = u.user_id AND r.valid_from <= now() AND (r.valid_to IS NULL OR r.valid_to > now())) AS role_codes,
           ARRAY(SELECT DISTINCT rp.permission_code FROM iam.user_roles r
                   JOIN iam.role_permissions rp ON rp.role_id = r.role_id
                  WHERE r.user_id = u.user_id AND r.valid_from <= now() AND (r.valid_to IS NULL OR r.valid_to > now())) AS permissions
      FROM iam.users u WHERE u.user_id = :uid""")


def resolve_request_context(token: str, ip: str | None = None) -> RequestContext:
    settings = get_settings()
    claims = decode_access_token(settings, token)
    with scoped_session(_ANON) as db:
        row = db.execute(text("SELECT * FROM app.auth_resolve_request(:a, :s, :t)"),
                         {"a": claims.account_id, "s": claims.session_id, "t": claims.tenant_id}).mappings().one()
    if not row["session_ok"]:
        raise AuthenticationError("Session is no longer valid", code=f"session_{row['session_reason']}")
    platform_role = row["platform_role"]
    platform_permissions: frozenset[str] = frozenset()
    if platform_role:
        with scoped_session(_ANON) as db:
            platform_permissions = frozenset(db.execute(text(
                "SELECT rp.permission_code FROM platform.platform_role_permissions rp "
                "JOIN platform.platform_roles r ON r.role_id = rp.role_id WHERE r.code = :c"), {"c": platform_role}).scalars())

    if claims.tenant_id is None:
        if not platform_role:
            raise PermissionDenied("Platform session without platform role", code="no_platform_role")
        with scoped_session(SecurityContext(access_mode="user", account_id=claims.account_id)) as db:
            me = db.execute(text("SELECT email::text AS email, display_name FROM iam.user_accounts WHERE account_id = :a"),
                            {"a": claims.account_id}).mappings().one()
        return RequestContext(account_id=claims.account_id, session_id=claims.session_id, email=me["email"],
                              display_name=me["display_name"], tenant_id=None, tenant_status=None, user_id=None,
                              platform_role=platform_role, platform_permissions=platform_permissions,
                              mfa_verified_at=row["mfa_verified_at"], mfa_in_token=claims.mfa, ip=ip)

    if not row["membership_ok"]:
        raise PermissionDenied("Tenant membership is not active", code="membership_inactive")
    if row["tenant_status"] not in OPERATIONAL:
        raise TenantUnavailable(f"Tenant is {row['tenant_status']}", code="tenant_" + str(row["tenant_status"]))
    if row["user_status"] != "active":
        raise PermissionDenied("Tenant user is inactive", code="user_inactive")

    base = SecurityContext(access_mode="user", tenant_id=claims.tenant_id, user_id=row["user_id"],
                           account_id=claims.account_id)
    with scoped_session(base) as db:
        u = db.execute(_CONTEXT_SQL, {"uid": row["user_id"]}).mappings().one()
    return RequestContext(
        account_id=claims.account_id, session_id=claims.session_id, email=str(u["email"]),
        display_name=u["display_name"], tenant_id=claims.tenant_id, tenant_status=row["tenant_status"],
        user_id=u["user_id"], user_type=u["user_type"], department_id=u["department_id"],
        business_unit=u["business_unit"], platform_role=platform_role, permissions=frozenset(u["permissions"]),
        platform_permissions=platform_permissions, group_ids=tuple(u["group_ids"]), role_ids=tuple(u["role_ids"]),
        team_ids=tuple(u["team_ids"]), role_codes=tuple(u["role_codes"]),
        lines_of_business=tuple(u["lines_of_business"]), jurisdictions=tuple(u["jurisdictions"]),
        clearance_rank=int(u["clearance_rank"]), mfa_verified_at=row["mfa_verified_at"], mfa_in_token=claims.mfa, ip=ip)


def require_step_up(ctx: RequestContext, minutes: int | None = None) -> None:
    """Administrative functions require a recent MFA verification when the
    tenant (or platform) enforces it (FR-003, FR-023)."""
    minutes = minutes or get_settings().mfa_step_up_minutes
    if ctx.mfa_verified_at is None or ctx.mfa_verified_at < datetime.now(UTC) - timedelta(minutes=minutes):
        raise AppError("Step-up authentication required", code="step_up_required", status_code=401)
