-- =============================================================================
-- 10  Tenant AI and RAG configuration, prompt templates, guardrail events and
--     model usage records (+ RLS)
-- Spec refs: 6.11 (FR-169..FR-173, FR-176, FR-177), 6.9 (FR-151, FR-152),
-- 6.14 (FR-220, FR-221), 10.2.5, extension 7.7.
-- Configurations are versioned and immutable once superseded: a change inserts
-- a new version and flips is_active (rollback = re-activate an old version).
-- =============================================================================
CREATE TABLE IF NOT EXISTS ai.tenant_ai_configurations (
  tenant_id            uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  config_id            uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  version              integer NOT NULL,
  llm_provider         text NOT NULL DEFAULT 'local',
  chat_model           text NOT NULL DEFAULT 'extractive-v1',
  embedding_provider   text NOT NULL DEFAULT 'local',
  embedding_model      text NOT NULL DEFAULT 'hashing-v1',
  embedding_dimensions integer NOT NULL DEFAULT 384 CHECK (embedding_dimensions IN (256, 384, 512, 768, 1024, 1536, 3072)),
  reranker_provider    text NOT NULL DEFAULT 'local',
  reranker_model       text NOT NULL DEFAULT 'lexical-overlap-v1',
  rewrite_model        text,
  temperature          real NOT NULL DEFAULT 0.1 CHECK (temperature BETWEEN 0 AND 2),
  max_output_tokens    integer NOT NULL DEFAULT 800 CHECK (max_output_tokens BETWEEN 16 AND 16000),
  distance_metric      text NOT NULL DEFAULT 'cosine' CHECK (distance_metric IN ('cosine', 'inner_product', 'l2')),
  is_active            boolean NOT NULL DEFAULT false,
  change_reason        text,
  created_by           uuid,
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS ai_config_one_active ON ai.tenant_ai_configurations (tenant_id) WHERE is_active;

CREATE TABLE IF NOT EXISTS ai.tenant_rag_configurations (
  tenant_id          uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  config_id          uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  version            integer NOT NULL,
  chunking_strategy  text NOT NULL DEFAULT 'structure_aware' CHECK (chunking_strategy IN ('fixed', 'recursive', 'structure_aware')),
  chunk_size         integer NOT NULL DEFAULT 350 CHECK (chunk_size BETWEEN 64 AND 4000),     -- tokens
  chunk_overlap      integer NOT NULL DEFAULT 40  CHECK (chunk_overlap >= 0),
  parent_child       boolean NOT NULL DEFAULT true,
  vector_top_k       integer NOT NULL DEFAULT 30 CHECK (vector_top_k BETWEEN 1 AND 500),
  fts_top_k          integer NOT NULL DEFAULT 30 CHECK (fts_top_k BETWEEN 1 AND 500),
  exact_top_k        integer NOT NULL DEFAULT 10 CHECK (exact_top_k BETWEEN 0 AND 100),
  vector_weight      real NOT NULL DEFAULT 1.0 CHECK (vector_weight >= 0),
  fts_weight         real NOT NULL DEFAULT 1.0 CHECK (fts_weight >= 0),
  exact_weight       real NOT NULL DEFAULT 1.5 CHECK (exact_weight >= 0),
  rrf_k              integer NOT NULL DEFAULT 60 CHECK (rrf_k BETWEEN 1 AND 1000),
  rerank_enabled     boolean NOT NULL DEFAULT true,
  rerank_top_n       integer NOT NULL DEFAULT 20 CHECK (rerank_top_n BETWEEN 1 AND 200),
  final_top_k        integer NOT NULL DEFAULT 6 CHECK (final_top_k BETWEEN 1 AND 50),
  max_context_tokens integer NOT NULL DEFAULT 3000 CHECK (max_context_tokens BETWEEN 256 AND 128000),
  min_relevance      real NOT NULL DEFAULT 0.0 CHECK (min_relevance >= 0),
  hnsw_ef_search     integer NOT NULL DEFAULT 100 CHECK (hnsw_ef_search BETWEEN 10 AND 1000),
  citation_required  boolean NOT NULL DEFAULT true,
  query_rewriting    boolean NOT NULL DEFAULT true,
  guardrails         jsonb NOT NULL DEFAULT '{"prompt_injection": "block", "pii_output": "mask", "regulated_decision": "block"}'::jsonb,
  is_active          boolean NOT NULL DEFAULT false,
  change_reason      text,
  created_by         uuid,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, version),
  CHECK (chunk_overlap < chunk_size)
);
CREATE UNIQUE INDEX IF NOT EXISTS rag_config_one_active ON ai.tenant_rag_configurations (tenant_id) WHERE is_active;

-- Tenant-specific provider credentials (only when the platform allows override).
CREATE TABLE IF NOT EXISTS ai.tenant_provider_credentials (
  tenant_id      uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  credential_id  uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  provider_code  text NOT NULL,
  base_url       text,
  api_key_enc    text,
  api_key_last4  text,
  created_by     uuid,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, provider_code)
);

