-- =============================================================================
-- 02  Database roles and privileges (cluster level)
-- Executed by backend/app/database/bootstrap.py as a superuser.  Placeholders
-- {{...}} are substituted with properly quoted literals by the bootstrap code;
-- passwords never live in this file.
--
-- Role model (least privilege, NO role has SUPERUSER or BYPASSRLS):
--   rag_migration  LOGIN   owns the database and every object; used only by
--                           Alembic / bootstrap.  Never configured in API or
--                           worker processes.  Subject to FORCE RLS like
--                           everybody else.
--   rag_app        LOGIN   FastAPI processes.  DML only, no DDL, no ownership.
--   rag_worker     LOGIN   Celery ingestion / aggregation workers.
--   rag_readonly   LOGIN   authorised reporting; SELECT only, still under RLS.
--   rag_auth_fn    NOLOGIN owner of the narrowly scoped SECURITY DEFINER
--                           authentication functions (credential lookup,
--                           membership resolution, refresh-token lookup).
--   rag_acl_fn     NOLOGIN owner of app.refresh_document_acl (ACL propagation
--                           to chunks without granting admins content reads).
--   rag_audit_fn   NOLOGIN owner of the audit hash-chain trigger function.
-- =============================================================================
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_migration') THEN
    CREATE ROLE rag_migration LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_app') THEN
    CREATE ROLE rag_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_worker') THEN
    CREATE ROLE rag_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_readonly') THEN
    CREATE ROLE rag_readonly LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_auth_fn') THEN
    CREATE ROLE rag_auth_fn NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_acl_fn') THEN
    CREATE ROLE rag_acl_fn NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_audit_fn') THEN
    CREATE ROLE rag_audit_fn NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
END $$;

-- Re-assert attributes on every run so drift (e.g. someone granting BYPASSRLS) is corrected.
ALTER ROLE rag_migration NOSUPERUSER NOBYPASSRLS PASSWORD {{RAG_MIGRATION_PASSWORD}};
ALTER ROLE rag_app       NOSUPERUSER NOBYPASSRLS PASSWORD {{RAG_APP_PASSWORD}};
ALTER ROLE rag_worker    NOSUPERUSER NOBYPASSRLS PASSWORD {{RAG_WORKER_PASSWORD}};
ALTER ROLE rag_readonly  NOSUPERUSER NOBYPASSRLS PASSWORD {{RAG_READONLY_PASSWORD}};

-- The migration role must be able to hand ownership of definer functions to the
-- function-owner roles (ALTER FUNCTION ... OWNER TO requires membership).
GRANT rag_auth_fn  TO rag_migration;
GRANT rag_audit_fn TO rag_migration;
GRANT rag_acl_fn   TO rag_migration;

-- Statement timeouts protect the pool from runaway queries.
ALTER ROLE rag_app      SET statement_timeout = '30s';
ALTER ROLE rag_worker   SET statement_timeout = '15min';
ALTER ROLE rag_readonly SET statement_timeout = '60s';
-- Never allow these roles to silently run with RLS disabled.
ALTER ROLE rag_app      SET row_security = on;
ALTER ROLE rag_worker   SET row_security = on;
ALTER ROLE rag_readonly SET row_security = on;
