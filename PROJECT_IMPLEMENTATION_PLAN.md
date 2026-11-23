# Implementation plan

**Sources**
- ERAG-INS-REQ-001 v1.0 DRAFT (DOCX, 958 catalogued identifiers)
- The backend implementation prompt
- The mandatory architecture extension (multi-tenancy, PostgreSQL RLS, Admin Consoles)

The extension takes precedence where the sources conflict. Each conflict is recorded in `docs/requirements/REQUIREMENTS_GAPS.md`, section 1.

The phases follow section 23 of the backend prompt. Exit criteria are objective: code exists, an automated test proves it, and the documentation is updated. Current status is in `PROJECT_STATUS.md`.

| Phase | Scope | Main deliverables | Exit criteria |
|---|---|---|---|
| **0 – Requirements analysis** | Read the whole DOCX; extract every requirement table; identify entities, APIs, security requirements and gaps | `scripts/extract_requirements.py` → `requirements_catalogue.json` (958 ids: FR 275, NFR 112, BR 187, TC 135, plus UC, AD, AP, SP, CN, A, D, IF, RSK, PAC, SO); `scripts/generate_rtm.py` → RTM; gaps; this plan; ADRs | Every id appears in the RTM; conflicts recorded |
| **1 – Database foundation** | Roles, extensions, multi-tenant schema (9 schemas, 67 tables), composite tenant keys, RLS helpers, restrictive and permissive policies, indexes, seed | `database/migrations/01–14`, Alembic `0001–0014`, SQL bundles, `app.database.bootstrap` | Clean install through Alembic **and** through psql; RLS tests 1–17 pass as `rag_app`/`rag_worker` |
| **2 – Authentication and security** | Local login and OIDC, JWT plus rotating refresh tokens, MFA/TOTP, sessions, lockout; tenant resolution from the session; RBAC/ABAC; transaction-local context; audit | `app/security/*`, `app/dependencies/auth.py`, definer functions (`13_security_functions.sql`), `app/services/auth_service.py`, `audit.py` | Auth, tamper, reuse-detection, revocation, tenant-selection and forged-tenant tests pass |
| **3 – Document management** | Upload (single and bulk), signature-based format detection, quotas, checksum and duplicates, tenant-scoped storage, metadata, versions, collections, access rules, legal hold, deletion | `document_service.py`, `integrations/storage.py`, `api/v1/documents.py`, `collections.py` | Upload, versioning, ACL and legal-hold tests pass |
| **4 – Ingestion** | Celery workers; malware scan; parsers and OCR; normalisation; insurance metadata; chunking; embeddings; FTS; retry, dead letter, replay | `app/rag/{parsers,ocr,ingestion,chunking,embeddings}`, `app/workers/*` | Multi-format ingestion, OCR, retry/dead-letter and idempotency tests pass |
| **5 – Hybrid search** | Vector, FTS, exact branches; metadata and as-of filters; RRF; authorisation rehydrate; reranking; permission-fingerprinted cache; facets; search APIs | `app/rag/retrieval/hybrid.py`, `hybrid_search/rrf.py`, `reranking/*`, `api/v1/search.py` | Search-mode, filter, facet, cache-isolation and RRF tests pass; vector benchmark recorded |
| **6 – RAG** | LangChain models (local extractive, OpenAI-compatible, Azure, Ollama, TEI); LangGraph workflow; guardrails; citation validation; SSE; conversation persistence | `app/rag/{generation,guardrails,citations,workflows}`, `chat_service.py` | Chat, SSE, citation, guardrail, abstention and unauthorised-content tests pass |
| **7 – Administration backend** | Platform Admin API (tenants, plans, quotas, providers, models, monitoring, audit, break-glass) and Tenant Admin API (users, roles, groups, departments, collections, documents, ingestion, AI/RAG configuration, analytics, reports) | `api/v1/{platform_admin,tenants,admin,users,roles,…}`, `platform_service.py`, `tenant_service.py`, `analytics_service.py` | Admin console tests (21) pass; statistics come from real data |
| **8 – Evaluation and observability** | Evaluation datasets, runs and gates; feedback review; usage and cost; aggregation jobs; Prometheus metrics; OpenTelemetry; structured logs | `evaluation_service.py`, `analytics/aggregation.py`, `observability/*` | Evaluation, aggregation and observability tests pass |
| **9 – Testing and hardening** | Unit, integration, RLS, security, RAG and E2E suites; performance benchmark; security review fixes | `backend/tests/*`, `scripts/benchmark_vector.py` | Full suite green on a clean database |
| **10 – Final delivery** | Documentation, Docker, scripts, API reference, test report, RTM status | `README.md`, `docs/**`, `docker-compose.yml`, `scripts/*` | Documentation complete; the RTM regenerated from the final mapping |

## Next steps after this delivery

These are the gaps, in recommended order of priority:

1. Run the Docker Compose stack in a networked environment and execute the test suite inside the `api` container (G-10).
2. Benchmark at design scale (A-01 to A-03) and decide on tenant partitioning (ADR-010).
3. Identity integration: SAML or OIDC-only production mode, SCIM provisioning, IdP group mapping (G-01 to G-03).
4. Source connectors (SharePoint, ECM, file shares) with source-ACL synchronisation (FR-026, AD-08).
5. Object-storage backend, WORM audit export and SIEM streaming (G-08, G-11, FR-234).
6. Retention executor, data-subject requests and residency enforcement (FR-240 to FR-247, G-14).
7. Model-based evaluation judges, regression gating on configuration change, drift monitoring (FR-209 to FR-214).
8. The frontend (`docs/requirements/FRONTEND_REQUIREMENTS.md`).
