-- =============================================================================
-- 06  Document chunks and embeddings (pgvector) + effective-ACL propagation
-- Spec refs: 6.5, 6.6, 10.2.2 (#14, #15), 10.4, 10.6 rules 6-7, FR-041..FR-045,
-- FR-074, FR-078, FR-080, FR-081, FR-087, FR-112, NFR-112.
--
-- Embedding storage: the column type is the dimension-less `vector`, and one
-- partial HNSW expression index exists per supported dimension (see
-- 08_search_indexes.sql).  Queries cast both sides to vector(N) and filter on
-- `dimensions = N`, so tenants may use different embedding models while every
-- vector search still uses an ANN index and never mixes incompatible vectors.
-- =============================================================================
CREATE TABLE IF NOT EXISTS content.document_chunks (
  tenant_id           uuid NOT NULL REFERENCES platform.tenants(tenant_id) ON DELETE RESTRICT,
  chunk_id            uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  document_id         uuid NOT NULL,
  version_id          uuid NOT NULL,
  collection_id       uuid NOT NULL,
  parent_chunk_id     uuid,
  chunk_index         integer NOT NULL CHECK (chunk_index >= 0),
  chunk_type          text NOT NULL DEFAULT 'text' CHECK (chunk_type IN ('text', 'table', 'parent', 'child', 'definition', 'faq')),
  title               text,
  section_path        text,
  clause_ref          text,
  page_from           integer,
  page_to             integer,
  content             text NOT NULL,
  identifiers         text NOT NULL DEFAULT '',   -- extracted policy/claim/form/clause numbers (exact search)
  fts_config          regconfig NOT NULL DEFAULT 'english',
  content_tsv         tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector(fts_config, coalesce(title, '') || ' ' || coalesce(section_path, '')), 'A') ||
                        setweight(to_tsvector('simple'::regconfig, identifiers), 'A') ||
                        setweight(to_tsvector(fts_config, content), 'B')) STORED,
  token_count         integer NOT NULL DEFAULT 0,
  content_hash        text NOT NULL,
  low_confidence      boolean NOT NULL DEFAULT false,     -- OCR below threshold (FR-066)
  injection_flag      boolean NOT NULL DEFAULT false,     -- instruction-like content detected (FR-136)
  sensitivity_tags    text[] NOT NULL DEFAULT '{}',       -- pii, health, financial ... (FR-237)
  -- denormalised filter / access attributes (no joins on the retrieval path)
  document_type       text NOT NULL DEFAULT 'other',
  line_of_business    text,
  product             text,
  jurisdictions       text[] NOT NULL DEFAULT '{}',
  classification_rank smallint NOT NULL DEFAULT 1,
  lifecycle_state     text NOT NULL DEFAULT 'processing',
  effective_from      date,
  effective_to        date,
  allow_principals    uuid[] NOT NULL DEFAULT '{}',
  deny_principals     uuid[] NOT NULL DEFAULT '{}',
  acl_fingerprint     text,
  lineage             jsonb NOT NULL DEFAULT '{}'::jsonb,  -- parser, chunker, extraction method (NFR-112)
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, chunk_id),
  UNIQUE (version_id, chunk_index),
  FOREIGN KEY (tenant_id, document_id)     REFERENCES content.documents (tenant_id, document_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, version_id)      REFERENCES content.document_versions (tenant_id, version_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, collection_id)   REFERENCES content.collections (tenant_id, collection_id),
  FOREIGN KEY (tenant_id, parent_chunk_id) REFERENCES content.document_chunks (tenant_id, chunk_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS content.chunk_embeddings (
  tenant_id           uuid NOT NULL,
  embedding_id        uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  chunk_id            uuid NOT NULL,
  document_id         uuid NOT NULL,
  model_name          text NOT NULL,
  dimensions          integer NOT NULL CHECK (dimensions IN (256, 384, 512, 768, 1024, 1536, 3072)),
  index_generation    integer NOT NULL DEFAULT 1,
  is_active           boolean NOT NULL DEFAULT true,
  embedding           vector NOT NULL,
  -- copies of the access attributes so ANN search applies the same RLS predicate
  classification_rank smallint NOT NULL DEFAULT 1,
  line_of_business    text,
  jurisdictions       text[] NOT NULL DEFAULT '{}',
  lifecycle_state     text NOT NULL DEFAULT 'processing',
  allow_principals    uuid[] NOT NULL DEFAULT '{}',
  deny_principals     uuid[] NOT NULL DEFAULT '{}',
  created_at          timestamptz NOT NULL DEFAULT now(),
  CHECK (vector_dims(embedding) = dimensions),
  UNIQUE (chunk_id, model_name, index_generation),
  FOREIGN KEY (tenant_id, chunk_id)    REFERENCES content.document_chunks (tenant_id, chunk_id) ON DELETE CASCADE,
  FOREIGN KEY (tenant_id, document_id) REFERENCES content.documents (tenant_id, document_id) ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- Effective access computation (FR-045, FR-101, FR-102, FR-112).
--   allow = document-level allow rules when the document has any, otherwise the
--           collection's read/write/manage allow rules (documents can narrow,
--           never silently widen, the collection default);
--   deny  = union of collection and document deny rules (deny overrides allow).
-- 'everyone' maps to the tenant principal (tenant_id), which every member of
-- the tenant carries in app.current_principals.
-- SECURITY DEFINER, owned by the NOLOGIN role rag_acl_fn whose only policies
-- are on the ACL columns' tables; FORCE RLS keeps the RESTRICTIVE tenant policy
-- in effect, so the function can only touch rows of the caller's tenant.  It
-- returns only a fingerprint (no content) and then copies the result and the document's filter attributes to every chunk
-- and embedding, so a chunk can never be more visible than its document.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app.refresh_document_acl(p_document_id uuid) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
  d content.documents%ROWTYPE;
  v_allow uuid[];
  v_deny  uuid[];
  v_fp    text;
BEGIN
  -- Narrow definer: only administrative / worker contexts may trigger propagation,
  -- the tenant boundary still comes from the caller's transaction-local context.
  IF app.current_tenant_id() IS NULL OR NOT app.mode_in('tenant_admin', 'worker', 'platform_provisioning') THEN
    RAISE EXCEPTION 'refresh_document_acl requires an administrative or worker tenant context'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  SELECT * INTO d FROM content.documents WHERE document_id = p_document_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'document % not found in current tenant context', p_document_id USING ERRCODE = 'no_data_found';
  END IF;

  IF EXISTS (SELECT 1 FROM content.document_access a WHERE a.document_id = d.document_id AND a.effect = 'allow') THEN
    SELECT COALESCE(array_agg(DISTINCT COALESCE(a.principal_id, d.tenant_id) ORDER BY COALESCE(a.principal_id, d.tenant_id)), '{}')
      INTO v_allow FROM content.document_access a WHERE a.document_id = d.document_id AND a.effect = 'allow';
  ELSE
    SELECT COALESCE(array_agg(DISTINCT COALESCE(c.principal_id, d.tenant_id) ORDER BY COALESCE(c.principal_id, d.tenant_id)), '{}')
      INTO v_allow FROM content.collection_access c WHERE c.collection_id = d.collection_id AND c.effect = 'allow';
  END IF;

  SELECT COALESCE(array_agg(DISTINCT p ORDER BY p), '{}') INTO v_deny FROM (
      SELECT COALESCE(a.principal_id, d.tenant_id) AS p FROM content.document_access a
       WHERE a.document_id = d.document_id AND a.effect = 'deny'
      UNION
      SELECT COALESCE(c.principal_id, d.tenant_id) FROM content.collection_access c
       WHERE c.collection_id = d.collection_id AND c.effect = 'deny') s;

  v_fp := md5(array_to_string(v_allow, ',') || '|' || array_to_string(v_deny, ',') || '|' ||
              d.classification_rank || '|' || coalesce(d.insurance_line, '') || '|' ||
              array_to_string(d.jurisdictions, ',') || '|' || d.lifecycle_state);

  UPDATE content.documents SET allow_principals = v_allow, deny_principals = v_deny, acl_fingerprint = v_fp
   WHERE document_id = d.document_id;

  UPDATE content.document_chunks c
     SET allow_principals = v_allow, deny_principals = v_deny, acl_fingerprint = v_fp,
         classification_rank = d.classification_rank, line_of_business = d.insurance_line,
         jurisdictions = d.jurisdictions, document_type = d.document_type, product = d.product,
         effective_from = d.effective_from, effective_to = d.effective_to,
         lifecycle_state = CASE WHEN c.version_id = d.current_version_id THEN d.lifecycle_state
                                WHEN d.lifecycle_state IN ('published', 'superseded') AND EXISTS (
                                     SELECT 1 FROM content.document_versions v
                                      WHERE v.version_id = c.version_id AND v.state = 'superseded') THEN 'superseded'
                                WHEN d.lifecycle_state IN ('withdrawn', 'archived', 'expired') THEN d.lifecycle_state
                                ELSE 'processing' END
   WHERE c.document_id = d.document_id;

  UPDATE content.chunk_embeddings e
     SET allow_principals = c.allow_principals, deny_principals = c.deny_principals,
         classification_rank = c.classification_rank, line_of_business = c.line_of_business,
         jurisdictions = c.jurisdictions, lifecycle_state = c.lifecycle_state
    FROM content.document_chunks c
   WHERE c.chunk_id = e.chunk_id AND c.document_id = d.document_id;

  UPDATE platform.tenant_usage SET content_epoch = content_epoch + 1, updated_at = now()
   WHERE tenant_id = d.tenant_id;
  RETURN v_fp;
END $$;
