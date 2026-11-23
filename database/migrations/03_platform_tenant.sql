-- =============================================================================
-- 03  Schemas, security-context helper functions, platform and tenant entities
-- Owner: rag_migration.  Spec refs: section 10.1 (conventions), 10.6 (RLS rules),
-- FR-105, FR-106, FR-178, NFR-020, extension sections 1-4.
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS app;        -- security-context helpers (STABLE SQL)
CREATE SCHEMA IF NOT EXISTS app_admin;  -- migration-only helpers, never granted to services
CREATE SCHEMA IF NOT EXISTS platform;   -- tenants, plans, quotas, platform identity, AI catalogue
CREATE SCHEMA IF NOT EXISTS iam;        -- identity, memberships, RBAC/ABAC
CREATE SCHEMA IF NOT EXISTS content;    -- collections, documents, versions, chunks, embeddings
CREATE SCHEMA IF NOT EXISTS ingest;     -- ingestion jobs and logs
CREATE SCHEMA IF NOT EXISTS rag;        -- conversations, messages, sources, search/retrieval logs, feedback
CREATE SCHEMA IF NOT EXISTS ai;         -- tenant AI/RAG configuration, prompts, guardrail events, model usage
CREATE SCHEMA IF NOT EXISTS eval;       -- evaluation datasets, runs, results
CREATE SCHEMA IF NOT EXISTS audit;      -- append-only, hash-chained tenant audit log
CREATE SCHEMA IF NOT EXISTS ops;        -- usage aggregates, worker heartbeats

-- Extensions (vector, pg_trgm, pgcrypto, citext) live in public: services need
-- USAGE for their types / functions but nobody except the owner may CREATE there.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO rag_app, rag_worker, rag_readonly, rag_auth_fn, rag_acl_fn, rag_audit_fn;
REVOKE ALL ON SCHEMA app_admin FROM PUBLIC;

