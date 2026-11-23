import time
import uuid

import pytest

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.security import totp
from app.security.crypto import decrypt_secret, encrypt_secret
from app.security.passwords import hash_password, password_policy_errors, verify_password
from app.security.tokens import decode_access_token, issue_access_token


def test_password_hashing_and_policy():
    h = hash_password("Corr3ct!Horse#")
    assert h.startswith("scrypt$") and verify_password("Corr3ct!Horse#", h) and not verify_password("wrong", h)
    assert not verify_password("x", None)
    assert password_policy_errors("short") and not password_policy_errors("Long3nough!Pass")


def test_jwt_roundtrip_and_tamper_detection():
    s = Settings(jwt_secret="x" * 40)
    tok, _ = issue_access_token(s, account_id=uuid.uuid4(), session_id=uuid.uuid4(), tenant_id=uuid.uuid4(), mfa=True)
    claims = decode_access_token(s, tok)
    assert claims.mfa and claims.tenant_id
    with pytest.raises(AuthenticationError):
        decode_access_token(Settings(jwt_secret="y" * 40), tok)
    with pytest.raises(AuthenticationError):
        decode_access_token(s, tok[:-3] + "abc")
    expired = Settings(jwt_secret="x" * 40, access_token_minutes=-1)
    tok2, _ = issue_access_token(expired, account_id=uuid.uuid4(), session_id=uuid.uuid4(), tenant_id=None, mfa=False)
    with pytest.raises(AuthenticationError):
        decode_access_token(s, tok2)


def test_totp_rfc6238_and_window():
    secret = totp.new_secret()
    now = time.time()
    assert totp.verify(secret, totp.current_code(secret, now), at=now)
    assert totp.verify(secret, totp.current_code(secret, now - 30), at=now)
    assert not totp.verify(secret, totp.current_code(secret, now - 300), at=now)
    # RFC 6238 test vector (SHA1, T=59) -> 94287082 (8 digits); 6-digit truncation = 287082
    assert totp._code("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 1) == "287082"


def test_secret_encryption():
    enc = encrypt_secret("sk-live-abc")
    assert enc != "sk-live-abc" and decrypt_secret(enc) == "sk-live-abc" and decrypt_secret("garbage") is None


def test_production_settings_guard():
    with pytest.raises(ValueError):
        Settings(environment="production")
