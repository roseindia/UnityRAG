# Architecture decisions (ADR log)

The decisions below were made while I implemented ERAG-INS-REQ-001 (v1.0 DRAFT) and the "mandatory architecture extension" prompt (multi-tenancy, PostgreSQL RLS and the Admin Consoles). Where the extension conflicts with the DOCX, the extension wins. Each such conflict is listed in `docs/requirements/REQUIREMENTS_GAPS.md`.

Status values:
- **Accepted**: implemented and tested.
- **Accepted (deviation)**: a deliberate departure from a prompt rule, with the reason given.
- **Proposed**: needs a business or architecture owner to confirm.

---

## ADR-001 Tenancy model: one shared database, logical isolation enforced by PostgreSQL RLS (DOCX AD-01)

**Status:** Accepted

**Decision**
- One PostgreSQL database holds every tenant's data. Every tenant-owned table carries `tenant_id`.
- Row-level security (RLS) is enabled **and forced** on every table except `iam.permissions`, which is the global catalogue of permission codes and holds no tenant data.
- Isolation is layered:
  1. A **RESTRICTIVE** tenant policy on every tenant-owned table, created by `app_admin.apply_tenant_rls()`. It applies to `rag_app`, `rag_worker` and `rag_readonly`.
  2. **PERMISSIVE** policies per access mode, ownership and ACL.
  3. RBAC/ABAC and final authorisation checks in the services.
- Cross-tenant relationships are impossible at the DDL level. Every child table references its parent with a composite `(tenant_id, parent_id)` foreign key onto a `UNIQUE (tenant_id, id)` key on the parent.

**Why**
- The DOCX proposes "shared platform with logical isolation" as its default.
- The extension makes RLS mandatory and requires that application filters are not the only control.