-- -----------------------------------------------------------------------------
-- Security context.  The API / worker sets these with set_config(name, value,
-- true) - the transaction-local equivalent of SET LOCAL - immediately after
-- BEGIN.  Values are derived server-side from the authenticated identity and
-- validated membership, never from request content (spec 10.6 rule 1).
-- Every helper FAILS CLOSED: a missing setting yields NULL / empty / -1 so that
-- every policy predicate evaluates to false (spec 10.6 rule 2, AP-07).
-- An unparsable tenant id raises an error (invalid context is rejected).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.current_tenant_id() RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION app.current_user_id() RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION app.current_account_id() RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT NULLIF(current_setting('app.current_account_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION app.current_platform_role() RETURNS text
LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT NULLIF(current_setting('app.current_platform_role', true), '') $$;

CREATE OR REPLACE FUNCTION app.current_access_mode() RETURNS text
LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT COALESCE(NULLIF(current_setting('app.current_access_mode', true), ''), 'none') $$;

CREATE OR REPLACE FUNCTION app.current_principals() RETURNS uuid[]
LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT COALESCE(string_to_array(NULLIF(current_setting('app.current_principals', true), ''), ',')::uuid[], '{}'::uuid[]) $$;

CREATE OR REPLACE FUNCTION app.current_lobs() RETURNS text[]
LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT COALESCE(string_to_array(NULLIF(current_setting('app.current_lobs', true), ''), ','), '{}'::text[]) $$;

CREATE OR REPLACE FUNCTION app.current_jurisdictions() RETURNS text[]
LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT COALESCE(string_to_array(NULLIF(current_setting('app.current_jurisdictions', true), ''), ','), '{}'::text[]) $$;

CREATE OR REPLACE FUNCTION app.current_max_class() RETURNS smallint
LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT COALESCE(NULLIF(current_setting('app.current_max_class', true), '')::smallint, -1::smallint) $$;

CREATE OR REPLACE FUNCTION app.is_platform_admin() RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT app.current_access_mode() IN ('platform', 'platform_provisioning')
          AND COALESCE(app.current_platform_role() IN ('platform_super_admin', 'platform_admin'), false) $$;

CREATE OR REPLACE FUNCTION app.is_platform_reader() RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT app.current_access_mode() IN ('platform', 'platform_provisioning')
          AND COALESCE(app.current_platform_role() IN
              ('platform_super_admin', 'platform_admin', 'platform_operator', 'platform_security', 'platform_support'), false) $$;

-- Generic updated_at trigger.
CREATE OR REPLACE FUNCTION app.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at := now(); RETURN NEW; END $$;

-- -----------------------------------------------------------------------------
-- Migration-only helper: enable + FORCE RLS and add the RESTRICTIVE tenant
-- isolation policy for the three service login roles.  The NOLOGIN definer
-- owners (rag_auth_fn, rag_acl_fn, rag_audit_fn) get their own explicit,
-- narrowly scoped policies; every other role (incl. the table owner, because
-- of FORCE) has no permissive policy at all and therefore sees nothing.  RESTRICTIVE means no PERMISSIVE policy added later can
-- ever widen tenant scope (spec 10.6 rule 3).  For user-facing access modes the
-- tenant must also be operational (not suspended / deactivated / archived).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app_admin.apply_tenant_rls(p_table regclass) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE pol text := replace(p_table::text, '.', '_') || '_tenant_isolation';
BEGIN
  EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', p_table);
  EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', p_table);
  EXECUTE format('DROP POLICY IF EXISTS %I ON %s', pol, p_table);
  EXECUTE format($f$CREATE POLICY %I ON %s AS RESTRICTIVE FOR ALL TO rag_app, rag_worker, rag_readonly
      USING (tenant_id = app.current_tenant_id()
             AND (app.current_access_mode() NOT IN ('user', 'tenant_admin', 'auditor')
                  OR (SELECT app.tenant_is_operational())))
      WITH CHECK (tenant_id = app.current_tenant_id()
             AND (app.current_access_mode() NOT IN ('user', 'tenant_admin', 'auditor')
                  OR (SELECT app.tenant_is_operational())))$f$, pol, p_table);
END $$;

-- =============================================================================
-- Platform-level tables
-- =============================================================================
CREATE TABLE IF NOT EXISTS platform.tenant_plans (
  plan_id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code                    text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9_]{2,40}$'),
  name                    text NOT NULL,
  description             text,
  max_users               integer NOT NULL CHECK (max_users >= 0),
  max_documents           integer NOT NULL CHECK (max_documents >= 0),
  max_storage_bytes       bigint  NOT NULL CHECK (max_storage_bytes >= 0),
  max_document_size_bytes bigint  NOT NULL CHECK (max_document_size_bytes > 0),
  monthly_ai_tokens       bigint  NOT NULL CHECK (monthly_ai_tokens >= 0),
  monthly_ai_requests     integer NOT NULL CHECK (monthly_ai_requests >= 0),
  max_concurrent_chats    integer NOT NULL CHECK (max_concurrent_chats >= 0),
  max_ingestion_jobs      integer NOT NULL CHECK (max_ingestion_jobs >= 0),
  max_collections         integer NOT NULL CHECK (max_collections >= 0),
  features                jsonb   NOT NULL DEFAULT '{}'::jsonb,
  monthly_price           numeric(12,2) NOT NULL DEFAULT 0,
  is_active               boolean NOT NULL DEFAULT true,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform.tenants (
  tenant_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code             text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9][a-z0-9-]{1,39}$'),
  name             text NOT NULL,
  legal_entity     text,
  status           text NOT NULL DEFAULT 'trial'
                   CHECK (status IN ('trial', 'active', 'suspended', 'deactivated', 'archived')),
  status_reason    text,
  home_region      text NOT NULL DEFAULT 'default',
  allowed_regions  text[] NOT NULL DEFAULT '{default}',
  branding         jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- Data is never auto-deleted on suspension / deactivation; archival keeps data
  -- until retention_until and a separate, approved offboarding job (FR-178, FR-241).
  retention_until  date,
  activated_at     timestamptz,
  suspended_at     timestamptz,
  archived_at      timestamptz,
  last_activity_at timestamptz,
  created_by       uuid,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform.tenant_subscriptions (
  subscription_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  plan_id         uuid NOT NULL REFERENCES platform.tenant_plans(plan_id) ON DELETE RESTRICT,
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('trial', 'active', 'past_due', 'cancelled', 'expired')),
  starts_at       timestamptz NOT NULL DEFAULT now(),
  ends_at         timestamptz,
  trial_ends_at   timestamptz,
  created_by      uuid,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_at IS NULL OR ends_at > starts_at)
);
CREATE UNIQUE INDEX IF NOT EXISTS tenant_subscriptions_one_current
  ON platform.tenant_subscriptions (tenant_id) WHERE status IN ('trial', 'active', 'past_due');

