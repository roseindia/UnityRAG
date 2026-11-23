"""API security: error hygiene, injection-safe parameters, cache isolation, rate limiting, headers."""
import uuid


def test_errors_are_consistent_and_leak_no_internals(client, tenants):
    a = tenants["A"]
    r = client.get(f"/api/v1/documents/{uuid.uuid4()}", headers=a["analyst"])
    body = r.json()
    assert r.status_code == 404 and set(body["error"]) == {"code", "message", "correlation_id", "details"}
    r = client.get("/api/v1/documents/not-a-uuid", headers=a["analyst"])
    assert r.status_code == 422 and "Traceback" not in r.text
    assert r.headers["x-correlation-id"] and r.headers["x-content-type-options"] == "nosniff"


def test_sql_injection_payloads_are_inert(client, tenants):
    a = tenants["A"]
    for q in ("' OR 1=1 --", "x'); DROP TABLE content.documents; --", "\\' UNION SELECT * FROM iam.user_accounts --"):
        r = client.post("/api/v1/search", headers=a["analyst"], json={"query": q})
        assert r.status_code == 200
        r = client.get("/api/v1/admin/users", headers=a["admin"], params={"q": q, "sort": q})
        assert r.status_code == 200
    assert client.get("/api/v1/documents", headers=a["analyst"]).json()["total"] > 0


def test_retrieval_cache_never_crosses_tenants_or_permissions(client, tenants):
    a, b = tenants["A"], tenants["B"]
    q = {"query": "waiting period illnesses accidents"}
    rb = client.post("/api/v1/search", headers=b["analyst"], json=q).json()
    assert rb["results"]
    ra = client.post("/api/v1/search", headers=a["analyst"], json=q).json()
    assert not ra["cache_hit"] and all(r["document_id"] not in {x["document_id"] for x in rb["results"]} for r in ra["results"])
    rb2 = client.post("/api/v1/search", headers=b["analyst"], json=q).json()
    assert rb2["cache_hit"] is True
    ro = client.post("/api/v1/search", headers=b["outsider"], json=q).json()      # same tenant, fewer permissions
    assert ro["cache_hit"] is False and ro["results"] == []


def test_rate_limiting_returns_429(client, tenants, monkeypatch):
    from app.core import config

    a = tenants["A"]
    monkeypatch.setattr(config.get_settings(), "rate_limit_per_minute", 3)
    codes = [client.get("/api/v1/auth/me", headers=a["outsider"]).status_code for _ in range(6)]
    assert 429 in codes


def test_platform_and_admin_namespaces_require_auth(client):
    for path in ("/api/v1/platform/tenants", "/api/v1/admin/users", "/api/v1/search/history"):
        assert client.get(path).status_code == 401


def test_openapi_documents_all_admin_namespaces(client):
    spec = client.get("/api/v1/openapi.json").json()
    paths = spec["paths"]
    for p in ("/api/v1/platform/dashboard", "/api/v1/platform/tenants/{tenant_id}/suspend", "/api/v1/admin/dashboard",
              "/api/v1/admin/users", "/api/v1/admin/config", "/api/v1/admin/audit", "/api/v1/chat", "/api/v1/search"):
        assert p in paths, p


def test_streaming_chat_rate_limit_is_a_plain_429(client, tenants, monkeypatch):
    """The limit must be checked before the SSE response starts, so clients get HTTP 429
    with the error envelope rather than a stream that breaks after a 200."""
    from app.core import config

    monkeypatch.setattr(config.get_settings(), "chat_rate_limit_per_minute", 0)
    r = client.post("/api/v1/chat/stream", headers=tenants["A"]["outsider"], json={"message": "excess"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
