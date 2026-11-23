"""Tenant Admin and Platform Admin consoles, quotas, analytics, evaluation,
audit, break-glass (extension 5-11, 14)."""
from __future__ import annotations

import uuid

from tests.conftest import PASSWORD, auth, login


# ---------------------------------------------------------------- tenant admin
def test_tenant_dashboard_uses_real_data(client, tenants):
    from app.analytics.aggregation import aggregate_all

    a = tenants["A"]
    client.post("/api/v1/search", headers=a["analyst"], json={"query": "excess"})
    assert aggregate_all(0) >= 2
    d = client.get("/api/v1/admin/dashboard", headers=a["admin"]).json()
    t = d["totals"]
    assert t["total_documents"] >= 2 and t["total_users"] >= 3 and t["total_collections"] >= 1
    assert t["searches"] >= 1 and t["total_chunks"] > 0 and d["series"]
    assert {q["metric"] for q in d["quotas"]} >= {"users", "documents", "storage_bytes", "ai_tokens"}
    assert "Estimated" in d["cost_note"]


def test_analytics_usage_and_reports(client, tenants):
    a = tenants["A"]
    client.post("/api/v1/chat", headers=a["analyst"], json={"message": "What excess applies to own damage claims?"})
    an = client.get("/api/v1/admin/analytics", headers=a["admin"]).json()
    assert an["search"]["summary"]["searches"] >= 1 and an["chat"]["by_status"]
    us = client.get("/api/v1/admin/usage", headers=a["admin"]).json()
    assert any(m["purpose"] == "chat" for m in us["by_model"])
    for name in ("document_inventory", "user_activity", "token_consumption", "citation_coverage", "feedback"):
        r = client.get(f"/api/v1/admin/reports/{name}.csv", headers=a["admin"])
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv"), name
    assert "Alpha Motor" in client.get("/api/v1/admin/reports/document_inventory.csv", headers=a["admin"]).text


def test_user_admin_lifecycle_and_session_revocation(client, tenants):
    a = tenants["A"]
    email = f"temp-{uuid.uuid4().hex[:6]}@a.test"
    u = client.post("/api/v1/admin/users", headers=a["admin"],
                    json={"email": email, "display_name": "Temp", "password": PASSWORD, "roles": ["member"]}).json()
    h = auth(login(client, email))
    assert client.get("/api/v1/auth/me", headers=h).status_code == 200
    upd = client.put(f"/api/v1/admin/users/{u['user_id']}", headers=a["admin"], json={"clearance_rank": 0})
    assert upd.json()["clearance_rank"] == 0
    r = client.post(f"/api/v1/admin/users/{u['user_id']}/deactivate", headers=a["admin"])
    assert r.json()["status"] == "inactive"
    assert client.get("/api/v1/auth/me", headers=h).status_code in (401, 403)
    assert client.post(f"/api/v1/admin/users/{u['user_id']}/activate", headers=a["admin"]).json()["status"] == "active"
    assert client.get(f"/api/v1/admin/users/{u['user_id']}/logins", headers=a["admin"]).json()
    users = client.get("/api/v1/admin/users?q=temp", headers=a["admin"]).json()
    assert users["total"] >= 1


def test_roles_permissions_and_system_role_protection(client, tenants):
    a = tenants["A"]
    roles = client.get("/api/v1/admin/roles", headers=a["admin"]).json()
    system = next(r for r in roles if r["code"] == "tenant_admin")
    assert client.put(f"/api/v1/admin/roles/{system['role_id']}", headers=a["admin"], json={"name": "x"}).status_code == 403
    r = client.post("/api/v1/admin/roles", headers=a["admin"], json={"code": "claims_reviewer", "name": "Claims Reviewer",
                                                                    "permissions": ["documents.read", "search.use", "feedback.review"]})
    assert r.status_code == 201
    bad = client.post("/api/v1/admin/roles", headers=a["admin"], json={"code": "bad_role", "name": "Bad", "permissions": ["root.all"]})
    assert bad.status_code == 422
    uid = a["users"]["outsider"]["user_id"]
    assert client.post(f"/api/v1/admin/users/{uid}/roles", headers=a["admin"], json={"role_code": "claims_reviewer"}).status_code == 200
    eff = client.get(f"/api/v1/admin/permissions/effective/{uid}", headers=a["admin"]).json()["permissions"]
    assert "feedback.review" in eff
    # segregation of duties: auditor + tenant_admin is refused
    aud = next(r for r in roles if r["code"] == "auditor")
    admin_user = client.get("/api/v1/auth/me", headers=a["admin"]).json()["user_id"]
    r = client.post(f"/api/v1/admin/users/{admin_user}/roles", headers=a["admin"], json={"role_id": aud["role_id"]})
    assert r.status_code == 409  # check_violation from the SoD trigger


