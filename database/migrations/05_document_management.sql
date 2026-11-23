-- =============================================================================
-- 05  Document management: collections, documents, versions, metadata,
--     access rules, pages, ingestion jobs and logs.
-- Spec refs: 6.3, 6.4, 6.16, 10.2.2, 10.2.3, FR-039/040/045/047/049/050/051,
-- FR-167, FR-249..FR-256.
-- Classification rank: public 0, internal 1, confidential 2, restricted 3.
-- =============================================================================
CREATE TABLE IF NOT EXISTS content.collections (
  tenant_id          uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  collection_id      uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  code               text NOT NULL CHECK (code ~ '^[a-z0-9][a-z0-9_-]{1,59}$'),
  name               text NOT NULL,
  description        text,
  department_id      uuid,
  owner_user_id      uuid,
  line_of_business   text,
  jurisdictions      text[] NOT NULL DEFAULT '{}',
  classification     text NOT NULL DEFAULT 'internal' CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
  retention_days     integer CHECK (retention_days IS NULL OR retention_days > 0),
  auto_publish       boolean NOT NULL DEFAULT true,     -- false => owner approval before publication (FR-047/251)
  status             text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
  created_by         uuid,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, collection_id),
  UNIQUE (tenant_id, code),
  FOREIGN KEY (tenant_id, department_id) REFERENCES iam.departments (tenant_id, department_id),
  FOREIGN KEY (tenant_id, owner_user_id) REFERENCES iam.users (tenant_id, user_id)
);

