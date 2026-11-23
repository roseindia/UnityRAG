"""Generate the table ownership / RLS matrix (docs/database/TABLE_OWNERSHIP_MATRIX.md)
from the live catalog of a migrated database (superuser DSN, read-only queries)."""
import os
from pathlib import Path

import psycopg

DSN = os.environ.get("DOCS_DB_DSN", "host=127.0.0.1 user=postgres dbname=rag_pytest")
PLATFORM = {"platform.tenants": "Platform (tenant row readable by its own tenant)",
            "platform.tenant_plans": "Platform reference", "platform.platform_roles": "Platform reference",
            "platform.platform_permissions": "Platform reference", "platform.platform_role_permissions": "Platform reference",
            "platform.platform_settings": "Platform reference", "platform.ai_providers": "Platform reference",
            "platform.model_catalogue": "Platform reference", "platform.platform_users": "Platform",
            "platform.platform_audit_logs": "Platform (append-only)", "platform.break_glass_grants": "Platform / tenant boundary",
            "iam.user_accounts": "Platform identity (global)", "iam.sessions": "Account / tenant boundary",
            "iam.refresh_tokens": "Account (definer functions only)", "iam.password_reset_tokens": "Account (definer functions only)",
            "iam.login_events": "Account / tenant boundary", "iam.permissions": "Global reference (no tenant data)",
            "ops.worker_heartbeats": "Platform operations", "audit.chain_heads": "Audit internals (definer only)",
            "ops.tenant_usage_daily": "Tenant aggregate (platform-readable)"}
WHY_NO_RESTRICTIVE = {"iam.permissions": "Identical catalogue for every tenant, contains no tenant data; read-only SELECT grant, so RLS adds nothing.",
                      "platform.tenant_plans": "Reference data; writes limited to platform admins by policy.",
                      "audit.chain_heads": "Only the audit trigger (rag_audit_fn) has a policy; services have no grant."}

with psycopg.connect(DSN) as c:
    rows = c.execute("""
      SELECT n.nspname || '.' || t.relname AS tbl, t.relrowsecurity, t.relforcerowsecurity,
             EXISTS (SELECT 1 FROM information_schema.columns col WHERE col.table_schema = n.nspname
                       AND col.table_name = t.relname AND col.column_name = 'tenant_id') AS has_tenant,
             (SELECT string_agg(DISTINCT p.policyname || CASE WHEN p.permissive = 'RESTRICTIVE' THEN ' (R)' ELSE '' END, ', ')
                FROM pg_policies p WHERE p.schemaname = n.nspname AND p.tablename = t.relname) AS policies,
             (SELECT count(*) FROM pg_policies p WHERE p.schemaname = n.nspname AND p.tablename = t.relname
                AND p.permissive = 'RESTRICTIVE') AS n_restrictive,
             pg_get_userbyid(t.relowner) AS owner
        FROM pg_class t JOIN pg_namespace n ON n.oid = t.relnamespace
       WHERE t.relkind = 'r' AND n.nspname IN ('platform','iam','content','ingest','rag','ai','eval','audit','ops')
       ORDER BY 1""").fetchall()
    fks = c.execute("""
      SELECT DISTINCT cn.nspname || '_' || cl.relname AS child, pn.nspname || '_' || pl.relname AS parent,
             (SELECT string_agg(a.attname, ',' ORDER BY a.attnum) FROM pg_attribute a
               WHERE a.attrelid = con.conrelid AND a.attnum = ANY (con.conkey)) AS cols
        FROM pg_constraint con
        JOIN pg_class cl ON cl.oid = con.conrelid JOIN pg_namespace cn ON cn.oid = cl.relnamespace
        JOIN pg_class pl ON pl.oid = con.confrelid JOIN pg_namespace pn ON pn.oid = pl.relnamespace
       WHERE con.contype = 'f' AND cn.nspname IN ('platform','iam','content','ingest','rag','ai','eval','audit','ops')
       ORDER BY 2, 1""").fetchall()
er = ["```mermaid", "erDiagram"]
for child, parent, cols in fks:
    if parent == "platform_tenants" and cols == "tenant_id":
        continue  # every tenant-owned table references platform.tenants; omitted for readability
    er.append(f'    {parent} ||--o{{ {child} : "{cols}"')
er.append("```")
out = ["# Table ownership and RLS matrix", "",
       "Generated from the PostgreSQL catalog of a database migrated to head (`scripts/generate_db_docs.py`).",
       "(R) = RESTRICTIVE policy (tenant isolation). Owner of every table: `rag_migration` (never used by services).", "",
       "| Table | Scope | tenant_id | RLS enabled | FORCE | Restrictive tenant policy | Policies | Notes |", "|---|---|---|---|---|---|---|---|"]
for tbl, rls, force, has_t, pols, n_r, owner in rows:
    scope = PLATFORM.get(tbl, "Tenant")
    note = WHY_NO_RESTRICTIVE.get(tbl, "")
    if not n_r and has_t and not note:
        note = "Cross-tenant platform reads allowed only for platform readers; tenants see their own rows."
    out.append(f"| {tbl} | {scope} | {'Yes' if has_t else 'No'} | {'Yes' if rls else 'No'} | {'Yes' if force else 'No'} | "
               f"{'Yes' if n_r else 'No'} | {pols or '-'} | {note} |")
out += ["", (f"Tables: {len(rows)}; with RLS: {sum(1 for r in rows if r[1])}; FORCE: {sum(1 for r in rows if r[2])}; "
             f"tenant-isolated (restrictive): {sum(1 for r in rows if r[5])}.")]
root = Path(__file__).resolve().parents[1] / "docs" / "database"
(root / "TABLE_OWNERSHIP_MATRIX.md").write_text("\n".join(out) + "\n", encoding="utf-8")
design = root / "DATABASE_DESIGN.md"
if design.exists():  # embed the generated matrix between the markers
    d = design.read_text(encoding="utf-8")
    a, b = d.index("<!-- MATRIX:BEGIN -->"), d.index("<!-- MATRIX:END -->")
    body = "\n".join(out[5:])  # skip the title/intro lines
    d = d[:a] + "<!-- MATRIX:BEGIN -->\n" + body + "\n" + d[b:]
    a, b = d.index("<!-- ER:BEGIN -->"), d.index("<!-- ER:END -->")
    d = d[:a] + "<!-- ER:BEGIN -->\n" + "\n".join(er) + "\n" + d[b:]
    design.write_text(d, encoding="utf-8")
print("\n".join(out[-1:]))