def test_members_cannot_use_admin_apis_and_denials_are_audited(client, tenants):
    a = tenants["A"]
    for path in ("/api/v1/admin/users", "/api/v1/admin/dashboard", "/api/v1/admin/audit", "/api/v1/admin/config"):
        assert client.get(path, headers=a["analyst"]).status_code == 403, path
    ev = client.get("/api/v1/admin/audit?category=authorization&outcome=denied", headers=a["admin"]).json()
    assert ev["total"] >= 1


def test_tenant_admin_cannot_use_platform_apis(client, tenants):
    a = tenants["A"]
    for path in ("/api/v1/platform/dashboard", "/api/v1/platform/tenants", "/api/v1/platform/monitoring"):
        assert client.get(path, headers=a["admin"]).status_code == 403, path


def test_departments_teams_groups(client, tenants):
    a = tenants["A"]
    d = client.post("/api/v1/admin/departments", headers=a["admin"], json={"code": "UW", "name": "Underwriting"}).json()
    t = client.post("/api/v1/admin/teams", headers=a["admin"], json={"department_id": d["department_id"], "name": "Motor UW"})
    assert t.status_code == 201
    assert client.post(f"/api/v1/admin/teams/{t.json()['team_id']}/members", headers=a["admin"],
                       json={"user_id": a["users"]["outsider"]["user_id"]}).status_code == 200
    assert any(x["code"] == "UW" for x in client.get("/api/v1/admin/departments", headers=a["admin"]).json())
    assert client.get(f"/api/v1/admin/departments/{d['department_id']}/usage", headers=a["admin"]).status_code == 200
    groups = client.get("/api/v1/admin/groups", headers=a["admin"]).json()
    assert groups[0]["member_count"] >= 1


def test_collections_admin_and_stats(client, tenants):
    a = tenants["A"]
    c = client.post("/api/v1/admin/collections", headers=a["admin"], json={"code": "empty-coll", "name": "Empty"}).json()
    assert client.get(f"/api/v1/admin/collections/{c['collection_id']}/stats", headers=a["admin"]).json()["documents"] == 0
    assert client.put(f"/api/v1/admin/collections/{c['collection_id']}", headers=a["admin"],
                      json={"description": "x"}).json()["description"] == "x"
    assert client.delete(f"/api/v1/admin/collections/{c['collection_id']}", headers=a["admin"]).status_code == 200
    full = a["collection"]["collection_id"]
    assert client.delete(f"/api/v1/admin/collections/{full}", headers=a["admin"]).status_code == 409


def test_ai_and_rag_configuration_versioning(client, tenants, platform_admin):
    a = tenants["A"]
    cfg = client.get("/api/v1/admin/config", headers=a["admin"]).json()
    v = cfg["rag"]["version"]
    r = client.put("/api/v1/admin/config/rag", headers=a["admin"], json={"vector_top_k": 25, "rrf_k": 50, "reason": "tuning"})
    assert r.status_code == 200 and r.json()["version"] == v + 1
    assert client.put("/api/v1/admin/config/rag", headers=a["admin"], json={"chunk_size": 100, "chunk_overlap": 200}).status_code == 422
    r = client.put("/api/v1/admin/config/ai", headers=a["admin"], json={"chat_model": "gpt-unapproved"})
    assert r.status_code == 422
    r = client.put("/api/v1/admin/config/ai", headers=a["admin"], json={"embedding_dimensions": 3072})
    assert r.status_code == 422  # no vector index for that dimension / model mismatch
    hist = client.get("/api/v1/admin/config/history/rag", headers=a["admin"]).json()
    assert len(hist) >= 2
    rb = client.post(f"/api/v1/admin/config/rollback/rag/{v}", headers=a["admin"])
    assert rb.status_code == 200 and rb.json()["vector_top_k"] == cfg["rag"]["vector_top_k"]
    # platform restricts what tenant admins may change
    tid = a["tenant"]["tenant_id"]
    from sqlalchemy import text

    from app.database.session import SecurityContext, scoped_session

    with scoped_session(SecurityContext(access_mode="platform", platform_role="platform_super_admin")) as db:
        db.execute(text("UPDATE platform.tenant_settings SET tenant_overridable_ai_settings = '{temperature}' WHERE tenant_id = :t"),
                   {"t": tid})
    try:
        r = client.put("/api/v1/admin/config/rag", headers=a["admin"], json={"rrf_k": 70})
        assert r.status_code == 403 and r.json()["error"]["code"] == "setting_not_overridable"
    finally:
        with scoped_session(SecurityContext(access_mode="platform", platform_role="platform_super_admin")) as db:
            db.execute(text("UPDATE platform.tenant_settings SET tenant_overridable_ai_settings = DEFAULT WHERE tenant_id = :t"),
                       {"t": tid})


