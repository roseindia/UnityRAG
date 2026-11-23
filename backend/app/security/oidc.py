"""OpenID Connect bearer-token validation for corporate SSO (FR-002, FR-005, FR-181).

The platform does not run the IdP; it validates IdP-issued ID/access tokens
(signature via JWKS, issuer, audience, expiry, required claims) and exchanges
them for a platform session through /auth/oidc/exchange.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt

from app.core.config import Settings
from app.core.errors import AuthenticationError


@dataclass(frozen=True)
class ExternalIdentity:
    subject: str
    email: str
    name: str
    groups: tuple[str, ...]
    mfa: bool


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def validate_oidc_token(settings: Settings, token: str, *, signing_key: Any | None = None) -> ExternalIdentity:
    if settings.auth_mode == "local" or not settings.oidc_issuer:
        raise AuthenticationError("Single sign-on is not configured", code="sso_not_configured")
    try:
        key = signing_key or _jwks_client(settings.oidc_jwks_url or "").get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256", "ES256", "PS256"],
                            audience=settings.oidc_audience, issuer=settings.oidc_issuer,
                            options={"require": ["exp", "iat", "sub", "iss", "aud"]})
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Identity token expired", code="token_expired") from exc
    except (jwt.PyJWTError, jwt.PyJWKClientError) as exc:
        raise AuthenticationError("Invalid identity token", code="invalid_token") from exc
    email = claims.get(settings.oidc_email_claim)
    if not email:
        raise AuthenticationError("Identity token lacks an e-mail claim", code="invalid_token")
    amr = claims.get("amr") or []
    return ExternalIdentity(subject=str(claims["sub"]), email=str(email).lower(), name=str(claims.get("name") or email),
                            groups=tuple(claims.get("groups") or ()), mfa=("mfa" in amr or "otp" in amr))
