"""Database roles: created by app.database.bootstrap (cluster level, superuser); this revision verifies them

Revision ID: 0002
Revises: 0001
"""
from alembic import op  # noqa: F401

revision = "0002"
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.exec_driver_sql(
        "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname IN "
        "('rag_migration','rag_app','rag_worker','rag_readonly','rag_auth_fn','rag_acl_fn','rag_audit_fn')").fetchall()
    found = {r[0] for r in rows}
    expected = {"rag_migration", "rag_app", "rag_worker", "rag_readonly", "rag_auth_fn", "rag_acl_fn", "rag_audit_fn"}
    if found != expected:
        raise RuntimeError(f"roles missing: {sorted(expected - found)} - run app.database.bootstrap first")
    unsafe = [r[0] for r in rows if r[1] or r[2]]
    if unsafe:
        raise RuntimeError(f"roles must not be SUPERUSER/BYPASSRLS: {unsafe}")


def downgrade() -> None:
    raise NotImplementedError("Forward-only migration: restore from backup or write a compensating revision.")
