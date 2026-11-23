"""Authentication, sessions, tenant selection, MFA (FR-002..FR-012)."""
from __future__ import annotations

import uuid

from tests.conftest import PASSWORD, auth, login


def test_invalid_credentials_and_lockout(client, tenants):
    email = tenants["A"]["users"]["outsider"]["email"]
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    assert r.json()["error"]["correlation_id"]
    r = client.post("/api/v1/auth/login", json={"email": "nobody@nowhere.test", "password": "x"})
    assert r.status_code == 401


def test_tampered_and_missing_tokens_rejected(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_me_reports_console_and_permissions(client, tenants):
    me = client.get("/api/v1/auth/me", headers=tenants["A"]["admin"]).json()
    assert me["console"] == "tenant_admin" and "admin.users.manage" in me["permissions"]
    me = client.get("/api/v1/auth/me", headers=tenants["A"]["analyst"]).json()
    assert me["console"] == "user" and not any(p.startswith("admin.") for p in me["permissions"])


def test_refresh_rotation_and_reuse_detection(client, tenants):
    tok = login(client, tenants["A"]["users"]["outsider"]["email"])
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r1.status_code == 200
    # replaying the rotated token revokes the session
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r2.status_code == 401 and r2.json()["error"]["code"] == "token_reuse"
    assert client.get("/api/v1/auth/me", headers=auth(r1.json())).status_code == 401


def test_logout_revokes_session(client, tenants):
    tok = login(client, tenants["A"]["users"]["outsider"]["email"])
    h = auth(tok)
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 200
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401


def test_tenant_selection_validated_server_side(client, tenants, platform_admin):
    a, b = tenants["A"], tenants["B"]
    # A user of tenant A may not select tenant B
    r = client.post("/api/v1/auth/select-tenant", headers=a["outsider"], json={"tenant_id": str(b["tenant"]["tenant_id"])})
    assert r.status_code == 403
    # Multi-tenant membership: add A's outsider to tenant B, then switching works
    email = a["users"]["outsider"]["email"]
    r = client.post("/api/v1/admin/users", headers=b["admin"], json={"email": email, "display_name": "Shared", "roles": ["member"]})
    assert r.status_code == 201, r.text
    tok = login(client, email, tenant_id=a["tenant"]["tenant_id"])
    assert {m["tenant_id"] for m in tok["memberships"]} == {a["tenant"]["tenant_id"], b["tenant"]["tenant_id"]}
    sw = client.post("/api/v1/auth/select-tenant", headers=auth(tok), json={"tenant_id": str(b["tenant"]["tenant_id"])})
    assert sw.status_code == 200 and sw.json()["tenant_id"] == b["tenant"]["tenant_id"]
    assert client.get("/api/v1/auth/me", headers=auth(sw.json())).json()["tenant_id"] == b["tenant"]["tenant_id"]
    # the old session was revoked by the switch
    assert client.get("/api/v1/auth/me", headers=auth(tok)).status_code == 401


def test_tenant_id_in_body_or_query_is_never_trusted(client, tenants):
    """Admin endpoints act on the token's validated tenant only; foreign ids are invisible (404)."""
    a, b = tenants["A"], tenants["B"]
    b_user = b["users"]["analyst"]["user_id"]
    assert client.get(f"/api/v1/admin/users/{b_user}", headers=a["admin"]).status_code == 404
    assert client.get(f"/api/v1/documents/{b['docs'][0]['document_id']}", headers=a["analyst"]).status_code == 404
    r = client.get(f"/api/v1/admin/users?tenant_id={b['tenant']['tenant_id']}", headers=a["admin"])
    assert r.status_code == 200 and all(u["user_id"] != b_user for u in r.json()["items"])


def test_mfa_enrolment_and_login(client, database, platform_admin):
    from app.security import totp

    r = client.post("/api/v1/platform/tenants", headers=platform_admin, json={
        "code": f"mfa-{uuid.uuid4().hex[:6]}", "name": "MFA Co", "plan_code": "starter",
        "admin_email": f"mfa-{uuid.uuid4().hex[:6]}@mfa.test", "admin_password": PASSWORD})
    email = r.json()["initial_admin"]["email"]
    h = auth(login(client, email))
    secret = client.post("/api/v1/auth/mfa/enroll", headers=h).json()["secret"]
    assert client.post("/api/v1/auth/mfa/verify", headers=h, json={"code": totp.current_code(secret)}).status_code == 200
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 401 and r.json()["error"]["code"] == "mfa_required"
    tok = login(client, email, mfa_code=totp.current_code(secret))
    assert client.get("/api/v1/auth/me", headers=auth(tok)).json()["mfa_verified"] is True


def test_password_reset_workflow(client, tenants):
    a = tenants["A"]
    uid = a["users"]["outsider"]["user_id"]
    r = client.post(f"/api/v1/admin/users/{uid}/password-reset", headers=a["admin"])
    assert r.status_code == 200
    token = r.json()["reset_token"]
    assert client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": "weak"}).status_code == 422
    new = "N3w!Password#2026x"
    assert client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": new}).status_code == 200
    assert client.post("/api/v1/auth/password/reset", json={"token": token, "new_password": new}).status_code == 401
    login(client, a["users"]["outsider"]["email"], new)
    # restore for other tests
    r = client.post(f"/api/v1/admin/users/{uid}/password-reset", headers=a["admin"])
    client.post("/api/v1/auth/password/reset", json={"token": r.json()["reset_token"], "new_password": PASSWORD})
    a["outsider"] = auth(login(client, a["users"]["outsider"]["email"]))


def test_oidc_token_validation(database):
    """FR-005: signature, issuer, audience, expiry are validated (RSA key, no network)."""
    import time

    import jwt
    import pytest
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.core.config import Settings
    from app.core.errors import AuthenticationError
    from app.security.oidc import validate_oidc_token

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    s = Settings(auth_mode="both", oidc_issuer="https://idp.test", oidc_audience="rag", oidc_jwks_url="https://idp.test/jwks")
    now = int(time.time())
    good = jwt.encode({"iss": "https://idp.test", "aud": "rag", "sub": "u1", "email": "U1@corp.test", "iat": now,
                       "exp": now + 60, "amr": ["mfa"]}, key, algorithm="RS256")
    ident = validate_oidc_token(s, good, signing_key=key.public_key())
    assert ident.email == "u1@corp.test" and ident.mfa
    bad_aud = jwt.encode({"iss": "https://idp.test", "aud": "other", "sub": "u1", "email": "a@b.c", "iat": now, "exp": now + 60},
                         key, algorithm="RS256")
    with pytest.raises(AuthenticationError):
        validate_oidc_token(s, bad_aud, signing_key=key.public_key())
    expired = jwt.encode({"iss": "https://idp.test", "aud": "rag", "sub": "u1", "email": "a@b.c", "iat": now - 120,
                          "exp": now - 60}, key, algorithm="RS256")
    with pytest.raises(AuthenticationError):
        validate_oidc_token(s, expired, signing_key=key.public_key())
