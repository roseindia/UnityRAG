-- =============================================================================
-- 11  Audit (append-only, hash-chained) and analytics aggregates (+ RLS)
-- Spec refs: 15 (15 audit categories), FR-226..FR-230, NFR-057, NFR-075,
-- FR-216..FR-224, extension section 10.
-- =============================================================================
CREATE TABLE IF NOT EXISTS audit.tenant_audit_logs (
  tenant_id        uuid NOT NULL,                 -- logical reference only (records outlive entities)
  event_id         uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  seq              bigint GENERATED ALWAYS AS IDENTITY,
  occurred_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
  category         text NOT NULL CHECK (category IN
                     ('authentication', 'authorization', 'document_access', 'search', 'retrieval', 'answer',
                      'model_call', 'prompt', 'guardrail', 'feedback', 'ingestion', 'document_update',
                      'document_deletion', 'configuration', 'administration', 'security')),
  event_type       text NOT NULL,
  outcome          text NOT NULL DEFAULT 'success' CHECK (outcome IN ('success', 'failure', 'denied')),
  actor_type       text NOT NULL DEFAULT 'user' CHECK (actor_type IN ('user', 'service', 'platform_admin', 'system')),
  actor_user_id    uuid,
  actor_account_id uuid,
  resource_type    text,
  resource_id      text,
  correlation_id   text,
  source_ip        inet,
  detail           jsonb NOT NULL DEFAULT '{}'::jsonb,   -- identifiers and hashes, never sensitive content
  prev_hash        text,
  hash             text
);
CREATE INDEX IF NOT EXISTS audit_tenant_time     ON audit.tenant_audit_logs (tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS audit_tenant_category ON audit.tenant_audit_logs (tenant_id, category, occurred_at DESC);
CREATE INDEX IF NOT EXISTS audit_tenant_actor    ON audit.tenant_audit_logs (tenant_id, actor_user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS audit_corr            ON audit.tenant_audit_logs (tenant_id, correlation_id);
CREATE INDEX IF NOT EXISTS audit_seq             ON audit.tenant_audit_logs (tenant_id, seq);

CREATE TABLE IF NOT EXISTS audit.chain_heads (
  chain_key  text PRIMARY KEY,           -- tenant uuid, or 'platform'
  last_hash  text NOT NULL,
  last_seq   bigint NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Hash chain (FR-229): each event's hash covers the previous hash and the
-- event's immutable fields.  The trigger serialises writers per chain with a
-- row lock on the chain head.  SECURITY DEFINER (owner rag_audit_fn) so that
-- services need no access to chain_heads; search_path pinned.
CREATE OR REPLACE FUNCTION audit.chain_hash() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  v_key  text;
  v_prev text;
BEGIN
  IF TG_TABLE_NAME = 'tenant_audit_logs' THEN
    v_key := NEW.tenant_id::text;
  ELSE
    v_key := 'platform';
  END IF;
  INSERT INTO audit.chain_heads (chain_key, last_hash) VALUES (v_key, 'GENESIS') ON CONFLICT (chain_key) DO NOTHING;
  SELECT last_hash INTO v_prev FROM audit.chain_heads WHERE chain_key = v_key FOR UPDATE;
  NEW.prev_hash := v_prev;
  IF TG_TABLE_NAME = 'tenant_audit_logs' THEN
    NEW.hash := encode(public.digest(concat_ws('|', v_prev, NEW.event_id::text, NEW.tenant_id::text,
                  to_char(NEW.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'), NEW.category,
                  NEW.event_type, NEW.outcome, coalesce(NEW.actor_user_id::text, ''),
                  coalesce(NEW.resource_type, ''), coalesce(NEW.resource_id, ''), NEW.detail::text), 'sha256'), 'hex');
  ELSE
    NEW.hash := encode(public.digest(concat_ws('|', v_prev, NEW.event_id::text, coalesce(NEW.target_tenant_id::text, ''),
                  to_char(NEW.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'), NEW.category,
                  NEW.action, NEW.outcome, coalesce(NEW.actor_account_id::text, ''),
                  coalesce(NEW.target_type, ''), coalesce(NEW.target_id, ''), NEW.detail::text), 'sha256'), 'hex');
  END IF;
  UPDATE audit.chain_heads SET last_hash = NEW.hash, last_seq = last_seq + 1, updated_at = now() WHERE chain_key = v_key;
  RETURN NEW;
END $$;
GRANT USAGE, CREATE ON SCHEMA audit TO rag_audit_fn;
ALTER FUNCTION audit.chain_hash() OWNER TO rag_audit_fn;
REVOKE CREATE ON SCHEMA audit FROM rag_audit_fn;
REVOKE ALL ON FUNCTION audit.chain_hash() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_tenant_audit_chain ON audit.tenant_audit_logs;
CREATE TRIGGER trg_tenant_audit_chain BEFORE INSERT ON audit.tenant_audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit.chain_hash();
DROP TRIGGER IF EXISTS trg_platform_audit_chain ON platform.platform_audit_logs;
CREATE TRIGGER trg_platform_audit_chain BEFORE INSERT ON platform.platform_audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit.chain_hash();

-- Immutability guard even for the owner role: updates and deletes are refused.
CREATE OR REPLACE FUNCTION audit.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit records are append-only' USING ERRCODE = 'insufficient_privilege'; END $$;
DROP TRIGGER IF EXISTS trg_tenant_audit_immutable ON audit.tenant_audit_logs;
CREATE TRIGGER trg_tenant_audit_immutable BEFORE UPDATE OR DELETE ON audit.tenant_audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit.refuse_mutation();
DROP TRIGGER IF EXISTS trg_platform_audit_immutable ON platform.platform_audit_logs;
CREATE TRIGGER trg_platform_audit_immutable BEFORE UPDATE OR DELETE ON platform.platform_audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit.refuse_mutation();
-- TRUNCATE bypasses row triggers, so it gets its own statement-level guard
-- (blocks the owner role too; only an explicit, audited DBA change can drop it).
DROP TRIGGER IF EXISTS trg_tenant_audit_no_truncate ON audit.tenant_audit_logs;
CREATE TRIGGER trg_tenant_audit_no_truncate BEFORE TRUNCATE ON audit.tenant_audit_logs
  FOR EACH STATEMENT EXECUTE FUNCTION audit.refuse_mutation();
DROP TRIGGER IF EXISTS trg_platform_audit_no_truncate ON platform.platform_audit_logs;
CREATE TRIGGER trg_platform_audit_no_truncate BEFORE TRUNCATE ON platform.platform_audit_logs
  FOR EACH STATEMENT EXECUTE FUNCTION audit.refuse_mutation();

ALTER TABLE audit.chain_heads ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit.chain_heads FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS chain_fn ON audit.chain_heads;
CREATE POLICY chain_fn ON audit.chain_heads FOR ALL TO rag_audit_fn USING (true) WITH CHECK (true);
GRANT USAGE ON SCHEMA audit TO rag_audit_fn;
GRANT SELECT, INSERT, UPDATE ON audit.chain_heads TO rag_audit_fn;

-- Integrity verification (FR-229): recomputes the chain for the current tenant.
CREATE OR REPLACE FUNCTION audit.verify_tenant_chain() RETURNS TABLE (ok boolean, checked bigint, first_broken_event uuid)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  r record; v_prev text := 'GENESIS'; v_hash text; n bigint := 0;
BEGIN
  FOR r IN SELECT * FROM audit.tenant_audit_logs WHERE tenant_id = app.current_tenant_id() ORDER BY seq LOOP
    n := n + 1;
    v_hash := encode(public.digest(concat_ws('|', v_prev, r.event_id::text, r.tenant_id::text,
                to_char(r.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'), r.category,
                r.event_type, r.outcome, coalesce(r.actor_user_id::text, ''),
                coalesce(r.resource_type, ''), coalesce(r.resource_id, ''), r.detail::text), 'sha256'), 'hex');
    IF r.prev_hash IS DISTINCT FROM v_prev OR r.hash IS DISTINCT FROM v_hash THEN
      RETURN QUERY SELECT false, n, r.event_id; RETURN;
    END IF;
    v_prev := r.hash;
  END LOOP;
  RETURN QUERY SELECT true, n, NULL::uuid;
END $$;

SELECT app_admin.apply_tenant_rls('audit.tenant_audit_logs'::regclass);
DROP POLICY IF EXISTS audit_append ON audit.tenant_audit_logs;
CREATE POLICY audit_append ON audit.tenant_audit_logs FOR INSERT
  WITH CHECK (app.mode_in('user', 'tenant_admin', 'auditor', 'worker', 'platform_provisioning', 'break_glass'));
DROP POLICY IF EXISTS audit_read ON audit.tenant_audit_logs;
CREATE POLICY audit_read ON audit.tenant_audit_logs FOR SELECT USING (app.mode_in('tenant_admin', 'auditor'));
GRANT INSERT ON audit.tenant_audit_logs TO rag_app, rag_worker;
GRANT SELECT ON audit.tenant_audit_logs TO rag_app, rag_readonly;
-- Deliberately NO UPDATE / DELETE grants on audit tables for any service role.

-- -----------------------------------------------------------------------------
-- Analytics aggregates, produced by the scheduled aggregation job per tenant
-- (one validated tenant context per tenant).  Dashboards read these instead of
-- scanning conversations / documents on every page load.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops.tenant_usage_daily (
  tenant_id            uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  usage_date           date NOT NULL,
  searches             integer NOT NULL DEFAULT 0,
  chats                integer NOT NULL DEFAULT 0,
  conversations_started integer NOT NULL DEFAULT 0,
  ai_requests          integer NOT NULL DEFAULT 0,
  input_tokens         bigint  NOT NULL DEFAULT 0,
  output_tokens        bigint  NOT NULL DEFAULT 0,
  estimated_cost       numeric(14,6) NOT NULL DEFAULT 0,
  documents_ingested   integer NOT NULL DEFAULT 0,
  ingestion_failures   integer NOT NULL DEFAULT 0,
  active_users         integer NOT NULL DEFAULT 0,
  avg_search_latency_ms integer,
  avg_llm_latency_ms   integer,
  abstentions          integer NOT NULL DEFAULT 0,
  feedback_positive    integer NOT NULL DEFAULT 0,
  feedback_negative    integer NOT NULL DEFAULT 0,
  guardrail_blocks     integer NOT NULL DEFAULT 0,
  documents_total      integer NOT NULL DEFAULT 0,
  chunks_total         bigint  NOT NULL DEFAULT 0,
  storage_bytes        bigint  NOT NULL DEFAULT 0,
  users_total          integer NOT NULL DEFAULT 0,
  computed_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, usage_date)
);

CREATE TABLE IF NOT EXISTS ops.department_usage_daily (
  tenant_id      uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  usage_date     date NOT NULL,
  department_id  uuid NOT NULL,
  searches       integer NOT NULL DEFAULT 0,
  chats          integer NOT NULL DEFAULT 0,
  input_tokens   bigint  NOT NULL DEFAULT 0,
  output_tokens  bigint  NOT NULL DEFAULT 0,
  estimated_cost numeric(14,6) NOT NULL DEFAULT 0,
  active_users   integer NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, usage_date, department_id)
);

CREATE TABLE IF NOT EXISTS ops.user_activity_daily (
  tenant_id      uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  usage_date     date NOT NULL,
  user_id        uuid NOT NULL,
  searches       integer NOT NULL DEFAULT 0,
  chats          integer NOT NULL DEFAULT 0,
  tokens         bigint  NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, usage_date, user_id)
);

-- tenant_usage_daily holds no user- or content-level data: platform readers may
-- see all tenants' aggregates; tenants see their own.
ALTER TABLE ops.tenant_usage_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.tenant_usage_daily FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS usage_read ON ops.tenant_usage_daily;
CREATE POLICY usage_read ON ops.tenant_usage_daily FOR SELECT USING (
  (tenant_id = app.current_tenant_id() AND app.mode_in('tenant_admin', 'auditor', 'worker')) OR app.is_platform_reader());
DROP POLICY IF EXISTS usage_write ON ops.tenant_usage_daily;
CREATE POLICY usage_write ON ops.tenant_usage_daily FOR ALL
  USING (tenant_id = app.current_tenant_id() AND app.mode_in('worker'))
  WITH CHECK (tenant_id = app.current_tenant_id() AND app.mode_in('worker'));

SELECT app_admin.apply_tenant_rls(t::regclass) FROM unnest(ARRAY['ops.department_usage_daily', 'ops.user_activity_daily']) AS t;
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['ops.department_usage_daily', 'ops.user_activity_daily'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS admin_read ON %s', t);
    EXECUTE format($f$CREATE POLICY admin_read ON %s FOR SELECT USING (app.mode_in('tenant_admin', 'auditor', 'worker'))$f$, t);
    EXECUTE format('DROP POLICY IF EXISTS worker_write ON %s', t);
    EXECUTE format($f$CREATE POLICY worker_write ON %s FOR ALL USING (app.mode_in('worker')) WITH CHECK (app.mode_in('worker'))$f$, t);
  END LOOP;
END $$;

GRANT SELECT ON ops.tenant_usage_daily, ops.department_usage_daily, ops.user_activity_daily TO rag_app, rag_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON ops.tenant_usage_daily, ops.department_usage_daily, ops.user_activity_daily TO rag_worker;