-- Effective quotas per tenant (copied from the plan at assignment, overridable).
CREATE TABLE IF NOT EXISTS platform.tenant_quotas (
  tenant_id               uuid PRIMARY KEY REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  max_users               integer NOT NULL CHECK (max_users >= 0),
  max_documents           integer NOT NULL CHECK (max_documents >= 0),
  max_storage_bytes       bigint  NOT NULL CHECK (max_storage_bytes >= 0),
  max_document_size_bytes bigint  NOT NULL CHECK (max_document_size_bytes > 0),
  monthly_ai_tokens       bigint  NOT NULL CHECK (monthly_ai_tokens >= 0),
  monthly_ai_requests     integer NOT NULL CHECK (monthly_ai_requests >= 0),
  max_concurrent_chats    integer NOT NULL CHECK (max_concurrent_chats >= 0),
  max_ingestion_jobs      integer NOT NULL CHECK (max_ingestion_jobs >= 0),
  max_collections         integer NOT NULL CHECK (max_collections >= 0),
  warning_threshold_pct   smallint NOT NULL DEFAULT 80 CHECK (warning_threshold_pct BETWEEN 1 AND 100),
  updated_by              uuid,
  updated_at              timestamptz NOT NULL DEFAULT now()
);

-- Live usage counters maintained transactionally by the services (quota checks).
CREATE TABLE IF NOT EXISTS platform.tenant_usage (
  tenant_id            uuid PRIMARY KEY REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  users_count          integer NOT NULL DEFAULT 0,
  documents_count      integer NOT NULL DEFAULT 0,
  collections_count    integer NOT NULL DEFAULT 0,
  chunks_count         bigint  NOT NULL DEFAULT 0,
  storage_bytes        bigint  NOT NULL DEFAULT 0,
  usage_month          date    NOT NULL DEFAULT date_trunc('month', now())::date,
  ai_tokens_month      bigint  NOT NULL DEFAULT 0,
  ai_requests_month    integer NOT NULL DEFAULT 0,
  active_ingestion_jobs integer NOT NULL DEFAULT 0,
  content_epoch        bigint  NOT NULL DEFAULT 0,  -- bumped on content/ACL change; part of cache keys (FR-108)
  updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform.tenant_feature_flags (
  tenant_id  uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  flag       text NOT NULL CHECK (flag ~ '^[a-z0-9_.]{2,60}$'),
  enabled    boolean NOT NULL DEFAULT false,
  updated_by uuid,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, flag)
);

