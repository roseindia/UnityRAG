"""Test configuration.

Integration, RLS, security and e2e tests run against a REAL PostgreSQL 16 +
pgvector database created from scratch by the bootstrap + Alembic migrations,
and connect with the non-superuser, non-BYPASSRLS service roles (rag_app /
rag_worker).  Set TEST_DB_SUPERUSER_DSN to point at your PostgreSQL server.
"""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_SSLMODE", "disable")
os.environ["DB_NAME"] = os.environ.get("TEST_DB_NAME", "rag_pytest")
os.environ.setdefault("DB_SUPERUSER_DSN", os.environ.get("TEST_DB_SUPERUSER_DSN", "host=127.0.0.1 user=postgres dbname=postgres"))
os.environ["CACHE_BACKEND"] = "memory"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
os.environ["CELERY_BROKER_URL"] = "memory://"
os.environ["CELERY_RESULT_BACKEND"] = "cache+memory://"
os.environ["STORAGE_ROOT"] = tempfile.mkdtemp(prefix="rag-test-storage-")
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-1234")
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["CHAT_RATE_LIMIT_PER_MINUTE"] = "100000"

PASSWORD = "Str0ng!Passw0rd#2026"


def _db_available() -> bool:
    try:
        import psycopg

        psycopg.connect(os.environ["DB_SUPERUSER_DSN"], connect_timeout=3).close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def database():
    if not _db_available():
        pytest.skip("PostgreSQL superuser DSN not reachable (TEST_DB_SUPERUSER_DSN)")
    from alembic.config import Config

    from alembic import command
    from app.database.bootstrap import bootstrap
    from app.database.session import dispose_engines

    dispose_engines()
    bootstrap(os.environ["DB_SUPERUSER_DSN"], drop_existing=True)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    command.upgrade(cfg, "head")
    yield
    dispose_engines()


@pytest.fixture(scope="session")
def client(database):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def login(client, email: str, password: str = PASSWORD, tenant_id=None, mfa_code=None) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password,
                                                "tenant_id": str(tenant_id) if tenant_id else None, "mfa_code": mfa_code})
    assert r.status_code == 200, r.text
    return r.json()


def auth(token: dict | str) -> dict:
    t = token["access_token"] if isinstance(token, dict) else token
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="session")
def platform_admin(database, client):
    from app.cli import create_platform_admin

    create_platform_admin("root@platform.test", PASSWORD)
    return auth(login(client, "root@platform.test"))


DOCS = {
    "A": [("motor_wording.md", """# Alpha Motor Policy Wording
Policy number: POL-2026-000123. Effective date: 01/01/2026.
## Section 4 - Exclusions
4.1 We will not pay for flood damage to a vehicle parked in a basement that was declared a flood zone.
4.2 We will not pay for mechanical breakdown or wear and tear.
## Section 5 - Excess
5.1 A standard excess of INR 2,500 applies to every own damage claim.
""", "policy_wording"),
          ("claims_manual.md", """# Alpha Claims Manual
## Section 6 - Authority limits
6.1 Claims adjusters may settle own damage claims up to INR 200,000. Larger claims are referred to the claims manager.
""", "claims_manual")],
    "B": [("health_wording.md", """# Beta Health Shield Wording
Policy number: POL-2026-777001.
## Section 3 - Waiting periods
3.1 A waiting period of 30 days applies to all illnesses except accidents.
3.2 A waiting period of 24 months applies to pre-existing diseases.
""", "policy_wording")],
}


def _build_tenant(client, platform_admin, key: str, lob: str) -> dict:
    code = f"tenant-{key.lower()}-{uuid.uuid4().hex[:6]}"
    r = client.post("/api/v1/platform/tenants", headers=platform_admin, json={
        "code": code, "name": f"Tenant {key}", "plan_code": "professional",
        "admin_email": f"admin@{code}.test", "admin_name": f"Admin {key}", "admin_password": PASSWORD})
    assert r.status_code == 201, r.text
    tenant = r.json()
    admin_h = auth(login(client, f"admin@{code}.test"))
    g = client.post("/api/v1/admin/groups", headers=admin_h, json={"name": f"{lob}-staff"})
    assert g.status_code == 201, g.text
    gid = g.json()["group_id"]
    dep = client.post("/api/v1/admin/departments", headers=admin_h, json={"code": "CLAIMS", "name": "Claims"}).json()
    users = {}
    for uname in ("analyst", "outsider"):
        body = {"email": f"{uname}@{code}.test", "display_name": uname, "password": PASSWORD, "roles": ["member"],
                "lines_of_business": [lob], "jurisdictions": ["*"], "clearance_rank": 2,
                "department_id": dep["department_id"], "group_ids": [gid] if uname == "analyst" else []}
        u = client.post("/api/v1/admin/users", headers=admin_h, json=body)
        assert u.status_code == 201, u.text
        users[uname] = u.json()
    coll = client.post("/api/v1/admin/collections", headers=admin_h, json={
        "code": f"{lob}-docs", "name": f"{lob} docs", "line_of_business": lob,
        "access": [{"principal_type": "group", "principal_id": gid, "permission": "write"}]})
    assert coll.status_code == 201, coll.text
    docs = []
    for fname, body, dtype in DOCS[key]:
        up = client.post("/api/v1/documents", headers=admin_h, data={"collection_id": coll.json()["collection_id"],
                                                                    "metadata": f'{{"document_type": "{dtype}", "insurance_line": "{lob}"}}'},
                         files={"file": (fname, body.encode(), "text/markdown")})
        assert up.status_code == 202, up.text
        docs.append(up.json())
    return {"tenant": tenant, "code": code, "admin": admin_h, "group_id": gid, "department": dep, "users": users,
            "collection": coll.json(), "docs": docs}


@pytest.fixture(scope="session")
def tenants(client, platform_admin):
    a = _build_tenant(client, platform_admin, "A", "motor")
    b = _build_tenant(client, platform_admin, "B", "health")
    for t in (a, b):
        t["analyst"] = auth(login(client, t["users"]["analyst"]["email"]))
        t["outsider"] = auth(login(client, t["users"]["outsider"]["email"]))
    return {"A": a, "B": b}
