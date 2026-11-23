"""Background workers: retries, dead-letter, tenant context, heartbeats, requeue."""
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.database.session import SecurityContext, scoped_session


def _job(tenant_id, job_id):
    with scoped_session(SecurityContext.worker(uuid.UUID(str(tenant_id))), role="worker") as db:
        return dict(db.execute(text("SELECT * FROM ingest.ingestion_jobs WHERE job_id = :j"), {"j": job_id}).mappings().one())


def test_transient_failure_retries_then_dead_letters(client, tenants, monkeypatch):
    from app.rag.ingestion import pipeline

    a = tenants["A"]
    tid = a["tenant"]["tenant_id"]
    up = client.post("/api/v1/documents", headers=a["admin"], data={"collection_id": a["collection"]["collection_id"]},
                     files={"file": ("transient.md", b"# Transient\nEmbedding outage simulation content here.", "text/markdown")})
    job_id = up.json()["job_id"]
    assert _job(tid, job_id)["status"] == "succeeded"
    # now simulate a provider outage on reprocess
    calls = {"n": 0}

    def boom(*a_, **k):
        calls["n"] += 1
        raise httpx.ConnectError("provider down")

    monkeypatch.setattr(pipeline, "build_embeddings", lambda *a_, **k: type("E", (), {"embed_documents": boom})())
    r = client.post(f"/api/v1/admin/documents/{up.json()['document_id']}/reprocess", headers=a["admin"])
    rj = r.json()["job_id"]
    job = _job(tid, rj)
    assert job["status"] in ("retrying", "dead_letter") and job["error_code"] == "ConnectError" and calls["n"] >= 1
    with scoped_session(SecurityContext.worker(uuid.UUID(str(tid))), role="worker") as db:
        db.execute(text("UPDATE ingest.ingestion_jobs SET attempt = max_attempts - 1, status = 'retrying' WHERE job_id = :j"),
                   {"j": rj})
    with pytest.raises(httpx.ConnectError):
        pipeline.run_job(uuid.UUID(str(tid)), uuid.UUID(str(rj)))
    assert _job(tid, rj)["status"] == "dead_letter"
    # the previously published version stays searchable (no partial replacement)
    assert client.post("/api/v1/search", headers=a["analyst"], json={"query": "embedding outage simulation"}).json()["results"]
    monkeypatch.undo()
    rr = client.post(f"/api/v1/admin/ingestion/jobs/{rj}/retry", headers=a["admin"])
    assert rr.status_code == 202 and _job(tid, rj)["status"] == "succeeded"


def test_permanent_failure_and_monitoring_summary(client, tenants):
    a = tenants["A"]
    up = client.post("/api/v1/documents", headers=a["admin"], data={"collection_id": a["collection"]["collection_id"]},
                     files={"file": ("empty.txt", b"   \n  \n", "text/plain")})
    job = client.get(f"/api/v1/ingestion/jobs/{up.json()['job_id']}", headers=a["admin"]).json()
    assert job["status"] == "failed" and job["error_code"] == "no_text"
    s = client.get("/api/v1/admin/ingestion/summary", headers=a["admin"]).json()
    assert s["by_status"].get("failed", 0) >= 1
    jobs = client.get("/api/v1/admin/ingestion/jobs?status=failed", headers=a["admin"]).json()
    assert jobs["total"] >= 1


def test_job_idempotent_replay(client, tenants):
    from app.rag.ingestion.pipeline import run_job

    a = tenants["A"]
    j = a["docs"][0]["job_id"]
    out = run_job(uuid.UUID(str(a["tenant"]["tenant_id"])), uuid.UUID(str(j)))
    assert out.status == "succeeded"   # already done -> no duplicate processing


def test_requeue_and_heartbeat_tasks(client, tenants):
    from app.workers.tasks import heartbeat, requeue_due_jobs

    assert heartbeat() and isinstance(requeue_due_jobs(), int)
    with scoped_session(SecurityContext(access_mode="platform", platform_role="platform_super_admin")) as db:
        assert db.execute(text("SELECT count(*) FROM ops.worker_heartbeats")).scalar() >= 1
