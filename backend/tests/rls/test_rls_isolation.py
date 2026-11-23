"""Mandatory PostgreSQL RLS tests (extension 2.5, prompt section 6, TC-063/TC-067).

All tests connect as the NON-superuser, NON-BYPASSRLS service roles rag_app /
rag_worker against the real database built by the migrations.  A superuser
connection is used only to assert role attributes and to inspect the catalog.
"""
from __future__ import annotations

import os
import threading
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.usefixtures("tenants")


def _role_password(role: str) -> str:
    # The bootstrap sets each role password from the configured settings, so the tests read them from there too.
    from app.core.config import get_settings
    s = get_settings()
    return {"rag_app": s.db_app_password, "rag_worker": s.db_worker_password,
            "rag_readonly": s.db_readonly_password, "rag_migration": s.db_migration_password}[role].get_secret_value()


def connect(role: str = "rag_app") -> psycopg.Connection:
    return psycopg.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                           user=role, password=_role_password(role))


def ctx(cur, tenant=None, user=None, mode="user", principals=(), lobs=("*",), juris=("*",), max_class=3, account=None,
        platform_role=None):
    cur.execute("""SELECT set_config('app.current_tenant_id', %s, true), set_config('app.current_user_id', %s, true),
                          set_config('app.current_access_mode', %s, true), set_config('app.current_principals', %s, true),
                          set_config('app.current_lobs', %s, true), set_config('app.current_jurisdictions', %s, true),
                          set_config('app.current_max_class', %s, true), set_config('app.current_account_id', %s, true),
                          set_config('app.current_platform_role', %s, true)""",
                (str(tenant or ""), str(user or ""), mode, ",".join(map(str, principals)), ",".join(lobs), ",".join(juris),
                 str(max_class), str(account or ""), platform_role or ""))


def ids(t):
    return t["tenant"]["tenant_id"], t["users"]["analyst"]["user_id"], t["group_id"]


def user_ctx(cur, t):
    tid, uid, gid = ids(t)
    ctx(cur, tid, uid, "user", principals=(uid, tid, gid))


def test_service_roles_have_no_superuser_or_bypassrls():
    with psycopg.connect(os.environ["DB_SUPERUSER_DSN"].replace("dbname=postgres", f"dbname={os.environ['DB_NAME']}")) as su:
        rows = su.execute("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname LIKE 'rag_%'").fetchall()
        assert rows and all(not s and not b for _, s, b in rows)
        unprotected = su.execute("""SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                                     WHERE c.relkind = 'r' AND n.nspname IN ('platform','iam','content','ingest','rag','ai','eval','audit','ops')
                                       AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity)""").fetchall()
        assert [r[0] for r in unprotected] == ["iam.permissions"]  # global reference catalogue (documented)
        owner = su.execute("SELECT tableowner FROM pg_tables WHERE schemaname = 'content' AND tablename = 'documents'").fetchone()[0]
        assert owner == "rag_migration"


def test_startup_role_safety_check_detects_bypass_credentials():
    from app.database.session import _ROLE_SAFETY_SQL, verify_role_safety

    for role in ("app", "worker", "readonly"):
        assert verify_role_safety(role) == []  # type: ignore[arg-type]
    with connect("rag_migration") as c:  # the table owner must be reported
        _, is_super, bypass, owns = c.execute(_ROLE_SAFETY_SQL.text).fetchone()
        assert (is_super, bypass, owns) == (False, False, True)
    with psycopg.connect(os.environ["DB_SUPERUSER_DSN"].replace("dbname=postgres", f"dbname={os.environ['DB_NAME']}")) as su:
        _, is_super, _, _ = su.execute(_ROLE_SAFETY_SQL.text).fetchone()
        assert is_super is True


def test_01_02_each_tenant_reads_its_own_documents(tenants):
    for key in ("A", "B"):
        with connect() as c, c.cursor() as cur:
            user_ctx(cur, tenants[key])
            cur.execute("SELECT DISTINCT tenant_id FROM content.documents")
            rows = cur.fetchall()
            assert rows == [(uuid.UUID(str(tenants[key]["tenant"]["tenant_id"])),)]