CREATE TABLE IF NOT EXISTS platform.tenant_domains (
  domain_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  domain     citext NOT NULL UNIQUE,
  verified   boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Tenant settings: session policy, MFA, retention, branding overrides and the
-- list of AI/RAG settings the platform allows the tenant admin to change.
CREATE TABLE IF NOT EXISTS platform.tenant_settings (
  tenant_id                 uuid PRIMARY KEY REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  require_mfa_for_admin     boolean NOT NULL DEFAULT false,
  session_idle_minutes      integer NOT NULL DEFAULT 30 CHECK (session_idle_minutes BETWEEN 5 AND 1440),
  session_absolute_hours    integer NOT NULL DEFAULT 12 CHECK (session_absolute_hours BETWEEN 1 AND 168),
  conversation_retention_days integer NOT NULL DEFAULT 365 CHECK (conversation_retention_days > 0),
  audit_retention_days      integer NOT NULL DEFAULT 2555 CHECK (audit_retention_days > 0),
  store_query_text          boolean NOT NULL DEFAULT true,
  default_language          text NOT NULL DEFAULT 'english',
  tenant_overridable_ai_settings text[] NOT NULL DEFAULT
      '{temperature,max_output_tokens,chunk_size,chunk_overlap,vector_top_k,fts_top_k,vector_weight,fts_weight,rrf_k,rerank_enabled,rerank_top_n,max_context_tokens,min_relevance,query_rewriting,citation_required}',
  settings                  jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_by                uuid,
  updated_at                timestamptz NOT NULL DEFAULT now()
);

-- Platform identity and RBAC ----------------------------------------------------
CREATE TABLE IF NOT EXISTS platform.platform_roles (
  role_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code        text NOT NULL UNIQUE,
  name        text NOT NULL,
  description text
);
CREATE TABLE IF NOT EXISTS platform.platform_permissions (
  permission_code text PRIMARY KEY,
  description     text NOT NULL
);
CREATE TABLE IF NOT EXISTS platform.platform_role_permissions (
  role_id         uuid NOT NULL REFERENCES platform.platform_roles(role_id) ON DELETE CASCADE,
  permission_code text NOT NULL REFERENCES platform.platform_permissions(permission_code) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_code)
);

-- Global login identity (one per human).  Tenant-specific profiles live in iam.users.
CREATE TABLE IF NOT EXISTS iam.user_accounts (
  account_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email               citext NOT NULL UNIQUE,
  display_name        text NOT NULL,
  password_hash       text,             -- NULL for SSO-only identities (FR-002)
  auth_provider       text NOT NULL DEFAULT 'local' CHECK (auth_provider IN ('local', 'oidc')),
  external_subject    text,             -- IdP 'sub' for OIDC identities
  mfa_enabled         boolean NOT NULL DEFAULT false,
  mfa_secret_enc      text,             -- Fernet-encrypted TOTP secret
  status              text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'locked', 'disabled')),
  failed_login_count  integer NOT NULL DEFAULT 0,
  locked_until        timestamptz,
  last_login_at       timestamptz,
  password_changed_at timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (auth_provider, external_subject)
);

