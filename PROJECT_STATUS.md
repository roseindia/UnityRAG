# Project status

**Last updated:** 2026-11-02.

**Overall.** The backend and database are implemented and verified against a real PostgreSQL 16 / pgvector 0.8 database. **110 automated tests pass.** The Docker Compose stack is validated but has not been started; the build sandbox had no registry access.

## Phase status

| Phase | Status | Evidence |
|---|---|---|
| 0 Requirements analysis | Done | 958 ids extracted from every DOCX table (`requirements_catalogue.json`); RTM with all ids; gaps and conflicts (`REQUIREMENTS_GAPS.md`); ADRs |
| 1 Database foundation | Done | 14 migrations; 67 tables in 9 schemas; 223 policies; FORCE RLS on 66 tables; composite tenant keys. Clean installs through Alembic and through psql both verified |
| 2 Authentication and security | Done (SAML and SCIM out of scope; see gaps) | Local login, OIDC exchange, MFA, step-up, rotating refresh tokens with reuse detection, per-request revalidation, RBAC/ABAC, audit; `test_auth_api.py`, `tests/security`, `tests/rls` |
| 3 Document management | Done (object-storage backend pending) | Upload, bulk upload, versions, metadata, collections, ACLs, legal hold, delete and purge |
| 4 Ingestion | Done | Celery worker (verified both eager and as a real worker on Redis); 8 formats plus OCR; chunking; embeddings; FTS; retry, dead letter, replay |
| 5 Hybrid search | Done | Vector, FTS, exact, RRF, rehydrate, rerank, cache, facets; benchmark (recall@10 0.977) |
| 6 RAG | Done (model-quality targets unmeasured) | LangGraph workflow, providers, guardrails, citations, SSE, conversations |
| 7 Administration backend | Done | 127 API paths, covering the Platform Admin and Tenant Admin consoles; real-data statistics; break-glass |
| 8 Evaluation and observability | Done (judges and drift pending) | Evaluation API and gates, feedback review, usage and cost, aggregation jobs, Prometheus, OpenTelemetry, JSON logs |
| 9 Testing and hardening | Done for functional scope; load tests pending | 110 tests; ruff clean; security fixes made during hardening (listed below) |
| 10 Final delivery | Done | README, docs (architecture, database with ER diagram, API reference, security, RAG, deployment, operations and test report), scripts, Docker |

## Definition of Done (backend prompt, section 26)

| Item | Status | Evidence / note |
|---|---|---|
| DOCX fully analysed; every requirement traceable | ✅ | RTM: FR 275, NFR 112, BR 187, TC 135, plus the other catalogues |
| PostgreSQL implemented; pgvector operational; FTS operational | ✅ | Migrations; HNSW and GIN; `test_vector_fulltext_hybrid_and_exact_search` |
| Multi-tenant architecture; RLS enabled and tested; tenant isolation demonstrated | ✅ | `tests/rls` (24 tests as `rag_app`/`rag_worker`), `tests/e2e/test_two_tenant_journey.py` |
| Authentication; RBAC and ABAC | ✅ | `test_auth_api.py`, `test_admin_consoles.py`, ACL and clearance tests |
| Upload, parsing, OCR, workers, chunking, persisted embeddings | ✅ | `test_upload_multiple_formats_and_ingestion`, `test_scanned_image_ocr`, `test_workers.py`; a real worker run was also performed |
| Vector, full-text and hybrid search; RRF | ✅ | Search tests, RRF unit tests |
| LangChain integrations; LangGraph workflow; RAG answers | ✅ | `tests/rag`, chat tests. The local extractive model is used for tests; external providers were tested with mocked HTTP |
| Citations persisted and validated; conversations persisted | ✅ | `test_chat_answer_citations_conversation_and_feedback`, `test_preview_download_and_citation_reverification` |
| Admin APIs; tenant statistics; platform statistics (authorised only) | ✅ | 21 admin console tests |
| Audit logs; evaluation APIs | ✅ | Audit chain verification, evaluation run and gates tests |
| Docker Compose starts the backend | ⚠️ Not verified | `docker compose config` passes; images could not be pulled in the sandbox (gap G-10) |
| Migrations work on a clean database | ✅ | Every test run bootstraps a fresh database; manual psql install also verified |
| Automated tests pass | ✅ | 110 passed, 0 skipped |
| Documentation complete | ✅ | See README "Repository map" |

## Changes during final hardening (this session)

1. **Audit logs:** added TRUNCATE guards. TRUNCATE bypasses row triggers, so a statement-level guard now blocks it even for the owner role. Tested.
2. **RLS bypass protection:** the API and workers now refuse to start in production if their database credential is a superuser, has BYPASSRLS or owns the tables. Tested.
3. **Credential scope in Compose:** only the one-shot `migrate` service receives the superuser DSN and migration password.
4. **Prompt structure:** source-block attributes and untrusted passage text are now HTML-escaped. Previously, a section path containing `>` broke `<source>` parsing, and a passage could have forged a `<source>` boundary. Tested.
5. **Embedding dimensions:** configurations without a matching HNSW index are now rejected (previously they caused a 500 at search time).
6. **Strict length checks:** `zip(strict=True)` now protects pairing of embedding vectors with chunks and of reranker scores with results.
7. **Exception handling:** silent `except: pass` handlers were replaced with logged handling.
8. **Search facets:** new `GET /api/v1/search/facets`, limited to entitled values (FR-016).
9. **OpenTelemetry tracing** with W3C propagation and `X-Trace-ID`.
10. **API explorer** (`/docs`, `/redoc`, `/openapi.json`) disabled in production.
11. **Unused settings:** removed `STORAGE_BACKEND`; `METRICS_ENABLED` is now honoured.
12. **Dates:** UTC dates are used throughout (`app/utils/clock.py`).

## Known limitations

These are summarised here; the full list, with resolutions, is in `docs/requirements/REQUIREMENTS_GAPS.md`.

- **Identity:** SAML 2.0, SCIM and JIT provisioning, external partner realm.
- **Integrations:** source connectors, SIEM export, notification platform, object-storage backend.
- **Data lifecycle:** retention executor, data-subject requests, residency enforcement.
- **Evaluation:** model-based judges, regression-gated promotion, drift detection.
- **Not yet measured:** performance at design scale; AI-quality NFRs with a production model and SME datasets.
- **Not in this repository:** the frontend (`docs/requirements/FRONTEND_REQUIREMENTS.md`).

## Decisions needed from the business

| Item | Decision needed | Reference |
|---|---|---|
| G-01 | Production `AUTH_MODE` (`oidc` recommended), and whether local accounts are allowed for operators and partners | `REQUIREMENTS_GAPS.md` |
| G-04 | Whether tenant admins may preview content (currently they cannot; SP-08) | `REQUIREMENTS_GAPS.md` |
| G-06 | Whether a document can belong to one collection only | `REQUIREMENTS_GAPS.md` |
| AD-01 to AD-12 | Confirmation of the architecture decisions | `REQUIREMENTS_GAPS.md`, section 2 |
| A-11 | Approval of the numeric targets | `REQUIREMENTS_GAPS.md` |