-- Collection-level entitlements; documents inherit them (plus their own rules).
-- principal_type 'everyone' => principal_id is NULL and maps to the tenant principal.
CREATE TABLE IF NOT EXISTS content.collection_access (
  tenant_id      uuid NOT NULL,
  access_id      uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  collection_id  uuid NOT NULL,
  principal_type text NOT NULL CHECK (principal_type IN ('user', 'group', 'role', 'department', 'team', 'everyone')),
  principal_id   uuid,
  effect         text NOT NULL DEFAULT 'allow' CHECK (effect IN ('allow', 'deny')),
  permission     text NOT NULL DEFAULT 'read' CHECK (permission IN ('read', 'write', 'manage')),
  granted_by     uuid,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CHECK ((principal_type = 'everyone') = (principal_id IS NULL)),
  UNIQUE NULLS NOT DISTINCT (tenant_id, collection_id, principal_type, principal_id, effect, permission),
  FOREIGN KEY (tenant_id, collection_id) REFERENCES content.collections (tenant_id, collection_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS content.documents (
  tenant_id          uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  document_id        uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  collection_id      uuid NOT NULL,
  title              text NOT NULL,
  document_type      text NOT NULL DEFAULT 'other' CHECK (document_type IN
                       ('policy_wording', 'policy_schedule', 'endorsement', 'claims_manual', 'underwriting_guideline',
                        'product_brochure', 'regulatory_circular', 'sop', 'customer_communication',
                        'authority_matrix', 'faq', 'other')),
  classification_confidence real,
  insurance_line     text,          -- line of business (motor, home, health, life, ...)
  product            text,
  jurisdictions      text[] NOT NULL DEFAULT '{}',
  language           text NOT NULL DEFAULT 'english',
  classification     text NOT NULL DEFAULT 'internal' CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
  classification_rank smallint NOT NULL DEFAULT 1 CHECK (classification_rank BETWEEN 0 AND 3),
  lifecycle_state    text NOT NULL DEFAULT 'draft' CHECK (lifecycle_state IN
                       ('draft', 'processing', 'in_review', 'approved', 'published', 'superseded', 'expired',
                        'archived', 'withdrawn', 'quarantined', 'failed')),
  owner_user_id      uuid,
  department_id      uuid,
  current_version_id uuid,
  legal_hold         boolean NOT NULL DEFAULT false,
  legally_privileged boolean NOT NULL DEFAULT false,
  source_system      text NOT NULL DEFAULT 'upload',
  source_ref         text,
  checksum_sha256    text,
  size_bytes         bigint NOT NULL DEFAULT 0,
  mime_type          text,
  effective_from     date,
  effective_to       date,
  review_due_at      date,
  retention_until    date,
  -- Effective access, denormalised from collection_access + document_access by
  -- app.refresh_document_acl() and copied to every chunk / embedding (FR-045, FR-112).
  allow_principals   uuid[] NOT NULL DEFAULT '{}',
  deny_principals    uuid[] NOT NULL DEFAULT '{}',
  acl_fingerprint    text,
  duplicate_of       uuid,
  created_by         uuid,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  deleted_at         timestamptz,
  UNIQUE (tenant_id, document_id),
  CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from),
  FOREIGN KEY (tenant_id, collection_id) REFERENCES content.collections (tenant_id, collection_id) ON DELETE RESTRICT,
  FOREIGN KEY (tenant_id, owner_user_id) REFERENCES iam.users (tenant_id, user_id),
  FOREIGN KEY (tenant_id, department_id) REFERENCES iam.departments (tenant_id, department_id),
  FOREIGN KEY (tenant_id, duplicate_of)  REFERENCES content.documents (tenant_id, document_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS documents_source_ref_uq
  ON content.documents (tenant_id, source_system, source_ref) WHERE source_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS content.document_versions (
  tenant_id             uuid NOT NULL,
  version_id            uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  document_id           uuid NOT NULL,
  version_seq           integer NOT NULL CHECK (version_seq > 0),
  version_label         text,
  original_filename     text NOT NULL,
  storage_uri           text NOT NULL,   -- tenant-prefixed key, generated server side
  checksum_sha256       text NOT NULL CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes            bigint NOT NULL CHECK (size_bytes >= 0),
  mime_type             text NOT NULL,
  detected_format       text,
  effective_from        date,
  effective_to          date,
  supersedes_version_id uuid,
  state                 text NOT NULL DEFAULT 'uploaded' CHECK (state IN
                          ('uploaded', 'processing', 'indexed', 'published', 'superseded', 'withdrawn', 'failed', 'quarantined')),
  page_count            integer,
  parser                text,
  ocr_applied           boolean NOT NULL DEFAULT false,
  extraction_confidence real,
  chunker_version       text,
  embedding_model       text,
  embedding_dimensions  integer,
  created_by            uuid,
  created_at            timestamptz NOT NULL DEFAULT now(),
  published_at          timestamptz,
  withdrawn_at          timestamptz,
  UNIQUE (tenant_id, version_id),
  UNIQUE (document_id, version_seq),
  FOREIGN KEY (tenant_id, document_id) REFERENCES content.documents (tenant_id, document_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, supersedes_version_id) REFERENCES content.document_versions (tenant_id, version_id)
);

ALTER TABLE content.documents DROP CONSTRAINT IF EXISTS documents_current_version_fk;
ALTER TABLE content.documents ADD CONSTRAINT documents_current_version_fk
  FOREIGN KEY (tenant_id, current_version_id) REFERENCES content.document_versions (tenant_id, version_id)
  DEFERRABLE INITIALLY DEFERRED;

-- Typed key/value metadata per version, incl. insurance metadata
-- (policy_number, claim_number, coverage_type, sum_insured, deductible,
-- waiting_period, exclusion, effective_date, expiration_date, jurisdiction ...).
CREATE TABLE IF NOT EXISTS content.document_metadata (
  tenant_id   uuid NOT NULL,
  version_id  uuid NOT NULL,
  key         text NOT NULL CHECK (key ~ '^[a-z][a-z0-9_]{1,60}$'),
  value       text NOT NULL,
  source      text NOT NULL DEFAULT 'extracted' CHECK (source IN ('extracted', 'user', 'source_system', 'steward', 'rule')),
  confidence  real,
  validated   boolean NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (version_id, key, value),
  FOREIGN KEY (tenant_id, version_id) REFERENCES content.document_versions (tenant_id, version_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS content.document_access (
  tenant_id      uuid NOT NULL,
  access_id      uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  document_id    uuid NOT NULL,
  principal_type text NOT NULL CHECK (principal_type IN ('user', 'group', 'role', 'department', 'team', 'everyone')),
  principal_id   uuid,
  effect         text NOT NULL DEFAULT 'allow' CHECK (effect IN ('allow', 'deny')),
  origin         text NOT NULL DEFAULT 'platform_policy' CHECK (origin IN ('source_acl', 'platform_policy')),
  granted_by     uuid,
  synced_at      timestamptz NOT NULL DEFAULT now(),
  CHECK ((principal_type = 'everyone') = (principal_id IS NULL)),
  UNIQUE NULLS NOT DISTINCT (tenant_id, document_id, principal_type, principal_id, effect),
  FOREIGN KEY (tenant_id, document_id) REFERENCES content.documents (tenant_id, document_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS content.document_pages (
  tenant_id      uuid NOT NULL,
  page_id        uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  version_id     uuid NOT NULL,
  document_id    uuid NOT NULL,
  page_number    integer NOT NULL CHECK (page_number > 0),
  page_label     text,
  text           text NOT NULL DEFAULT '',
  extraction     text NOT NULL DEFAULT 'text' CHECK (extraction IN ('text', 'ocr', 'table', 'mixed')),
  ocr_confidence real,
  low_confidence boolean NOT NULL DEFAULT false,
  char_count     integer NOT NULL DEFAULT 0,
  UNIQUE (tenant_id, page_id),
  UNIQUE (version_id, page_number),
  FOREIGN KEY (tenant_id, version_id)  REFERENCES content.document_versions (tenant_id, version_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, document_id) REFERENCES content.documents (tenant_id, document_id) ON DELETE CASCADE
);

-- Ingestion ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest.ingestion_jobs (
  tenant_id       uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  job_id          uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  document_id     uuid,
  version_id      uuid,
  job_type        text NOT NULL DEFAULT 'ingest' CHECK (job_type IN ('ingest', 'reprocess', 'reindex', 'reembed', 'delete')),
  status          text NOT NULL DEFAULT 'queued' CHECK (status IN
                    ('queued', 'running', 'succeeded', 'failed', 'retrying', 'dead_letter', 'cancelled', 'deferred')),
  stage           text NOT NULL DEFAULT 'queued',
  attempt         integer NOT NULL DEFAULT 0,
  max_attempts    integer NOT NULL DEFAULT 5,
  priority        smallint NOT NULL DEFAULT 5,
  idempotency_key text NOT NULL,
  initiated_by    uuid,           -- tenant user id
  correlation_id  text,
  task_id         text,
  error_code      text,
  error_message   text,           -- never contains document content (spec 10.2.3)
  stats           jsonb NOT NULL DEFAULT '{}'::jsonb,
  queued_at       timestamptz NOT NULL DEFAULT now(),
  started_at      timestamptz,
  finished_at     timestamptz,
  next_retry_at   timestamptz,
  UNIQUE (tenant_id, job_id),
  UNIQUE (tenant_id, idempotency_key),
  FOREIGN KEY (tenant_id, document_id) REFERENCES content.documents (tenant_id, document_id) ON DELETE SET NULL (document_id),
  FOREIGN KEY (tenant_id, version_id)  REFERENCES content.document_versions (tenant_id, version_id) ON DELETE SET NULL (version_id)
);

CREATE TABLE IF NOT EXISTS ingest.ingestion_job_logs (
  tenant_id  uuid NOT NULL,
  log_id     uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  job_id     uuid NOT NULL,
  stage      text NOT NULL,
  level      text NOT NULL DEFAULT 'info' CHECK (level IN ('debug', 'info', 'warning', 'error')),
  message    text NOT NULL,
  detail     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY (tenant_id, job_id) REFERENCES ingest.ingestion_jobs (tenant_id, job_id) ON DELETE CASCADE
);

DROP TRIGGER IF EXISTS trg_documents_touch ON content.documents;
CREATE TRIGGER trg_documents_touch BEFORE UPDATE ON content.documents FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
DROP TRIGGER IF EXISTS trg_collections_touch ON content.collections;
CREATE TRIGGER trg_collections_touch BEFORE UPDATE ON content.collections FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at();
