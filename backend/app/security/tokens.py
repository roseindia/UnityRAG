"""Access tokens (short-lived JWT) and opaque refresh tokens (FR-005, FR-006).

The access token carries the account id, session id and the *validated* active
tenant chosen at login / tenant switch.  It is still re-validated against the
database on every request (session alive, membership active, tenant
operational) - the token is never the sole authority for tenant identity.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import Settings
from app.core.errors import AuthenticationError


@dataclass(frozen=True)
class AccessClaims:
    account_id: uuid.UUID
    session_id: uuid.UUID
    tenant_id: uuid.UUID | None
    mfa: bool
    expires_at: datetime


def issue_access_token(settings: Settings, *, account_id: uuid.UUID, session_id: uuid.UUID,
                       tenant_id: uuid.UUID | None, mfa: bool) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=settings.access_token_minutes)
    payload = {
        "iss": settings.jwt_issuer, "aud": settings.jwt_audience, "sub": str(account_id), "sid": str(session_id),
        "tid": str(tenant_id) if tenant_id else None, "amr": ["pwd", "mfa"] if mfa else ["pwd"],
        "iat": int(now.timestamp()), "nbf": int(now.timestamp()), "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex, "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm), exp


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    try:
        data = jwt.decode(token, settings.jwt_secret.get_secret_value(), algorithms=[settings.jwt_algorithm],
                          audience=settings.jwt_audience, issuer=settings.jwt_issuer,
                          options={"require": ["exp", "iat", "sub", "sid", "aud", "iss"]})
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token expired", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid access token", code="invalid_token") from exc
    if data.get("typ") != "access":
        raise AuthenticationError("Invalid token type", code="invalid_token")
    try:
        return AccessClaims(
            account_id=uuid.UUID(data["sub"]), session_id=uuid.UUID(data["sid"]),
            tenant_id=uuid.UUID(data["tid"]) if data.get("tid") else None,
            mfa="mfa" in (data.get("amr") or []),
            expires_at=datetime.fromtimestamp(data["exp"], tz=UTC))
    except (ValueError, KeyError) as exc:
        raise AuthenticationError("Malformed token claims", code="invalid_token") from exc


def new_refresh_token() -> tuple[str, str]:
    """Return (opaque token for the client, SHA-256 hash for storage)."""
    token = secrets.token_urlsafe(48)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
