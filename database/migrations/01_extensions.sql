-- =============================================================================
-- 01  PostgreSQL extensions
-- Executed by the bootstrap step as a superuser (pgvector is not a "trusted"
-- extension, so a non-superuser migration role cannot create it).
-- Alembic revision 0001 re-runs this file; every statement is idempotent.
-- Supported: PostgreSQL 16.x, pgvector >= 0.8.0 (iterative index scans).
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector: semantic retrieval (FR-083)
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- trigram indexes: exact clause / number search (FR-093)
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid(), digest() for audit hash chain (FR-229)
CREATE EXTENSION IF NOT EXISTS citext;      -- case-insensitive e-mail identity
