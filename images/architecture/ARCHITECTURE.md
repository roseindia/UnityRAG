# Architecture overview

The decisions behind each element are recorded in `PROJECT_ARCHITECTURE_DECISIONS.md` (ADR-001 to ADR-018).

## 1. Runtime view

```mermaid
flowchart LR
  subgraph Clients
    UI[React/TS frontend<br/>user app + admin consoles]
    IdP[(Corporate IdP<br/>OIDC)]
  end
  UI -->|HTTPS| NGINX[Nginx<br/>TLS, SSE passthrough]
  UI -. OIDC login .-> IdP
  NGINX --> API[FastAPI API<br/>rag_app role]
  API -->|SET LOCAL context per tx| PG[(PostgreSQL 16<br/>pgvector + FTS + RLS)]
  API --> REDIS[(Redis<br/>cache, rate limit, broker)]
  API -->|enqueue| REDIS
  REDIS --> WORKER[Celery worker<br/>rag_worker role]
  BEAT[Celery beat<br/>scheduler] --> REDIS
  WORKER --> PG
  WORKER --> STORE[(Document storage<br/>tenant-prefixed)]
  API --> STORE
  WORKER --> CLAM[ClamAV]
  WORKER --> OCR[Tesseract OCR]
  API --> LLM[LLM / embedding / rerank providers<br/>local, OpenAI, Azure, Ollama, TEI]
  WORKER --> LLM
  API --> OTEL[(OTLP collector)]
  PROM[(Prometheus)] -->|/metrics| API
```

## 2. Request flow and security layers

```mermaid
sequenceDiagram
  participant C as Client
  participant M as Middleware
  participant D as Auth dependency
  participant S as Service
  participant DB as PostgreSQL (RLS)
  C->>M: request + Bearer token (+ traceparent)
  M->>M: correlation id, size limit, server span
  M->>D: route
  D->>D: verify JWT (sig, iss, aud, exp)
  D->>DB: app.auth_resolve_request(session) [definer]
  DB-->>D: account, tenant, membership, roles, permissions, ABAC
  D->>D: RBAC check (require / admin / require_platform), rate limit
  D->>S: RequestContext (tenant from session only)
  S->>DB: BEGIN then set_config(app.current_*, value, true)
  S->>DB: parameterised SQL (RESTRICTIVE tenant + PERMISSIVE mode/ACL policies)
  DB-->>S: only authorised rows
  S->>DB: audit row (hash-chained), COMMIT
  S-->>C: JSON / SSE (X-Correlation-ID, X-Trace-ID)
```

## 3. Code layout (`backend/app`)

| Package | Responsibility |
|---|---|
| `api/v1` | FastAPI routers. Validation, dependency injection, calls into services; no business logic |
| `dependencies` | Authentication and authorisation dependencies (`get_context`, `require`, `require_any`, `require_platform`) |
| `security` | Passwords (scrypt), JWT, refresh tokens, TOTP, OIDC validation, Fernet secrets, `RequestContext` |
| `database` | Engines per role, `SecurityContext`, `scoped_session` (transaction-local context), role-safety check, bootstrap |
| `services` | Use-case logic and parameterised SQL: auth, identity, tenants, quotas, documents, search, chat, configuration, analytics, evaluation, platform, usage, audit |
| `rag` | `parsers`, `ocr`, `ingestion`, `chunking`, `embeddings`, `retrieval`, `hybrid_search` (RRF), `reranking`, `generation` (LangChain models, prompts), `citations`, `guardrails`, `evaluation` (metrics), `workflows` (LangGraph) |
| `workers` | Celery application, queues, beat schedule, tasks |
| `analytics` | Per-tenant scheduled aggregation into `ops.*_daily` |
| `integrations` | Storage, ClamAV, AI provider registry |
| `middleware` | Correlation, metrics, tracing, security headers, rate limiting |
| `observability` | Prometheus metrics, OpenTelemetry tracing |
| `core` | Settings (with the production guard), errors, logging (JSON + redaction), context variables |
| `schemas` | Pydantic v2 request and response models |

## 4. Data and isolation model

See `docs/database/DATABASE_DESIGN.md`, which has the ER diagram and the ownership matrix, and `docs/security/DATABASE_SECURITY.md`.

| Layer | What it enforces |
|---|---|
| 1. RLS | Tenant isolation in the database |
| 2. RBAC/ABAC | In dependencies and SQL context |
| 3. Resource ACLs | Denormalised principal arrays checked by `app.acl_visible()` on documents, chunks and embeddings |

## 5. RAG flow

See `docs/rag/RAG_PIPELINE.md`.

- **Ingestion** runs asynchronously per tenant: worker mode, then parse, OCR, chunk, embed and publish.
- **Retrieval** is hybrid (HNSW + FTS + exact), fused with RRF and re-authorised under RLS.
- **Generation** is a LangGraph state machine with guardrails, citation validation, abstention and degraded mode.