def test_feedback_review_queue(client, tenants):
    a = tenants["A"]
    client.post("/api/v1/feedback", headers=a["analyst"], json={"category": "missing_source", "comment": "need hail guidance"})
    q = client.get("/api/v1/admin/feedback?status=new", headers=a["admin"]).json()
    assert q["total"] >= 1
    fid = q["items"][0]["feedback_id"]
    r = client.put(f"/api/v1/admin/feedback/{fid}", headers=a["admin"], json={"status": "resolved", "resolution": "added doc"})
    assert r.json()["status"] == "resolved" and r.json()["resolved_at"]


def test_audit_chain_is_tamper_evident(client, tenants):
    a = tenants["A"]
    v = client.get("/api/v1/admin/audit/verify", headers=a["admin"]).json()
    assert v["ok"] is True and v["checked"] > 10
    assert client.get("/api/v1/admin/audit/export.csv", headers=a["admin"]).status_code == 200


def test_evaluation_dataset_run_and_gates(client, tenants):
    a = tenants["A"]
    ds = client.post("/api/v1/admin/evaluation/datasets", headers=a["admin"], json={"name": "motor-golden"}).json()
    doc = a["docs"][0]["document_id"]
    qs = [{"question": "flood damage vehicle basement exclusion", "expected_document_ids": [doc]},
          {"question": "standard excess own damage claim", "expected_document_ids": [doc]},
          {"question": "what is the capital of mars", "answerable": False}]
    assert client.post(f"/api/v1/admin/evaluation/datasets/{ds['dataset_id']}/questions", headers=a["admin"], json=qs).json()["added"] == 3
    # the admin is also in the collection's group? use end_to_end + retrieval runs as the admin persona
    client.post(f"/api/v1/admin/groups/{a['group_id']}/members", headers=a["admin"],
                json={"user_id": client.get("/api/v1/auth/me", headers=a["admin"]).json()["user_id"]})
    run = client.post(f"/api/v1/admin/evaluation/datasets/{ds['dataset_id']}/runs", headers=a["admin"],
                      json={"mode": "end_to_end", "k": 5})
    assert run.status_code == 201, run.text
    s = run.json()["summary"]
    assert s["recall_at_k"] == 1.0 and s["mrr"] > 0 and "abstention_accuracy" in s
    assert run.json()["config_snapshot"]["rag_config"]
    assert client.get("/api/v1/admin/evaluation/runs", headers=a["admin"]).json()


# ---------------------------------------------------------------- quotas
def test_quota_enforcement_rejects_and_records(client, tenants, platform_admin):
    b = tenants["B"]
    tid = b["tenant"]["tenant_id"]
    cur = client.get(f"/api/v1/platform/tenants/{tid}", headers=platform_admin).json()
    used = next(q for q in cur["quotas"] if q["metric"] == "documents")["used"]
    r = client.put(f"/api/v1/platform/tenants/{tid}/quotas", headers=platform_admin,
                   json={"max_documents": used, "reason": "quota test"})
    assert r.status_code == 200
    try:
        up = client.post("/api/v1/documents", headers=b["admin"], data={"collection_id": b["collection"]["collection_id"]},
                         files={"file": ("over.md", b"# Over quota\nThis upload must be rejected by the quota.", "text/markdown")})
        assert up.status_code == 429 and up.json()["error"]["code"] == "quota_exceeded"
        ev = client.get("/api/v1/admin/audit?category=administration", headers=b["admin"]).json()["items"]
        assert any(e["event_type"] == "quota_exceeded" for e in ev)
    finally:
        client.put(f"/api/v1/platform/tenants/{tid}/quotas", headers=platform_admin, json={"max_documents": 100000})


