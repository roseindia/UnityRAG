-- =============================================================================
-- 09  Conversations, messages, citations (message sources), feedback,
--     search and retrieval logs  (+ their RLS policies)
-- Spec refs: 6.8, 6.10, 10.2.4, 10.6 rule 8, FR-019, FR-119/120, FR-153..FR-162,
-- FR-226, FR-247.  Owner-scoped: only the owning user reads conversations,
-- messages, sources and personal search history.  Analytics use aggregates
-- (11_audit_analytics.sql); investigators use break-glass.
-- Partitioning by month (spec 10.5.2) is deferred until measured volume
-- requires it - see docs/database/DATABASE_DESIGN.md "Partitioning".
-- =============================================================================
CREATE TABLE IF NOT EXISTS rag.conversations (
  tenant_id       uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id         uuid NOT NULL,
  title           text NOT NULL DEFAULT 'New conversation',
  context         jsonb NOT NULL DEFAULT '{}'::jsonb,   -- product, jurisdiction, as_of_date, collections
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deleted')),
  legal_hold      boolean NOT NULL DEFAULT false,
  retention_until date,
  message_count   integer NOT NULL DEFAULT 0,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  deleted_at      timestamptz,
  UNIQUE (tenant_id, conversation_id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES iam.users (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS rag.conversation_messages (
  tenant_id         uuid NOT NULL,
  message_id        uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  conversation_id   uuid NOT NULL,
  user_id           uuid NOT NULL,
  seq               integer NOT NULL,
  role              text NOT NULL CHECK (role IN ('user', 'assistant', 'notice')),
  content           text NOT NULL,                     -- protected column
  content_hash      text NOT NULL,
  answer_status     text CHECK (answer_status IN ('answered', 'abstained', 'blocked', 'error', 'needs_review')),
  evidence_strength text CHECK (evidence_strength IN ('high', 'medium', 'low', 'none')),
  rewritten_query   text,
  warnings          jsonb NOT NULL DEFAULT '[]'::jsonb,
  model_provider    text,
  model_name        text,
  prompt_version    text,
  guardrail_version text,
  rag_config_version integer,
  input_tokens      integer NOT NULL DEFAULT 0,
  output_tokens     integer NOT NULL DEFAULT 0,
  latency_ms        integer,
  correlation_id    text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, message_id),
  UNIQUE (conversation_id, seq),
  FOREIGN KEY (tenant_id, conversation_id) REFERENCES rag.conversations (tenant_id, conversation_id) ON DELETE CASCADE
);

-- Citations: link an answer to the chunk / version / page that supports it.
-- No FK to chunks: a chunk may be purged while past answers are retained (spec 10.3).
CREATE TABLE IF NOT EXISTS rag.message_sources (
  tenant_id     uuid NOT NULL,
  source_id     uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  message_id    uuid NOT NULL,
  user_id       uuid NOT NULL,
  ordinal       integer NOT NULL,
  chunk_id      uuid NOT NULL,
  document_id   uuid NOT NULL,
  version_id    uuid NOT NULL,
  title         text,
  section_path  text,
  clause_ref    text,
  page_from     integer,
  page_to       integer,
  score         real,
  verified      boolean NOT NULL DEFAULT false,
  quote_hash    text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (message_id, ordinal),
  FOREIGN KEY (tenant_id, message_id) REFERENCES rag.conversation_messages (tenant_id, message_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rag.feedback (
  tenant_id        uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  feedback_id      uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id          uuid NOT NULL,
  message_id       uuid,
  search_id        uuid,
  rating           smallint CHECK (rating IN (-1, 1)),
  category         text NOT NULL DEFAULT 'rating' CHECK (category IN
                     ('rating', 'incorrect', 'outdated', 'unsafe', 'missing_source', 'wrong_version', 'access', 'document_error', 'other')),
  comment          text,                               -- protected column
  severity         text NOT NULL DEFAULT 'low' CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  status           text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'triaged', 'in_progress', 'resolved', 'rejected')),
  assigned_to      uuid,
  resolution       text,
  golden_candidate boolean NOT NULL DEFAULT false,
  created_at       timestamptz NOT NULL DEFAULT now(),
  resolved_at      timestamptz,
  UNIQUE (tenant_id, feedback_id),
  FOREIGN KEY (tenant_id, user_id)    REFERENCES iam.users (tenant_id, user_id),
  FOREIGN KEY (tenant_id, message_id) REFERENCES rag.conversation_messages (tenant_id, message_id) ON DELETE SET NULL (message_id)
);

CREATE TABLE IF NOT EXISTS rag.search_logs (
  tenant_id         uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  search_id         uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id           uuid NOT NULL,
  department_id     uuid,
  conversation_id   uuid,
  message_id        uuid,
  mode              text NOT NULL CHECK (mode IN ('vector', 'fulltext', 'hybrid', 'chat')),
  query_hash        text NOT NULL,
  query_text        text,                              -- only when tenant policy allows (protected)
  filters           jsonb NOT NULL DEFAULT '{}'::jsonb,
  policy_scope_hash text NOT NULL,
  rag_config_version integer,
  result_count      integer NOT NULL DEFAULT 0,
  top_score         real,
  latency_ms        integer,
  cache_hit         boolean NOT NULL DEFAULT false,
  correlation_id    text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, search_id),
  FOREIGN KEY (tenant_id, user_id) REFERENCES iam.users (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS rag.retrieval_logs (
  tenant_id   uuid NOT NULL,
  retrieval_id uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  search_id   uuid NOT NULL,
  user_id     uuid NOT NULL,
  stage       text NOT NULL CHECK (stage IN ('vector', 'fulltext', 'exact', 'fused', 'reranked', 'context')),
  rank        integer NOT NULL,
  chunk_id    uuid NOT NULL,
  document_id uuid NOT NULL,
  score       real,
  selected    boolean NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, search_id) REFERENCES rag.search_logs (tenant_id, search_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS conversations_user   ON rag.conversations (tenant_id, user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS messages_conv        ON rag.conversation_messages (tenant_id, conversation_id, seq);
CREATE INDEX IF NOT EXISTS messages_time        ON rag.conversation_messages (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS sources_message      ON rag.message_sources (tenant_id, message_id);
CREATE INDEX IF NOT EXISTS sources_version      ON rag.message_sources (tenant_id, version_id);
CREATE INDEX IF NOT EXISTS feedback_queue       ON rag.feedback (tenant_id, status, created_at);
CREATE INDEX IF NOT EXISTS feedback_message     ON rag.feedback (tenant_id, message_id);
CREATE INDEX IF NOT EXISTS search_logs_user     ON rag.search_logs (tenant_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS search_logs_time     ON rag.search_logs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS search_logs_corr     ON rag.search_logs (correlation_id);
CREATE INDEX IF NOT EXISTS retrieval_logs_search ON rag.retrieval_logs (tenant_id, search_id);
CREATE INDEX IF NOT EXISTS retrieval_logs_chunk ON rag.retrieval_logs (tenant_id, chunk_id);

DROP TRIGGER IF EXISTS trg_conversations_touch ON rag.conversations;
CREATE TRIGGER trg_conversations_touch BEFORE UPDATE ON rag.conversations FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();

-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------
SELECT app_admin.apply_tenant_rls(t::regclass) FROM unnest(ARRAY[
  'rag.conversations', 'rag.conversation_messages', 'rag.message_sources', 'rag.feedback',
  'rag.search_logs', 'rag.retrieval_logs']) AS t;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['rag.conversations', 'rag.conversation_messages', 'rag.message_sources',
                           'rag.search_logs', 'rag.retrieval_logs'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS owner_all ON %s', t);
    EXECUTE format($f$CREATE POLICY owner_all ON %s FOR ALL
        USING (app.mode_in('user') AND user_id = app.current_user_id())
        WITH CHECK (app.mode_in('user') AND user_id = app.current_user_id())$f$, t);
    EXECUTE format('DROP POLICY IF EXISTS worker_all ON %s', t);
    EXECUTE format($f$CREATE POLICY worker_all ON %s FOR ALL USING (app.mode_in('worker')) WITH CHECK (app.mode_in('worker'))$f$, t);
    EXECUTE format('DROP POLICY IF EXISTS break_glass_read ON %s', t);
    EXECUTE format($f$CREATE POLICY break_glass_read ON %s FOR SELECT USING (app.break_glass_active())$f$, t);
  END LOOP;
END $$;
DROP POLICY IF EXISTS owner_all ON rag.feedback;
CREATE POLICY owner_all ON rag.feedback FOR ALL
  USING (app.mode_in('user') AND user_id = app.current_user_id())
  WITH CHECK (app.mode_in('user') AND user_id = app.current_user_id());
DROP POLICY IF EXISTS reviewer_all ON rag.feedback;
CREATE POLICY reviewer_all ON rag.feedback FOR ALL
  USING (app.mode_in('tenant_admin', 'worker', 'auditor')) WITH CHECK (app.mode_in('tenant_admin', 'worker'));

GRANT SELECT, INSERT, UPDATE ON rag.conversations, rag.conversation_messages, rag.message_sources, rag.feedback,
                                rag.search_logs, rag.retrieval_logs TO rag_app;
GRANT DELETE ON rag.conversations, rag.conversation_messages, rag.message_sources TO rag_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON rag.conversations, rag.conversation_messages, rag.message_sources,
      rag.feedback, rag.search_logs, rag.retrieval_logs TO rag_worker;
GRANT SELECT ON rag.feedback TO rag_readonly;