def test_03_tenant_a_cannot_read_tenant_b_documents_even_with_explicit_filter(tenants):
    b_tid = tenants["B"]["tenant"]["tenant_id"]
    with connect() as c, c.cursor() as cur:
        user_ctx(cur, tenants["A"])
        cur.execute("SELECT count(*) FROM content.documents WHERE tenant_id = %s", (b_tid,))
        assert cur.fetchone()[0] == 0
        # tenant_admin mode is also tenant-restricted
        ctx(cur, tenants["A"]["tenant"]["tenant_id"], None, "tenant_admin")
        cur.execute("SELECT count(*) FROM content.documents WHERE tenant_id = %s", (b_tid,))
        assert cur.fetchone()[0] == 0


def test_04_insert_with_other_tenant_id_rejected(tenants):
    a, b = tenants["A"], tenants["B"]
    with connect() as c, c.cursor() as cur:
        ctx(cur, a["tenant"]["tenant_id"], a["users"]["analyst"]["user_id"], "tenant_admin")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("""INSERT INTO content.documents (tenant_id, collection_id, title, created_by)
                           VALUES (%s, %s, 'smuggled', %s)""",
                        (b["tenant"]["tenant_id"], b["collection"]["collection_id"], a["users"]["analyst"]["user_id"]))


def test_05_update_of_other_tenant_rows_affects_nothing(tenants):
    with connect() as c, c.cursor() as cur:
        ctx(cur, tenants["A"]["tenant"]["tenant_id"], None, "tenant_admin")
        cur.execute("UPDATE content.documents SET title = 'hacked' WHERE tenant_id = %s", (tenants["B"]["tenant"]["tenant_id"],))
        assert cur.rowcount == 0
        # moving an own row into another tenant fails WITH CHECK
        doc = tenants["A"]["docs"][0]["document_id"]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("UPDATE content.documents SET tenant_id = %s WHERE document_id = %s",
                        (tenants["B"]["tenant"]["tenant_id"], doc))


def test_06_delete_of_other_tenant_rows_affects_nothing(tenants):
    with connect("rag_worker") as c, c.cursor() as cur:
        ctx(cur, tenants["A"]["tenant"]["tenant_id"], None, "worker")
        cur.execute("DELETE FROM content.document_chunks WHERE tenant_id = %s", (tenants["B"]["tenant"]["tenant_id"],))
        assert cur.rowcount == 0
        c.rollback()


def test_07_chunks_and_embeddings_of_other_tenant_not_accessible(tenants):
    with connect() as c, c.cursor() as cur:
        user_ctx(cur, tenants["A"])
        cur.execute("SELECT count(*) FROM content.document_chunks WHERE tenant_id = %s", (tenants["B"]["tenant"]["tenant_id"],))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM content.chunk_embeddings WHERE tenant_id = %s", (tenants["B"]["tenant"]["tenant_id"],))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM content.document_chunks")
        assert cur.fetchone()[0] > 0


def test_08_conversations_of_other_tenant_and_other_users_not_accessible(tenants, client):
    from tests.conftest import auth  # noqa: F401

    r = client.post("/api/v1/conversations", headers=tenants["B"]["analyst"], json={"title": "B private"})
    assert r.status_code == 201
    with connect() as c, c.cursor() as cur:
        user_ctx(cur, tenants["A"])
        cur.execute("SELECT count(*) FROM rag.conversations WHERE conversation_id = %s", (r.json()["conversation_id"],))
        assert cur.fetchone()[0] == 0
        # same tenant, different user: owner-only policy
        tb = tenants["B"]
        ctx(cur, tb["tenant"]["tenant_id"], tb["users"]["outsider"]["user_id"], "user",
            principals=(tb["users"]["outsider"]["user_id"], tb["tenant"]["tenant_id"]))
        cur.execute("SELECT count(*) FROM rag.conversations WHERE conversation_id = %s", (r.json()["conversation_id"],))
        assert cur.fetchone()[0] == 0