def test_ai_request_quota(client, tenants, platform_admin):
    b = tenants["B"]
    tid = b["tenant"]["tenant_id"]
    client.put(f"/api/v1/platform/tenants/{tid}/quotas", headers=platform_admin, json={"monthly_ai_requests": 0})
    try:
        r = client.post("/api/v1/chat", headers=b["analyst"], json={"message": "waiting period for illnesses?"})
        assert r.status_code == 429
    finally:
        client.put(f"/api/v1/platform/tenants/{tid}/quotas", headers=platform_admin, json={"monthly_ai_requests": 200000})


# ---------------------------------------------------------------- platform admin
def test_platform_dashboard_tenants_and_details(client, tenants, platform_admin):
    from app.analytics.aggregation import aggregate_all

    aggregate_all(0)
    d = client.get("/api/v1/platform/dashboard", headers=platform_admin).json()
    assert d["tenants"]["total"] >= 2 and d["content"]["documents"] >= 3 and d["users"]["total_accounts"] >= 5
    assert d["health"]["database"]["status"] == "up" and d["top_tenants"]
    lst = client.get("/api/v1/platform/tenants?sort=documents", headers=platform_admin).json()
    assert lst["total"] >= 2
    tid = tenants["A"]["tenant"]["tenant_id"]
    det = client.get(f"/api/v1/platform/tenants/{tid}", headers=platform_admin).json()
    assert det["administrators"] and det["quotas"] and det["subscriptions"]
    assert client.get(f"/api/v1/platform/tenants/{tid}/usage", headers=platform_admin).json()["series"]
    assert client.get("/api/v1/platform/analytics", headers=platform_admin).json()["tenants"]
    mon = client.get("/api/v1/platform/monitoring", headers=platform_admin).json()
    assert mon["health"]["redis"]["status"] in ("up", "down")
    assert client.get("/api/v1/platform/jobs", headers=platform_admin).json()["tenants"]


def test_tenant_lifecycle_requires_confirmation_and_reason(client, platform_admin):
    r = client.post("/api/v1/platform/tenants", headers=platform_admin, json={"code": f"life-{uuid.uuid4().hex[:6]}",
                                                                              "name": "Lifecycle Co", "plan_code": "trial"})
    tid = r.json()["tenant_id"]
    assert r.json()["status"] == "trial"
    assert client.post(f"/api/v1/platform/tenants/{tid}/suspend", headers=platform_admin,
                       json={"reason": "short", "confirm": True}).status_code == 422
    assert client.post(f"/api/v1/platform/tenants/{tid}/suspend", headers=platform_admin,
                       json={"reason": "a valid reason here", "confirm": False}).status_code == 422
    for action, status in (("suspend", "suspended"), ("deactivate", "deactivated"), ("archive", "archived")):
        res = client.post(f"/api/v1/platform/tenants/{tid}/{action}", headers=platform_admin,
                          json={"reason": f"lifecycle test {action}", "confirm": True})
        assert res.status_code == 200 and res.json()["status"] == status
    assert client.post(f"/api/v1/platform/tenants/{tid}/suspend", headers=platform_admin,
                       json={"reason": "cannot suspend archived", "confirm": True}).status_code == 409
    audit = client.get(f"/api/v1/platform/tenants/{tid}/audit", headers=platform_admin).json()["items"]
    assert {e["action"] for e in audit} >= {"tenant_created", "tenant_suspend", "tenant_archive"}


def test_plans_features_subscription_and_tenant_admins(client, tenants, platform_admin):
    tid = tenants["B"]["tenant"]["tenant_id"]
    assert len(client.get("/api/v1/platform/plans", headers=platform_admin).json()) >= 4
    assert client.put(f"/api/v1/platform/tenants/{tid}/features", headers=platform_admin,
                      json={"flag": "beta.answer_summaries", "enabled": True}).json()["beta.answer_summaries"] is True
    r = client.put(f"/api/v1/platform/tenants/{tid}/subscription", headers=platform_admin,
                   json={"plan_code": "enterprise", "apply_quotas": True})
    assert r.json()["plan_code"] == "enterprise"
    email = f"admin2-{uuid.uuid4().hex[:6]}@b.test"
    r = client.post(f"/api/v1/platform/tenants/{tid}/admins", headers=platform_admin,
                    json={"email": email, "display_name": "Second Admin", "password": PASSWORD})
    assert r.status_code == 201 and "tenant_admin" in r.json()["roles"]
    assert any(x["email"] == email for x in client.get(f"/api/v1/platform/tenants/{tid}/admins", headers=platform_admin).json())