**Consequences**
- A "dedicated instance" option for high-sensitivity tenants (AD-01's alternative) needs no code change; it is the same deployment with a single tenant.
- Partitioning by tenant is deferred (see ADR-010).

## ADR-002 Schema-per-domain layout

**Status:** Accepted

| Schema | Content |
|---|---|
| `platform` | Tenants, plans, subscriptions, quotas, usage, feature flags, settings, domains, platform users/roles/permissions, platform audit, break-glass grants, AI provider and model catalogue |
| `iam` | Global accounts (`user_accounts`, including the external IdP subject), tenant users, memberships, user attributes (ABAC), roles, role permissions, permissions, departments, teams and team members, groups and group members, sessions, refresh tokens, login events, password reset tokens |
| `content` | Collections, collection access, documents, versions, metadata, document access, pages, chunks, chunk embeddings |
| `ingest` | Ingestion jobs and job logs |
| `rag` | Conversations, messages, message sources, search logs, retrieval logs, feedback |
| `ai` | Tenant AI and RAG configurations (versioned), tenant provider credentials (encrypted), prompt templates, guardrail events, model usage |
| `eval` | Evaluation datasets, questions, runs and results |
| `audit` | Hash-chained, append-only tenant audit log and chain heads |
| `ops` | Daily usage aggregates (tenant, department, user) and worker heartbeats |
| `app`, `app_admin` | RLS helper and SECURITY DEFINER functions; DDL helpers used only by migrations |

The table names listed in the extension (`tenants`, `users`, `documents`, `tenant_ai_configurations` and so on) are kept exactly. They are grouped into these schemas so that grants can be given per schema.

## ADR-003 Tenant context: transaction-local settings, set only by the server

**Status:** Accepted

- The context is established per transaction with `set_config(name, value, true)`, which is equivalent to `SET LOCAL`. **It is never set at session level.** The pool also runs `RESET ALL` when a connection is returned (`app/database/session.py`).
- Settings, all read through `app.current_*()` helper functions:

| Setting | Meaning |
|---|---|
| `app.current_tenant_id` | Active tenant |
| `app.current_user_id` | Tenant user (`iam.users.user_id`) |
| `app.current_account_id` | Global identity (`iam.user_accounts.account_id`) |
| `app.current_platform_role` | Platform role code, for platform staff only |
| `app.current_access_mode` | See ADR-004 |
| `app.current_principals` | uuid[]: the user id, the tenant "everyone" principal, department, groups, roles, teams |
| `app.current_lobs`, `app.current_jurisdictions` | ABAC attributes (`*` = all) |
| `app.current_max_class` | Highest classification rank the user is cleared for |

- The values come **only** from the validated access token and a per-request revalidation in the database (`app.auth_resolve_request`). A tenant id in a URL, query string, header or body is never used to set tenant context.
- Platform endpoints that act *on* a tenant take its id in the path. They run in `platform` or `platform_provisioning` mode, and only callers with a platform role reach them.
- With no context, every `app.current_*()` returns NULL. NULL matches no permissive policy, so the query returns zero rows. The RLS tests check this.

## ADR-004 Access modes

**Status:** Accepted

`app.current_access_mode` selects which permissive policies can match:

| Mode | Used by | Can see |
|---|---|---|
| `user` | Normal API requests | Own tenant; content filtered by ACL + ABAC (`app.acl_visible`) |
| `tenant_admin` | Tenant Admin Console | Own tenant's identity, configuration and metadata. **No document or chunk content** (DOCX SP-08) |
| `auditor` | Audit and report readers | Own tenant's audit and report tables, read-only |
| `worker` | Celery tasks; aggregate analytics (ADR-012) | Exactly one tenant, every row of that tenant (needed for ingestion) |
| `scheduler` | Periodic jobs | `platform.tenants` id and status only, to enumerate tenants. Each tenant is then processed in its own `worker` transaction |
| `platform` | Platform Admin Console | Platform tables and cross-tenant **aggregates** (`tenant_usage`, `ops.tenant_usage_daily`). No tenant content |
| `platform_provisioning` | Tenant onboarding | One tenant's identity and configuration tables (creating the first tenant admin, default roles) |
| `break_glass` | Support access | Read-only document, chunk and conversation access, only while an active, unexpired `platform.break_glass_grants` row for that account and tenant exists |

Any other value, or no value, matches nothing. User-facing modes (`user`, `tenant_admin`, `auditor`) also require the tenant to be operational (`app.tenant_is_operational()`). A suspended tenant therefore loses data access inside the database, not only in the API.

## ADR-005 Database roles and SECURITY DEFINER functions

**Status:** Accepted

Login roles, all `NOSUPERUSER NOBYPASSRLS`:

| Role | Purpose |
|---|---|
| `rag_migration` | Owns every object; used only by Alembic. FORCE RLS applies to it too, so the seed migration sets a platform context before inserting |
| `rag_app` | API |
| `rag_worker` | Celery workers and the scheduler |
| `rag_readonly` | Reporting |

**No role has BYPASSRLS.** The superuser is used only by `app.database.bootstrap`, to create roles, the database and extensions.

Three operations cannot be expressed as "the caller sees its own rows". Each runs in a `SECURITY DEFINER` function owned by a dedicated `NOLOGIN` role. That role does **not** have BYPASSRLS; it has explicit, narrowly scoped policies of its own:

| Owner role | Functions | Why |
|---|---|---|
| `rag_auth_fn` | `app.auth_*`, `app.account_id_for_email` | Authentication happens before any tenant context exists: password lookup, session creation, refresh rotation and reuse detection, per-request revalidation, reset tokens |
| `rag_acl_fn` | `app.refresh_document_acl` | Recomputes the allow/deny principal arrays onto documents, chunks and embeddings and increments `tenant_usage.content_epoch`. Tenant admins can change access rules without being able to read or update chunk content. The function's own policies are restricted to `tenant_id = app.current_tenant_id()` |
| `rag_audit_fn` | `audit.chain_hash` trigger, `audit.verify_tenant_chain` | Appending to the hash chain needs the chain head, which normal roles cannot update |

Every definer function pins `search_path = pg_catalog, pg_temp`, uses schema-qualified names and has `EXECUTE` revoked from PUBLIC.

## ADR-006 Document ACL model: denormalised principal arrays

**Status:** Accepted

- Document and collection access rules (`content.document_access`, `content.collection_access`) grant or deny one of these principals: a user, the tenant (everyone), a department, a group, a role or a team.
- `app.refresh_document_acl(document_id)` resolves the effective `allow_principals` and `deny_principals` arrays and writes them to the document, every chunk and every embedding.
- Deny always wins. The collection's rules apply when the document has none of its own.
- `app.acl_visible()` is the single predicate used by the `user`-mode policies on all three tables, combining:
  - lifecycle published or superseded
  - classification rank at or below the clearance
  - line of business (LOB) and jurisdiction ABAC
  - the allow array overlapping the caller's principals
  - no overlap with the deny array
- GIN indexes on the arrays keep the check fast.

**Why**
- Joining ACL tables inside the vector search would defeat the HNSW index.
- Chunks can never be more visible than their parent document (extension rule), because both carry the same arrays and are refreshed together.

**Consequences**
- Every change to an ACL, membership, group or role calls the refresh for the affected documents. `content_epoch` changes, so permission-keyed caches are invalidated automatically.

## ADR-007 Authentication

**Status:** Accepted

- **Identity.** Global `iam.user_accounts` (one per person) with tenant-scoped `iam.users` and `iam.tenant_memberships`. One person can belong to several tenants and switch between them with `POST /auth/select-tenant`. Membership is revalidated in the database on every request.
- **Local login.**
  - Passwords are hashed with scrypt (n = 2^15, r = 8, p = 1).
  - Account lockout (`LOCKOUT_THRESHOLD`, `LOCKOUT_MINUTES`) and the password policy (`PASSWORD_MIN_LENGTH`, plus complexity checks) come from configuration.
  - Optional TOTP MFA, plus step-up for admin writes.
- **OIDC.** `POST /auth/oidc/exchange` validates an IdP token (issuer, audience, expiry, signature via JWKS) and maps it to an account by `(auth_provider, external_subject)` on `iam.user_accounts`. The first login may link by e-mail, but only for an account pre-provisioned for that provider.
- **Tokens.**
  - Access tokens are short-lived JWTs (HS256 by default, secret from the environment). They carry session id, account and tenant.
  - Refresh tokens are opaque random strings stored hashed. They rotate on every use; reusing an old one revokes the whole session family.
- **Secrets.** Provider API keys stored in the database are encrypted with Fernet. The key comes from `SECRETS_ENCRYPTION_KEY`, which is required in production.

The DOCX says the platform "shall not store employee passwords" (FR-002). The extension prompt requires login, registration and password management. Both are supported: `AUTH_MODE=oidc` turns local passwords off. See the gaps document.

## ADR-008 Retrieval: hybrid search in PostgreSQL (DOCX AD-02, AD-03, AD-06)

**Status:** Accepted

- **Three branches**, each running under RLS in the caller's context:
  - **Vector:** pgvector HNSW, cosine distance.
  - **Full-text:** `websearch_to_tsquery`, with an OR-relaxed fallback when the AND query returns nothing, ranked with `ts_rank_cd`.
  - **Exact identifier:** trigram and equality on clause references, form and endorsement numbers.
- **Fusion and ranking**
  - Results are combined with weighted Reciprocal Rank Fusion (k = 60 by default, configurable per tenant).
  - Then: content-hash de-duplication, an **authorisation rehydrate** (the fused ids are re-read under RLS, and anything no longer visible is dropped and counted in diagnostics), optional reranking, a minimum-relevance cut-off and top-k.
- **Permission filter placement (AD-06): both.** RLS pre-filters every branch. The services re-verify before prompt assembly.
- **Caching**
  - Retrieval results are cached by `tenant`, permission fingerprint, `content_epoch`, RAG config version, AI config version and the query/filter digest.
  - The cache holds chunk ids and scores only, never content. Content is always re-read under RLS.
  - No answer cache is implemented. AD-07's default enables one only after cache-isolation tests are passed.

## ADR-009 Embedding storage: dimension-less column with per-dimension partial HNSW indexes

**Status:** Accepted

- `content.chunk_embeddings.embedding` is `vector` with no fixed dimension, plus a `dimensions` column.
- There is one partial expression index per supported dimension: `emb_hnsw_384`, `emb_hnsw_768`, `emb_hnsw_1024` and `emb_hnsw_1536`, each `USING hnsw ((embedding::vector(N)) vector_cosine_ops) WHERE dimensions = N AND is_active`.
- Queries cast to the same expression and set `hnsw.iterative_scan = relaxed_order`. Under the extra RLS and tenant filters, the scan then continues until it has k visible rows.

**Why**
- Tenants can pick different embedding models.
- A re-embedding job can write a new model's vectors next to the old ones and switch atomically with `is_active`.

**Evidence**
- 4 tenants × 10,000 vectors, 384 dimensions, `ef_search` 100: mean recall@10 = 0.977, p95 latency under 8 ms.
- See `docs/database/VECTOR_INDEXING.md`, which also covers the case where the planner chose the B-tree path.

## ADR-010 Partitioning deferred

**Status:** Proposed

- Tables are not partitioned yet. The extension allows partitioning only "when justified by measured scale".
- The measured scale so far is 40k vectors.
- The DOCX's planning figure (A-03: about 150M chunks) would justify LIST or HASH partitioning of `document_chunks` and `chunk_embeddings` by `tenant_id`, and RANGE partitioning of the audit tables by month (AD-11).
- The composite `(tenant_id, …)` keys were chosen so that partitioning by tenant needs no change to the primary keys.
- Trigger to revisit: any tenant over 5M chunks, or vector p95 above target in the benchmark.

## ADR-011 Orchestration: LangChain plus LangGraph, with contracts that don't depend on the framework (DOCX AD-05)

**Status:** Accepted

- The chat flow is a LangGraph `StateGraph` (`app/rag/workflows/rag_graph.py`):

  `validate_input → analyze_query → rewrite_query → authorize → hybrid_retrieval → rerank → select_context → check_sufficiency → (generate | reformulate → hybrid_retrieval | abstain) → (validate_citations → output_guardrails | degraded_answer | abstain) → finalize`

- Models implement LangChain's `BaseChatModel` and `Embeddings` interfaces:
  - **OpenAI-compatible HTTP:** covers OpenAI, Azure OpenAI-compatible gateways, vLLM and LiteLLM.
  - **Ollama**.
  - **Hugging Face TEI** (embeddings and reranking).
  - **Local `ExtractiveChatModel` and `LocalHashingEmbeddings`.** Deterministic and dependency-free; used for tests and offline or air-gapped deployments. The extractive model answers only with sentences copied from authorised sources, with their citations.
- Prompts, guardrail rules and the citation contract live in the application (`app/rag/generation/prompts.py`, `app/rag/guardrails`, `app/rag/citations`), not in the framework.

## ADR-012 Tenant analytics read via `worker_tx`, aggregate-only

**Status:** Accepted

- **The problem.** Tenant administrators have no content access (SP-08). In `tenant_admin` mode they cannot count the tenant's chunks, conversations or search logs. Yet the Tenant Admin dashboard must show real numbers (no mock statistics).
- **The decision.**
  - Analytics endpoints first check the admin permission (for example `admin.analytics.view`).
  - They then open a transaction in `worker` mode **for the caller's own tenant**, taken from the session (`app/api/deps.py::worker_tx`).
  - In that transaction they run **aggregate-only** SQL: counts, sums, averages and daily series grouped by date, department, status or model.
- **What is forbidden.** `worker_tx` must never be used to return row-level content. The rule is enforced by code review and by tests that check the analytics responses contain no content fields.
- **Where the numbers come from.** Historical dashboards read the `ops.*_daily` aggregates built by the scheduler, so pages do not scan raw tables.

## ADR-013 Services use SQLAlchemy Core `text()` queries; no repository layer

**Status:** Accepted (deviation)

The backend prompt asks for "SQLAlchemy repositories and service layers" and also forbids "empty placeholder modules".

- The data access is SQL that relies heavily on PostgreSQL features: RLS context, array operators, pgvector casts, `websearch_to_tsquery`, CTE aggregates and `ON CONFLICT`. An ORM model layer would have duplicated the DDL (the source of truth is `database/migrations/*.sql`) and added nothing.
- The services in `app/services/*` therefore own their parameterised SQL, using SQLAlchemy `text()` with bound parameters only. **No user input is ever interpolated into SQL.**
- The planned `app/models` and `app/repositories` packages were removed rather than left empty.
- Routers contain no business logic. They validate input with Pydantic, resolve the context and call a service.

## ADR-014 Ingestion and background processing (DOCX AD-10)

**Status:** Accepted

- **Queue.** Celery with a Redis broker and two queues, `ingestion` and `maintenance`. Celery beat runs these schedules:
  - due-job requeue every 60 s
  - usage aggregation every 15 min
  - worker heartbeat every 30 s
- **Pipeline:** load → malware scan (ClamAV, mandatory in production) → parse (PDF, DOCX, XLSX, PPTX, HTML, TXT/MD, CSV, images through Tesseract OCR; scanned PDFs fall back to OCR) → remove repeated headers and footers → insurance metadata extraction → structure-aware chunking (default 350 tokens, 40 overlap, parent/child) → embeddings → near-duplicate detection (simhash) → publish.
- **Each job runs in a `worker` context for its own tenant.**
- **Failures.**
  - Transient errors retry with exponential backoff.
  - Permanent errors, or exhausted retries, move the job to `dead_letter`.
  - Replay is idempotent: the checksum and version keep it from re-creating published data.

## ADR-015 Audit (DOCX AD-11)

**Status:** Accepted

- `audit.tenant_audit_logs` is append-only. UPDATE and DELETE are refused by triggers and are not granted.
- Each row is hash-chained per tenant: `hash = sha256(prev_hash ‖ canonical row)`. `audit.verify_tenant_chain()` verifies the chain; the API exposes this as `GET /api/v1/admin/audit/verify`.
- Platform actions go to `platform.platform_audit_logs`, which is chained and append-only in the same way.
- Break-glass access is written to **both** logs.
- Not implemented: monthly partitioning and export to write-once storage (see gaps).

## ADR-016 Streaming protocol: Server-Sent Events (DOCX AD-12)

**Status:** Accepted

- `POST /api/v1/chat/stream` emits `meta`, then `token`*, then `final` and `done`.
- Tokens are buffered per sentence and released only after each sentence passes the output guardrails, covering regulated-decision statements, PII masking and link neutralisation.
- If the guardrails would change the final answer, the `final` event carries the corrected text and the client must replace what it has rendered.

## ADR-017 AI never makes regulated decisions (DOCX CN-02, section 13)

**Status:** Accepted

- **On input.** Requests to approve, reject or settle a claim, accept or decline a risk, or calculate a binding premium are detected and answered with a knowledge-boundary response.
- **On output.** Any regulated-decision statement is removed before it reaches the user.
- **No data path.** No endpoint or workflow node can write a claim, underwriting or settlement decision. The platform has no such tables.

## ADR-018 Local development and sandbox notes

**Status:** Accepted

- The verified run used Python 3.13.18, PostgreSQL 16.15 with pgvector 0.8.1 (built from source) and Redis 7. Versions are pinned in `backend/requirements.txt`.
- The build sandbox had no access to PyPI or Docker Hub:
  - Python packages were installed from source.
  - Three packages with native extensions (`orjson`, `ormsgpack`, `uuid_utils`) were replaced in that sandbox by small pure-Python shims. **The shims are not part of the deliverable**; pip installs the real packages.
  - The Celery CLI dependencies (`click-didyoumean`, `click-repl`, `click-plugins`, `prompt_toolkit`, `wcwidth`) and the OpenTelemetry SDK and OTLP exporter were installed from their GitHub sources.
- The Docker images could not be pulled or built in the sandbox. `docker compose config` validates the compose file, but the containerised stack was **not started there** (see `PROJECT_STATUS.md`).

## ADR-019 Observability: Prometheus metrics, OpenTelemetry traces, JSON logs

**Status:** Accepted

**Metrics.** `/metrics` exposes the golden signals plus RAG-specific series (retrieval per branch, generation, guardrail decisions, empty retrievals, tokens, ingestion stages, cache). It is internal-only behind Nginx.

**Traces.** OpenTelemetry API instrumentation is always present and costs nothing when disabled (no-op tracer). With `OTEL_ENABLED=true`, an SDK provider exports spans via OTLP/HTTP, configured by the standard `OTEL_EXPORTER_OTLP_*` and `OTEL_TRACES_SAMPLER*` variables. Spans:
- an HTTP server span, with W3C `traceparent` extraction and the trace id returned as `X-Trace-ID`;
- `rag.retrieve` with the vector, full-text and exact child spans;
- `rag.generate`, with token counts;
- `ingestion.job`.

Span attributes carry ids, counts and timings only; never query text, prompts, answers or document content.

**Logs.** Structured JSON logs carry the correlation id, tenant id and trace id, with secret redaction.

**Gap.** Trace context is not yet propagated from the API into Celery tasks (gap G-09).