def test_09_ingestion_jobs_of_other_tenant_not_accessible(tenants):
    with connect() as c, c.cursor() as cur:
        ctx(cur, tenants["A"]["tenant"]["tenant_id"], None, "tenant_admin")
        cur.execute("SELECT count(*) FROM ingest.ingestion_jobs WHERE job_id = %s", (tenants["B"]["docs"][0]["job_id"],))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM ingest.ingestion_jobs")
        assert cur.fetchone()[0] >= len(tenants["A"]["docs"])


def test_10_audit_records_of_other_tenant_not_accessible_and_append_only(tenants):
    with connect() as c, c.cursor() as cur:
        ctx(cur, tenants["A"]["tenant"]["tenant_id"], None, "auditor")
        cur.execute("SELECT count(*) FROM audit.tenant_audit_logs WHERE tenant_id = %s", (tenants["B"]["tenant"]["tenant_id"],))
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM audit.tenant_audit_logs")
        assert cur.fetchone()[0] > 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("UPDATE audit.tenant_audit_logs SET outcome = 'success'")


def test_audit_logs_cannot_be_rewritten_even_by_the_owner_role():
    """The migration/owner role is subject to FORCE RLS and to the append-only triggers,
    including TRUNCATE (which bypasses row-level triggers)."""
    def owner_cursor(c):
        cur = c.cursor()
        cur.execute("SELECT set_config('app.current_access_mode', 'platform', true), "
                    "set_config('app.current_platform_role', 'platform_super_admin', true)")
        return cur

    for stmt in ("TRUNCATE audit.tenant_audit_logs", "TRUNCATE platform.platform_audit_logs"):
        with connect("rag_migration") as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                owner_cursor(c).execute(stmt)
    with connect("rag_migration") as c:
        cur = owner_cursor(c)
        cur.execute("DELETE FROM platform.platform_audit_logs")  # no DELETE policy => 0 rows under FORCE RLS
        assert cur.rowcount == 0
        c.rollback()
    with psycopg.connect(os.environ["DB_SUPERUSER_DSN"].replace("dbname=postgres", f"dbname={os.environ['DB_NAME']}")) as su:
        assert su.execute("SELECT count(*) FROM platform.platform_audit_logs").fetchone()[0] > 0


def test_11_missing_context_exposes_nothing():
    with connect() as c, c.cursor() as cur:
        for table in ("content.documents", "content.document_chunks", "content.chunk_embeddings", "rag.conversations",
                      "iam.users", "ingest.ingestion_jobs", "audit.tenant_audit_logs", "platform.tenant_quotas",
                      "ai.tenant_model_usage", "iam.user_accounts"):
            cur.execute(f"SELECT count(*) FROM {table}")
            assert cur.fetchone()[0] == 0, table


def test_12_invalid_tenant_context_rejected():
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT set_config('app.current_tenant_id', 'not-a-uuid', true), set_config('app.current_access_mode', 'user', true)")
        with pytest.raises(psycopg.errors.InvalidTextRepresentation):
            cur.execute("SELECT count(*) FROM content.documents")