def test_ai_providers_secrets_masked_and_model_catalogue(client, platform_admin):
    r = client.post("/api/v1/platform/ai-providers", headers=platform_admin, json={
        "code": f"oai-{uuid.uuid4().hex[:4]}", "name": "OpenAI", "provider_type": "openai",
        "base_url": "https://api.openai.com/v1", "api_key": "sk-test-1234567890abcd"})
    assert r.status_code == 201
    p = r.json()
    assert p["api_key_masked"] == "****abcd" and "sk-test" not in str(p)
    m = client.post("/api/v1/platform/models", headers=platform_admin, json={
        "provider_id": p["provider_id"], "model_name": "text-embedding-3-small", "purpose": "embedding", "dimensions": 1536,
        "input_cost_per_1k": 0.00002}).json()
    assert m["status"] == "proposed"
    ok = client.put(f"/api/v1/platform/models/{m['model_id']}", headers=platform_admin, json={"status": "approved"}).json()
    assert ok["status"] == "approved" and ok["approved_by"]
    assert any(x["model_name"] == "text-embedding-3-small" for x in client.get("/api/v1/platform/models", headers=platform_admin).json())


def test_platform_users_and_rbac(client, platform_admin):
    email = f"ops-{uuid.uuid4().hex[:6]}@platform.test"
    r = client.put("/api/v1/platform/users", headers=platform_admin,
                   json={"email": email, "role": "platform_operator", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["role"] == "platform_operator"
    ops = auth(login(client, email))
    assert client.get("/api/v1/platform/monitoring", headers=ops).status_code == 200
    assert client.post("/api/v1/platform/tenants", headers=ops, json={"code": "nope-x", "name": "Nope"}).status_code == 403
    assert client.get("/api/v1/platform/users", headers=ops).status_code == 403


def test_break_glass_is_time_limited_scoped_and_audited(client, tenants, platform_admin):
    a = tenants["A"]
    tid = a["tenant"]["tenant_id"]
    assert client.post("/api/v1/platform/break-glass", headers=platform_admin,
                       json={"tenant_id": tid, "reason": "too short", "confirm": True}).status_code == 422
    g = client.post("/api/v1/platform/break-glass", headers=platform_admin,
                    json={"tenant_id": tid, "reason": "Support ticket INC-4411: ingestion output check", "minutes": 15,
                          "confirm": True})
    assert g.status_code == 201, g.text
    gid = g.json()["grant_id"]
    docs = client.get(f"/api/v1/platform/break-glass/{gid}/documents", headers=platform_admin).json()
    assert docs["data"] and docs["tenant_id"] == tid
    one = client.get(f"/api/v1/platform/break-glass/{gid}/document?resource_id={a['docs'][0]['document_id']}",
                     headers=platform_admin).json()
    assert one["data"]
    conv = client.get(f"/api/v1/platform/break-glass/{gid}/conversation?resource_id={uuid.uuid4()}", headers=platform_admin)
    assert conv.status_code == 403  # scope excludes conversations
    assert client.post(f"/api/v1/platform/break-glass/{gid}/close", headers=platform_admin).status_code == 200
    assert client.get(f"/api/v1/platform/break-glass/{gid}/documents", headers=platform_admin).status_code == 403
    sec = client.get("/api/v1/platform/security-events", headers=platform_admin).json()["items"]
    actions = {e.get("action") for e in sec}
    assert {"break_glass_opened", "break_glass_access", "break_glass_closed"} <= actions
    ten = client.get("/api/v1/admin/audit?category=administration", headers=a["admin"]).json()["items"]
    assert any(e["event_type"] == "break_glass_access" for e in ten)


def test_platform_admin_without_grant_sees_no_tenant_content(client, tenants, platform_admin):
    # platform APIs expose aggregates only; there is no content endpoint outside break-glass
    d = client.get("/api/v1/platform/dashboard", headers=platform_admin).json()
    assert "Alpha Motor" not in str(d)