CREATE TABLE IF NOT EXISTS ai.prompt_templates (
  tenant_id     uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  template_id   uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  name          text NOT NULL,
  purpose       text NOT NULL CHECK (purpose IN ('answer', 'rewrite', 'judge', 'summarise')),
  version       integer NOT NULL,
  template      text NOT NULL,
  status        text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'active', 'retired')),
  created_by    uuid,
  approved_by   uuid,
  approved_at   timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, name, version),
  CHECK (approved_by IS NULL OR approved_by <> created_by)      -- approver differs from author (FR-171)
);

CREATE TABLE IF NOT EXISTS ai.guardrail_events (
  tenant_id      uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  event_id       uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id        uuid,
  conversation_id uuid,
  message_id     uuid,
  stage          text NOT NULL CHECK (stage IN ('ingestion', 'input', 'evidence', 'output')),
  rule_id        text NOT NULL,
  rule_version   text NOT NULL DEFAULT '1',
  decision       text NOT NULL CHECK (decision IN ('allow', 'block', 'sanitise', 'mask', 'abstain', 'alert', 'quarantine')),
  severity       text NOT NULL DEFAULT 'low' CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  category       text NOT NULL,
  correlation_id text,
  detail         jsonb NOT NULL DEFAULT '{}'::jsonb,         -- match metadata only, never raw content
  occurred_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai.tenant_model_usage (
  tenant_id      uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  usage_id       uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id        uuid,
  department_id  uuid,
  purpose        text NOT NULL CHECK (purpose IN ('chat', 'embedding', 'rerank', 'rewrite', 'judge', 'ingestion_embedding')),
  provider       text NOT NULL,
  model          text NOT NULL,
  input_tokens   integer NOT NULL DEFAULT 0,
  output_tokens  integer NOT NULL DEFAULT 0,
  latency_ms     integer,
  estimated_cost numeric(14,6) NOT NULL DEFAULT 0,       -- estimate from catalogue pricing
  status         text NOT NULL DEFAULT 'success' CHECK (status IN ('success', 'error', 'fallback')),
  correlation_id text,
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS guardrail_rule    ON ai.guardrail_events (tenant_id, rule_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS guardrail_corr    ON ai.guardrail_events (correlation_id);
CREATE INDEX IF NOT EXISTS model_usage_time  ON ai.tenant_model_usage (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS model_usage_model ON ai.tenant_model_usage (tenant_id, model, created_at DESC);

SELECT app_admin.apply_tenant_rls(t::regclass) FROM unnest(ARRAY[
  'ai.tenant_ai_configurations', 'ai.tenant_rag_configurations', 'ai.tenant_provider_credentials',
  'ai.prompt_templates', 'ai.guardrail_events', 'ai.tenant_model_usage']) AS t;

-- Configuration: every tenant context may read the active configuration (the RAG
-- pipeline needs it); administration writes.  Platform provisioning seeds defaults.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['ai.tenant_ai_configurations', 'ai.tenant_rag_configurations', 'ai.prompt_templates'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS tenant_read ON %s', t);
    EXECUTE format($f$CREATE POLICY tenant_read ON %s FOR SELECT
                      USING (app.mode_in('user', 'tenant_admin', 'auditor', 'worker', 'platform_provisioning'))$f$, t);
    EXECUTE format('DROP POLICY IF EXISTS admin_write ON %s', t);
    EXECUTE format($f$CREATE POLICY admin_write ON %s FOR ALL
                      USING (app.mode_in('tenant_admin', 'platform_provisioning'))
                      WITH CHECK (app.mode_in('tenant_admin', 'platform_provisioning'))$f$, t);
  END LOOP;
END $$;
DROP POLICY IF EXISTS cred_admin ON ai.tenant_provider_credentials;
CREATE POLICY cred_admin ON ai.tenant_provider_credentials FOR ALL
  USING (app.mode_in('tenant_admin', 'worker', 'platform_provisioning', 'user'))
  WITH CHECK (app.mode_in('tenant_admin', 'platform_provisioning'));

-- Events / usage: any tenant context appends; admins, auditors and workers read.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['ai.guardrail_events', 'ai.tenant_model_usage'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS append ON %s', t);
    EXECUTE format($f$CREATE POLICY append ON %s FOR INSERT
                      WITH CHECK (app.mode_in('user', 'tenant_admin', 'worker', 'auditor'))$f$, t);
    EXECUTE format('DROP POLICY IF EXISTS admin_read ON %s', t);
    EXECUTE format($f$CREATE POLICY admin_read ON %s FOR SELECT USING (app.mode_in('tenant_admin', 'auditor', 'worker'))$f$, t);
  END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE ON ai.tenant_ai_configurations, ai.tenant_rag_configurations,
                                ai.tenant_provider_credentials, ai.prompt_templates TO rag_app;
GRANT DELETE ON ai.tenant_provider_credentials TO rag_app;
GRANT SELECT, INSERT ON ai.guardrail_events, ai.tenant_model_usage TO rag_app, rag_worker;
GRANT SELECT ON ai.tenant_ai_configurations, ai.tenant_rag_configurations, ai.tenant_provider_credentials,
                ai.prompt_templates TO rag_worker;
GRANT SELECT ON ai.guardrail_events, ai.tenant_model_usage, ai.tenant_ai_configurations,
                ai.tenant_rag_configurations TO rag_readonly;