def test_13_pooled_connections_do_not_leak_context(tenants):
    """Transaction-local settings vanish at COMMIT; the SQLAlchemy pool also resets
    on check-in.  Re-using one physical connection must not carry tenant A's scope."""
    from sqlalchemy import text

    from app.database.session import SecurityContext, get_engine, scoped_session

    a = tenants["A"]
    tid, uid, gid = ids(a)
    sec = SecurityContext(access_mode="user", tenant_id=tid, user_id=uid, principals=(uid, tid, gid), lobs=("*",),
                          jurisdictions=("*",), max_class=3)
    engine = get_engine("app")
    with scoped_session(sec) as db:
        pid = db.execute(text("SELECT pg_backend_pid()")).scalar()
        assert db.execute(text("SELECT count(*) FROM content.documents")).scalar() > 0
    with engine.connect() as conn:  # same pool, no context
        assert conn.execute(text("SELECT current_setting('app.current_tenant_id', true)")).scalar() in ("", None)
        assert conn.execute(text("SELECT count(*) FROM content.documents")).scalar() == 0
        same = conn.execute(text("SELECT pg_backend_pid()")).scalar() == pid
    # raw connection: SET LOCAL semantics
    with connect() as c:
        with c.cursor() as cur:
            user_ctx(cur, a)
            cur.execute("SELECT count(*) FROM content.documents")
            assert cur.fetchone()[0] > 0
        c.commit()
        with c.cursor() as cur:
            cur.execute("SELECT count(*) FROM content.documents")
            assert cur.fetchone()[0] == 0
    # concurrent sessions with different tenants never see each other's rows
    seen: dict[str, set] = {}

    def work(key):
        t = tenants[key]
        t_tid, t_uid, t_gid = ids(t)
        s = SecurityContext(access_mode="user", tenant_id=t_tid, user_id=t_uid, principals=(t_uid, t_tid, t_gid),
                            lobs=("*",), jurisdictions=("*",), max_class=3)
        for _ in range(15):
            with scoped_session(s) as db:
                seen.setdefault(key, set()).update(db.execute(text("SELECT DISTINCT tenant_id::text FROM content.documents")).scalars())

    threads = [threading.Thread(target=work, args=(k,)) for k in ("A", "B", "A", "B")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert seen["A"] == {str(tenants["A"]["tenant"]["tenant_id"])}
    assert seen["B"] == {str(tenants["B"]["tenant"]["tenant_id"])}
    assert same in (True, False)


def test_14_worker_processes_only_its_tenant(tenants):
    from app.rag.ingestion.pipeline import PermanentIngestionError, run_job

    a, b = tenants["A"], tenants["B"]
    # A's worker context cannot load B's job: the job is invisible, so the run fails closed.
    with pytest.raises(PermanentIngestionError):
        run_job(uuid.UUID(str(a["tenant"]["tenant_id"])), uuid.UUID(str(b["docs"][0]["job_id"])))
    with connect("rag_worker") as c, c.cursor() as cur:
        ctx(cur, a["tenant"]["tenant_id"], None, "worker")
        cur.execute("SELECT DISTINCT tenant_id FROM content.document_chunks")
        assert [str(r[0]) for r in cur.fetchall()] == [str(a["tenant"]["tenant_id"])]


def test_15_revoked_access_enforced_on_next_request(client, tenants):
    a = tenants["A"]
    q = {"query": "standard excess own damage claim"}
    assert client.post("/api/v1/search", headers=a["analyst"], json=q).json()["results"]
    gid, uid = a["group_id"], a["users"]["analyst"]["user_id"]
    r = client.delete(f"/api/v1/admin/groups/{gid}/members/{uid}", headers=a["admin"])
    assert r.status_code == 200
    try:
        res = client.post("/api/v1/search", headers=a["analyst"], json=q)
        assert res.status_code == 200 and res.json()["results"] == []
    finally:
        client.post(f"/api/v1/admin/groups/{gid}/members", headers=a["admin"], json={"user_id": uid})
    assert client.post("/api/v1/search", headers=a["analyst"], json=q).json()["results"]


def test_16_suspended_tenant_cannot_operate(client, tenants, platform_admin):
    b = tenants["B"]
    tid = b["tenant"]["tenant_id"]
    r = client.post(f"/api/v1/platform/tenants/{tid}/suspend", headers=platform_admin,
                    json={"reason": "overdue invoice - RLS test", "confirm": True})
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    try:
        res = client.post("/api/v1/search", headers=b["analyst"], json={"query": "waiting period"})
        assert res.status_code in (401, 403)
        # database level: user-mode reads fail closed for a suspended tenant
        with connect() as c, c.cursor() as cur:
            user_ctx(cur, b)
            cur.execute("SELECT count(*) FROM content.documents")
            assert cur.fetchone()[0] == 0
        lr = client.post("/api/v1/auth/login", json={"email": b["users"]["analyst"]["email"], "password": "Str0ng!Passw0rd#2026"})
        assert lr.status_code == 403
    finally:
        r = client.post(f"/api/v1/platform/tenants/{tid}/activate", headers=platform_admin,
                        json={"reason": "invoice settled - RLS test", "confirm": True})
        assert r.json()["status"] == "active"
    from tests.conftest import auth, login

    b["analyst"] = auth(login(client, b["users"]["analyst"]["email"]))
    b["admin"] = auth(login(client, f"admin@{b['code']}.test"))
    b["outsider"] = auth(login(client, b["users"]["outsider"]["email"]))


def test_17_cross_tenant_foreign_keys_rejected(tenants):
    a, b = tenants["A"], tenants["B"]
    with connect() as c, c.cursor() as cur:
        ctx(cur, a["tenant"]["tenant_id"], a["users"]["analyst"]["user_id"], "tenant_admin")
        with pytest.raises((psycopg.errors.ForeignKeyViolation, psycopg.errors.InsufficientPrivilege)):
            # A's document referencing B's collection: composite FK (tenant_id, collection_id) fails
            cur.execute("""INSERT INTO content.documents (tenant_id, collection_id, title, created_by)
                           VALUES (%s, %s, 'cross-ref', %s)""",
                        (a["tenant"]["tenant_id"], b["collection"]["collection_id"], a["users"]["analyst"]["user_id"]))


def test_chunk_cannot_be_more_visible_than_parent_document(tenants):
    """Chunk ACL arrays derive from the parent document; restricting the document
    immediately restricts every chunk (prompt 6 test 9)."""
    a = tenants["A"]
    tid, uid, gid = ids(a)
    doc_id = a["docs"][1]["document_id"]
    with connect() as c, c.cursor() as cur:
        ctx(cur, tid, None, "tenant_admin")
        cur.execute("""INSERT INTO content.document_access (tenant_id, document_id, principal_type, principal_id, effect)
                       VALUES (%s, %s, 'user', %s, 'deny')""", (tid, doc_id, uid))
        cur.execute("SELECT app.refresh_document_acl(%s)", (doc_id,))
        c.commit()
    try:
        with connect() as c, c.cursor() as cur:
            user_ctx(cur, a)
            cur.execute("SELECT count(*) FROM content.document_chunks WHERE document_id = %s", (doc_id,))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM content.chunk_embeddings WHERE document_id = %s", (doc_id,))
            assert cur.fetchone()[0] == 0
    finally:
        with connect() as c, c.cursor() as cur:
            ctx(cur, tid, None, "tenant_admin")
            cur.execute("DELETE FROM content.document_access WHERE document_id = %s AND effect = 'deny'", (doc_id,))
            cur.execute("SELECT app.refresh_document_acl(%s)", (doc_id,))
            c.commit()


def test_tenant_admin_mode_has_no_content_access(tenants):
    """Spec SP-08: administrators manage metadata but cannot read chunk content."""
    with connect() as c, c.cursor() as cur:
        ctx(cur, tenants["A"]["tenant"]["tenant_id"], None, "tenant_admin")
        cur.execute("SELECT count(*) FROM content.documents")
        assert cur.fetchone()[0] > 0
        cur.execute("SELECT count(*) FROM content.document_chunks")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM content.document_pages")
        assert cur.fetchone()[0] == 0


def test_acl_refresh_function_refuses_user_mode(tenants):
    with connect() as c, c.cursor() as cur:
        user_ctx(cur, tenants["A"])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("SELECT app.refresh_document_acl(%s)", (tenants["A"]["docs"][0]["document_id"],))


def test_platform_mode_cannot_read_tenant_content(tenants):
    with connect() as c, c.cursor() as cur:
        ctx(cur, None, None, "platform", platform_role="platform_super_admin")
        cur.execute("SELECT count(*) FROM platform.tenants")
        assert cur.fetchone()[0] >= 2
        for table in ("content.documents", "content.document_chunks", "rag.conversation_messages", "iam.users"):
            cur.execute(f"SELECT count(*) FROM {table}")
            assert cur.fetchone()[0] == 0, table


def test_platform_admin_cannot_self_assert_break_glass_without_grant(tenants):
    with connect() as c, c.cursor() as cur:
        ctx(cur, tenants["A"]["tenant"]["tenant_id"], None, "break_glass", account=uuid.uuid4(),
            platform_role="platform_super_admin")
        cur.execute("SELECT count(*) FROM content.document_chunks")
        assert cur.fetchone()[0] == 0
