"""Symmetric encryption for secrets at rest (provider API keys, MFA seeds).

Uses Fernet (AES-128-CBC + HMAC-SHA256, authenticated).  In production the key
comes from SECRETS_ENCRYPTION_KEY (injected by the secrets manager / KMS); in
development it is derived from JWT_SECRET so local setups work out of the box.
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    if s.secrets_encryption_key is not None:
        key = s.secrets_encryption_key.get_secret_value().encode()
    else:
        key = base64.urlsafe_b64encode(hashlib.sha256(b"secrets:" + s.jwt_secret.get_secret_value().encode()).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def mask_secret(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    return "****" + plaintext[-4:] if len(plaintext) > 4 else "****"
