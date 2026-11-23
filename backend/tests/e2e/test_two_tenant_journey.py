"""End-to-end multi-tenant journey (prompt section 21, steps 1-15) over HTTP
against the real database; only external LLM calls would be mocked (the local
extractive model is used here)."""
import uuid

from tests.conftest import PASSWORD, auth, login

MOTOR = b"""# Gamma Motor Policy
## Section 3 - Theft
3.1 Theft of the insured vehicle is covered when the vehicle was locked and the keys were secured.
3.2 Theft claims require a police FIR within 48 hours.
"""
HEALTH = b"""# Delta Health Plan
## Section 7 - Maternity
7.1 Maternity expenses are covered after a waiting period of 9 months, up to INR 50,000 per delivery.
"""


def _tenant(client, platform_admin, name, lob, doc):
    code = f"e2e-{lob}-{uuid.uuid4().hex[:5]}"
    t = client.post("/api/v1/platform/tenants", headers=platform_admin, json={            # step 1
        "code": code, "name": name, "plan_code": "starter", "admin_email": f"admin@{code}.test",
        "admin_password": PASSWORD}).json()
    adm = auth(login(client, f"admin@{code}.test"))
    role = client.post("/api/v1/admin/roles", headers=adm, json={                            # step 3
        "code": f"{lob}_handler", "name": f"{lob} handler",
        "permissions": ["documents.read", "collections.read", "search.use", "chat.use", "feedback.submit"]}).json()
    user = client.post("/api/v1/admin/users", headers=adm, json={                            # step 2
        "email": f"user@{code}.test", "display_name": "Handler", "password": PASSWORD, "roles": [role["code"]],
        "lines_of_business": [lob]}).json()
    coll = client.post("/api/v1/admin/collections", headers=adm, json={
        "code": "kb", "name": "Knowledge base", "line_of_business": lob,
        "access": [{"principal_type": "role", "principal_id": role["role_id"]}]}).json()
    up = client.post("/api/v1/documents", headers=adm, data={"collection_id": coll["collection_id"]},  # step 4-7
                     files={"file": (f"{lob}.md", doc, "text/markdown")}).json()
    job = client.get(f"/api/v1/ingestion/jobs/{up['job_id']}", headers=adm).json()
    assert job["status"] == "succeeded" and job["stats"]["chunks"] >= 1
    return {"tenant": t, "admin": adm, "user": auth(login(client, f"user@{code}.test")), "doc": up, "user_id": user["user_id"]}


def test_two_tenant_end_to_end(client, platform_admin):
    g = _tenant(client, platform_admin, "Gamma Motor", "motor", MOTOR)
    d = _tenant(client, platform_admin, "Delta Health", "health", HEALTH)
    for t, q, own, other in ((g, "theft of locked vehicle", "Gamma", "Delta"), (d, "maternity waiting period", "Delta", "Gamma")):
        for mode in ("vector", "fulltext", "hybrid"):                                         # steps 8-10
            res = client.post("/api/v1/search", headers=t["user"], json={"query": q, "mode": mode}).json()["results"]
            assert res and all(own in r["title"] for r in res), (mode, res)
        # cross-tenant probes find nothing
        cross = "maternity waiting period" if own == "Gamma" else "theft of locked vehicle"
        assert all(other not in r["title"] for r in client.post("/api/v1/search", headers=t["user"],
                                                               json={"query": cross}).json()["results"])
        chat = client.post("/api/v1/chat", headers=t["user"], json={"message": f"What does the policy say about {q}?"}).json()  # step 11
        assert chat["status"] in ("answered", "needs_review") and chat["citations"]                # step 12
        assert all(c["verified"] and own in c["title"] for c in chat["citations"])                 # step 13
    from app.analytics.aggregation import aggregate_all

    aggregate_all(0)
    for t in (g, d):                                                                              # step 14
        dash = client.get("/api/v1/admin/dashboard", headers=t["admin"]).json()["totals"]
        assert dash["total_documents"] == 1 and dash["searches"] >= 4 and dash["chats"] >= 1
        ev = client.get("/api/v1/admin/audit", headers=t["admin"]).json()                         # step 15
        cats = {e["category"] for e in ev["items"]}
        assert {"search", "answer", "ingestion", "document_update"} <= cats
        assert all(e["category"] for e in ev["items"])
        assert client.get("/api/v1/admin/audit/verify", headers=t["admin"]).json()["ok"]
    # each tenant's audit never contains the other tenant's resources
    g_doc = str(g["doc"]["document_id"])
    d_events = client.get("/api/v1/admin/audit?limit=500", headers=d["admin"]).json()["items"]
    assert g_doc not in str(d_events)
