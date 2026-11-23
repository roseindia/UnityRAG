-- =============================================================================
-- 12  RAG evaluation datasets, questions, runs and results (+ RLS)
-- Spec refs: 6.13 (FR-200..FR-215), 14, 10.2.5 (#27, #28).
-- =============================================================================
CREATE TABLE IF NOT EXISTS eval.evaluation_datasets (
  tenant_id   uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  dataset_id  uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  name        text NOT NULL,
  version     integer NOT NULL DEFAULT 1,
  purpose     text NOT NULL DEFAULT 'retrieval' CHECK (purpose IN ('retrieval', 'generation', 'safety', 'access', 'regression')),
  description text,
  status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'retired')),
  created_by  uuid,
  approved_by uuid,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, dataset_id),
  UNIQUE (tenant_id, name, version),
  CHECK (approved_by IS NULL OR approved_by <> created_by)
);

CREATE TABLE IF NOT EXISTS eval.evaluation_questions (
  tenant_id            uuid NOT NULL,
  question_id          uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  dataset_id           uuid NOT NULL,
  question             text NOT NULL,
  expected_answer      text,
  expected_document_ids uuid[] NOT NULL DEFAULT '{}',
  expected_chunk_ids   uuid[] NOT NULL DEFAULT '{}',
  answerable           boolean NOT NULL DEFAULT true,
  category             text,
  line_of_business     text,
  jurisdiction         text,
  difficulty           text CHECK (difficulty IS NULL OR difficulty IN ('easy', 'medium', 'hard')),
  is_critical          boolean NOT NULL DEFAULT false,
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, question_id),
  FOREIGN KEY (tenant_id, dataset_id) REFERENCES eval.evaluation_datasets (tenant_id, dataset_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS eval.evaluation_runs (
  tenant_id       uuid NOT NULL,
  run_id          uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  dataset_id      uuid NOT NULL,
  status          text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
  mode            text NOT NULL DEFAULT 'retrieval' CHECK (mode IN ('retrieval', 'end_to_end')),
  k               integer NOT NULL DEFAULT 10,
  config_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,   -- AI + RAG config versions, models, index generation (FR-213)
  evaluator_user_id uuid,                               -- persona whose permissions the run uses
  summary         jsonb NOT NULL DEFAULT '{}'::jsonb,
  gate_passed     boolean,
  initiated_by    uuid,
  started_at      timestamptz,
  finished_at     timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, run_id),
  FOREIGN KEY (tenant_id, dataset_id) REFERENCES eval.evaluation_datasets (tenant_id, dataset_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS eval.evaluation_results (
  tenant_id          uuid NOT NULL,
  result_id          uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  run_id             uuid NOT NULL,
  question_id        uuid NOT NULL,
  retrieved_chunk_ids uuid[] NOT NULL DEFAULT '{}',
  retrieved_document_ids uuid[] NOT NULL DEFAULT '{}',
  metrics            jsonb NOT NULL DEFAULT '{}'::jsonb,
  answer_status      text,
  passed             boolean,
  latency_ms         integer,
  created_at         timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, run_id)      REFERENCES eval.evaluation_runs (tenant_id, run_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, question_id) REFERENCES eval.evaluation_questions (tenant_id, question_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS eval_results_run ON eval.evaluation_results (tenant_id, run_id);
CREATE INDEX IF NOT EXISTS eval_runs_dataset ON eval.evaluation_runs (tenant_id, dataset_id, created_at DESC);

SELECT app_admin.apply_tenant_rls(t::regclass) FROM unnest(ARRAY[
  'eval.evaluation_datasets', 'eval.evaluation_questions', 'eval.evaluation_runs', 'eval.evaluation_results']) AS t;
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['eval.evaluation_datasets', 'eval.evaluation_questions', 'eval.evaluation_runs',
                           'eval.evaluation_results'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS evaluator_all ON %s', t);
    EXECUTE format($f$CREATE POLICY evaluator_all ON %s FOR ALL
                      USING (app.mode_in('tenant_admin', 'worker', 'auditor'))
                      WITH CHECK (app.mode_in('tenant_admin', 'worker'))$f$, t);
  END LOOP;
END $$;
GRANT SELECT, INSERT, UPDATE ON eval.evaluation_datasets, eval.evaluation_questions, eval.evaluation_runs,
                                eval.evaluation_results TO rag_app;
GRANT DELETE ON eval.evaluation_questions TO rag_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON eval.evaluation_datasets, eval.evaluation_questions, eval.evaluation_runs,
      eval.evaluation_results TO rag_worker;
GRANT SELECT ON eval.evaluation_datasets, eval.evaluation_runs, eval.evaluation_results TO rag_readonly;