CREATE TABLE IF NOT EXISTS platform.platform_users (
  account_id uuid PRIMARY KEY REFERENCES iam.user_accounts(account_id) ON DELETE RESTRICT,
  role_id    uuid NOT NULL REFERENCES platform.platform_roles(role_id) ON DELETE RESTRICT,
  status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Hash-chained platform audit trail (cross-tenant administrative actions,
-- break-glass access, security events).  Append-only.
CREATE TABLE IF NOT EXISTS platform.platform_audit_logs (
  event_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  seq               bigint GENERATED ALWAYS AS IDENTITY,
  occurred_at       timestamptz NOT NULL DEFAULT clock_timestamp(),
  category          text NOT NULL,
  action            text NOT NULL,
  outcome           text NOT NULL DEFAULT 'success' CHECK (outcome IN ('success', 'failure', 'denied')),
  severity          text NOT NULL DEFAULT 'info' CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
  actor_account_id  uuid,
  target_tenant_id  uuid,
  target_type       text,
  target_id         text,
  reason            text,
  correlation_id    text,
  source_ip         inet,
  detail            jsonb NOT NULL DEFAULT '{}'::jsonb,
  prev_hash         text,
  hash              text
);

-- AI provider registry and model catalogue (FR-169).  Secrets encrypted by the
-- application (Fernet / KMS); only the last four characters are stored in clear.
CREATE TABLE IF NOT EXISTS platform.ai_providers (
  provider_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code             text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9_-]{2,40}$'),
  name             text NOT NULL,
  provider_type    text NOT NULL CHECK (provider_type IN
                     ('openai', 'azure_openai', 'ollama', 'huggingface', 'openai_compatible', 'local')),
  base_url         text,
  api_version      text,
  api_key_enc      text,
  api_key_last4    text,
  region           text NOT NULL DEFAULT 'default',
  is_enabled       boolean NOT NULL DEFAULT true,
  allow_tenant_override boolean NOT NULL DEFAULT false,
  rate_limit_per_min integer,
  health_status    text NOT NULL DEFAULT 'unknown' CHECK (health_status IN ('unknown', 'healthy', 'degraded', 'down')),
  last_checked_at  timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS platform.model_catalogue (
  model_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_id         uuid NOT NULL REFERENCES platform.ai_providers(provider_id) ON DELETE RESTRICT,
  model_name          text NOT NULL,
  model_version       text NOT NULL DEFAULT 'latest',
  purpose             text NOT NULL CHECK (purpose IN ('chat', 'embedding', 'rerank', 'rewrite', 'judge')),
  dimensions          integer CHECK (dimensions IS NULL OR dimensions IN (256, 384, 512, 768, 1024, 1536, 3072)),
  context_window      integer,
  input_cost_per_1k   numeric(12,6) NOT NULL DEFAULT 0,
  output_cost_per_1k  numeric(12,6) NOT NULL DEFAULT 0,
  risk_class          text NOT NULL DEFAULT 'medium' CHECK (risk_class IN ('low', 'medium', 'high')),
  status              text NOT NULL DEFAULT 'proposed'
                      CHECK (status IN ('proposed', 'approved', 'active', 'deprecated', 'retired')),
  is_default          boolean NOT NULL DEFAULT false,
  approved_by         uuid,
  approved_at         timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider_id, model_name, model_version, purpose),
  CHECK (purpose <> 'embedding' OR dimensions IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS model_catalogue_one_default
  ON platform.model_catalogue (purpose) WHERE is_default;

CREATE TABLE IF NOT EXISTS platform.platform_settings (
  key        text PRIMARY KEY,
  value      jsonb NOT NULL,
  updated_by uuid,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Break-glass: explicit, time-limited, reason-captured, audited support access.
CREATE TABLE IF NOT EXISTS platform.break_glass_grants (
  grant_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id   uuid NOT NULL REFERENCES iam.user_accounts(account_id),
  tenant_id    uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  reason       text NOT NULL CHECK (length(reason) >= 15),
  scope        text[] NOT NULL DEFAULT '{documents:read}',
  starts_at    timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  ended_at     timestamptz,
  status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended', 'expired', 'revoked')),
  resources_accessed jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (expires_at > starts_at AND expires_at <= starts_at + interval '8 hours')
);

-- Worker heartbeats for platform monitoring (no tenant data).
CREATE TABLE IF NOT EXISTS ops.worker_heartbeats (
  worker_name  text PRIMARY KEY,
  hostname     text,
  queues       text[] NOT NULL DEFAULT '{}',
  status       text NOT NULL DEFAULT 'online',
  processed    bigint NOT NULL DEFAULT 0,
  failed       bigint NOT NULL DEFAULT 0,
  last_seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION app.tenant_is_operational() RETURNS boolean
LANGUAGE sql STABLE AS
$$ SELECT COALESCE((SELECT t.status IN ('active', 'trial') FROM platform.tenants t
                    WHERE t.tenant_id = app.current_tenant_id()), false) $$;

DROP TRIGGER IF EXISTS trg_tenants_touch ON platform.tenants;
CREATE TRIGGER trg_tenants_touch BEFORE UPDATE ON platform.tenants FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
DROP TRIGGER IF EXISTS trg_accounts_touch ON iam.user_accounts;
CREATE TRIGGER trg_accounts_touch BEFORE UPDATE ON iam.user_accounts FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
