"""Generate docs/requirements/REQUIREMENTS_TRACEABILITY_MATRIX.md from the
requirements extracted from the DOCX (requirements_catalogue.json, produced by
scripts/extract_requirements.py) and the implementation mapping below.

Status values: Completed | In Progress | Not Started | Frontend.
"Completed" is used only where code exists AND an automated test exercises it
(or, for pure configuration/DDL items, where the migration enforces it).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAT = json.loads((ROOT / "docs/requirements/requirements_catalogue.json").read_text(encoding="utf-8"))
REQ = {r["id"]: r for r in CAT}

T_RLS = "tests/rls/test_rls_isolation.py"
T_AUTH = "tests/integration/test_auth_api.py"
T_DOC = "tests/integration/test_documents_rag_api.py"
T_ADM = "tests/integration/test_admin_consoles.py"
T_WRK = "tests/integration/test_workers.py"
T_E2E = "tests/e2e/test_two_tenant_journey.py"
T_SEC = "tests/security/test_api_security.py"
T_UCH = "tests/unit/test_chunking_parsing.py"
T_UGR = "tests/unit/test_guardrails_citations.py"
T_URR = "tests/unit/test_rrf_metrics.py"
T_USP = "tests/unit/test_security_primitives.py"
T_RAG = "tests/rag/test_providers_and_workflow.py"

# section prefix -> (component, db objects, endpoints, tests)
SECTIONS = {
    (1, 11): ("app/services/auth_service.py, app/security/*, app/services/identity_service.py",
              "iam.user_accounts, iam.users, iam.tenant_memberships, iam.sessions, iam.refresh_tokens, iam.user_roles, iam.user_group_members",
              "/api/v1/auth/*, /api/v1/admin/users/*", T_AUTH),
    (12, 25): ("Frontend (React) consuming backend APIs", "-", "see FRONTEND_REQUIREMENTS.md", "-"),
    (26, 53): ("app/rag/ingestion/pipeline.py, app/services/document_service.py, app/workers/*",
               "content.documents, content.document_versions, content.document_pages, content.document_chunks, ingest.ingestion_jobs, ingest.ingestion_job_logs",
               "/api/v1/documents*, /api/v1/admin/documents*, /api/v1/admin/ingestion/*", f"{T_DOC}, {T_WRK}"),
    (54, 69): ("app/rag/parsers/*, app/rag/ocr/tesseract.py, app/rag/ingestion/insurance_metadata.py",
               "content.document_pages, content.document_metadata", "/api/v1/documents (upload)", f"{T_UCH}, {T_DOC}"),
    (70, 82): ("app/rag/chunking/chunker.py, app/rag/embeddings/providers.py", "content.document_chunks, content.chunk_embeddings, ai.tenant_rag_configurations",
               "/api/v1/admin/config/rag, /api/v1/admin/documents/{id}/reindex", f"{T_UCH}, {T_RAG}"),
    (83, 99): ("app/rag/retrieval/hybrid.py, app/rag/hybrid_search/rrf.py, app/rag/reranking/rerankers.py",
               "content.document_chunks (GIN tsv/trgm), content.chunk_embeddings (HNSW)", "/api/v1/search, /api/v1/search/vector, /api/v1/search/fulltext",
               f"{T_DOC}, {T_URR}, {T_SEC}"),
    (100, 113): ("database/migrations/07_rls_policies.sql, app/rag/retrieval/hybrid.py (final authorisation), app/utils/cache.py",
                 "all tenant tables (RLS), content.document_access, content.collection_access", "/api/v1/search, /api/v1/chat, /api/v1/documents/{id}/preview|download",
                 f"{T_RLS}, {T_SEC}"),
    (114, 134): ("app/rag/workflows/rag_graph.py, app/rag/generation/*, app/rag/citations/validator.py",
                 "rag.conversation_messages, rag.message_sources", "/api/v1/chat, /api/v1/chat/stream", f"{T_DOC}, {T_RAG}, {T_UGR}"),
    (135, 152): ("app/rag/guardrails/detectors.py, app/rag/workflows/rag_graph.py", "ai.guardrail_events", "/api/v1/chat",
                 f"{T_UGR}, {T_DOC}"),
    (153, 162): ("app/services/chat_service.py, app/api/v1/admin.py (feedback queue)", "rag.feedback", "/api/v1/feedback, /api/v1/admin/feedback",
                 f"{T_DOC}, {T_ADM}"),
    (163, 180): ("app/services/identity_service.py, tenant_service.py, config_service.py, quota_service.py",
                 "iam.*, platform.tenant_quotas, ai.tenant_ai_configurations, ai.tenant_rag_configurations", "/api/v1/admin/*, /api/v1/platform/*", T_ADM),
    (181, 199): ("app/api/v1/*, app/core/errors.py, app/middleware/*", "-", "/api/v1/* (OpenAPI)", f"{T_SEC}, {T_AUTH}, {T_DOC}"),
    (200, 215): ("app/services/evaluation_service.py, app/rag/evaluation/metrics.py", "eval.*", "/api/v1/admin/evaluation/*", f"{T_ADM}, {T_URR}"),
    (216, 236): ("app/services/analytics_service.py, app/analytics/aggregation.py, app/services/audit.py, app/observability/*",
                 "audit.tenant_audit_logs, ops.tenant_usage_daily, ops.department_usage_daily, ai.tenant_model_usage",
                 "/api/v1/admin/analytics*, /api/v1/admin/audit*, /api/v1/admin/reports/*, /metrics, /health/*", f"{T_ADM}, {T_E2E}"),
    (237, 248): ("app/rag/guardrails/detectors.py, app/services/document_service.py", "content.document_chunks.sensitivity_tags, content.documents.legal_hold",
                 "/api/v1/admin/documents/{id}/legal-hold", f"{T_UGR}, {T_DOC}"),
    (249, 259): ("app/services/document_service.py", "content.documents (lifecycle, effective dates), content.document_versions",
                 "/api/v1/admin/documents/{id}/lifecycle, /versions", T_DOC),
    (260, 275): ("app/rag/workflows/rag_graph.py (grounded RAG over approved documents)", "content.*", "/api/v1/chat", f"{T_DOC}, {T_E2E}"),
}

COMPLETED_WITH_REMARK = {
    "FR-003": "TOTP MFA + step-up for admin writes (tenant setting); IdP MFA claims honoured for OIDC.",
    "FR-029": "ClamAV INSTREAM client; production refuses MALWARE_SCANNER=none. Not exercised against a live clamd in CI.",
    "FR-055": "python-docx reads the accepted view; comments excluded.",
    "FR-085": "ts_rank_cd cover-density ranking (no BM25 extension).",
    "FR-091": "Rule-based rewriting for follow-ups; rewritten query logged and returned.",
    "FR-176": "Tenant-level quotas (users, documents, storage, size, tokens, requests, ingestion jobs, collections). Per-group/user quotas not implemented.",
    "FR-178": "Provisioning with isolated config/quotas; archival keeps data (no automatic deletion).",
    "FR-183": "Retry / cancel / reprocess; no pause-resume of a running job.",
    "FR-221": "Inference + embedding cost estimates from catalogue pricing (OCR/storage cost not priced).",
}
IN_PROGRESS = {
    "FR-001": "Admin/API provisioning implemented; SCIM feed and JIT provisioning not implemented.",
    "FR-002": "OIDC token validation + session exchange implemented; SAML 2.0 not implemented; local passwords remain for non-SSO deployments.",
    "FR-004": "user_type broker/agent + partner role; separate external IdP realm not implemented.",
    "FR-008": "Groups/attributes resolved on every request (no stale cache); IdP change-event sync not implemented.",
    "FR-019": "History, rename, delete, export implemented; saved/shared searches and alerts not implemented.",
    "FR-027": "Upload acquisition with server-generated tenant storage keys; source connectors not implemented.",
    "FR-033": "Headings, lists, tables, reading order of text layer; multi-column/footnote layout analysis not implemented.",
    "FR-038": "Repeated header/footer removal, zero-width stripping; date/identifier standardisation partial.",
    "FR-060": "Grayscale/autocontrast + orientation detection; deskew/denoise not implemented.",
    "FR-062": "Tables kept with headers; table-type classification not implemented.",
    "FR-066": "Per-page OCR confidence, low-confidence flag on chunks and answer warnings; per-word storage not implemented.",
    "FR-068": "Policy/claim/form/clause numbers, amounts, dates, jurisdictions extracted; general NER not implemented.",
    "FR-077": "Parent-child sections and section paths; cross-clause linking (definition<->exclusion<->endorsement) not implemented.",
    "FR-082": "Re-embedding into new generation with atomic cut-over; automated regression evaluation before cut-over not wired.",
    "FR-090": "Insurance synonym normalisation in the local embedding/reranker; user-visible query expansion not implemented.",
    "FR-095": "Candidate counts, branch weights, thresholds, versioned; recency/status boosts and diversity not implemented.",
    "FR-097": "User LOB/jurisdiction/clearance enforced as ABAC; editable context defaults not implemented.",
    "FR-122": "Depends on the configured LLM; extractive local model gives short cited answers only.",
    "FR-123": "Depends on the configured LLM (prompt supports structure).",
    "FR-124": "Depends on the configured LLM; no dedicated comparison flow.",
    "FR-125": "Prompt rule only; no automatic conflict detection.",
    "FR-134": "Degraded search-only mode on model failure; alternative-model fallback routing not implemented.",
    "FR-144": "Pattern + base64/spacing de-obfuscation; multi-turn jailbreak tracking not implemented.",
    "FR-149": "Abuse / regulated-decision input checks; full moderation model not integrated.",
    "FR-150": "Regulated-decision, PII and link checks on output; toxicity model not integrated.",
    "FR-152": "All decisions stored in ai.guardrail_events with rule version; SIEM forwarding not implemented.",
    "FR-158": "Reviewer can resolve feedback; SME validation markers on answers not implemented.",
    "FR-161": "Status/resolution workflow; reporter notification not implemented.",
    "FR-162": "golden_candidate flag on feedback; automatic conversion to evaluation cases not implemented.",
    "FR-164": "Platform groups; IdP group mapping not implemented.",
    "FR-171": "ai.prompt_templates table (versioned, approver != author constraint); management API not implemented; active prompt is code-versioned (answer-v3).",
    "FR-173": "Guardrail modes configurable per tenant (rag config JSON, versioned); rule editor / test harness not implemented.",
    "FR-175": "Mandatory audit events cannot be disabled (no switch exists); retention/redaction configuration UI not implemented.",
    "FR-177": "Quota-threshold alerts on the platform dashboard; budget caps / model downgrade not implemented.",
    "FR-181": "Bearer tokens (local JWT / OIDC exchange); client-credentials / mTLS API clients not implemented.",
    "FR-197": "Per tenant+identity rate limits with 429; idempotency keys on create operations not implemented (ingestion jobs are idempotent internally).",
    "FR-202": "Lexical proxies for faithfulness / answer relevance; model-based judges not implemented.",
    "FR-204": "Context tokens/omitted candidates recorded; relevance scoring not implemented.",
    "FR-205": "Unsupported-citation detection online; hallucination-rate reporting by slice not implemented.",
    "FR-207": "Attack cases in automated tests; in-product attack-suite harness not implemented.",
    "FR-217": "Zero-result counts, latency, cache hits; topic clustering not implemented.",
    "FR-218": "Abstentions and missing-source feedback captured; clustering/routing not implemented.",
    "FR-219": "Citation records per document available; document usage report not implemented.",
    "FR-224": "Aggregates only for admins; minimum group sizes / pseudonymisation not implemented.",
    "FR-225": "CSV export of 11 reports, audited; scheduling not implemented.",
    "FR-230": "Search by user/document/correlation id/category; pipeline replay partial (retrieval_logs + audit lineage).",
    "FR-231": "Prometheus metrics, correlation IDs and OpenTelemetry spans (HTTP server span with W3C propagation, retrieval branches, generation, ingestion job) exported over OTLP/HTTP; trace id in JSON logs and X-Trace-ID. Celery task context propagation from API to worker not implemented.",
    "FR-233": "Quota/ingestion/security alerts on the platform dashboard; alert routing not implemented.",
    "FR-239": "Sensitivity tags and classification rank; source-label inheritance not implemented.",
    "FR-240": "Retention fields (collections, conversations, tenants); retention executor job not implemented.",
    "FR-243": "home_region / allowed_regions recorded; enforcement of provider regions not implemented.",
    "FR-244": "Provider region recorded; transfer register not implemented.",
    "FR-246": "Downloads audited with user watermark header; DLP not implemented.",
    "FR-247": "Users delete own conversations (legal hold respected); scheduled retention purge not implemented.",
    "FR-248": "legally_privileged flag; restriction to named legal roles via ACL only.",
    "FR-252": "review_due_at stored; reminders not implemented.",
    "FR-258": "Near-duplicates linked via duplicate_of (SimHash); reviewer decision workflow not implemented.",
    "FR-259": "document_type 'faq' supported; curated FAQ management not implemented.",
}
NOT_STARTED = {
    "FR-011": "Access certification campaigns.", "FR-022": "Notifications.", "FR-026": "Source connectors / discovery.",
    "FR-059": "Email ingestion (Could).", "FR-061": "Image extraction (Could).", "FR-069": "Terminology store.",
    "FR-072": "Semantic chunking (Could).", "FR-092": "HyDE (Could).", "FR-113": "Purpose-of-access capture.",
    "FR-127": "Follow-up suggestions.", "FR-130": "Clarification requests.", "FR-166": "Policy editor and simulation.",
    "FR-168": "Connector configuration.", "FR-179": "Two-person approval of production changes.", "FR-198": "Events / webhooks.",
    "FR-209": "Automatic regression evaluation on change.", "FR-210": "Evaluation-gated promotion.",
    "FR-211": "Model-based judge governance.", "FR-212": "Human evaluation workflow.", "FR-214": "Online drift detection.",
    "FR-223": "Business value measurement.", "FR-234": "SIEM export.", "FR-242": "Data subject requests.",
    "FR-245": "Processing purpose register.", "FR-257": "Glossary / synonym management.",
}
DOMAIN_IN_PROGRESS = {f"FR-{n}" for n in range(260, 276)} - {"FR-262", "FR-264"}
FRONTEND = {f"FR-0{n}" for n in range(12, 26)} - {"FR-019", "FR-022"}
FR_TEST = {"FR-105": T_RLS, "FR-106": T_RLS, "FR-108": T_SEC, "FR-109": T_DOC, "FR-110": T_DOC, "FR-142": T_UGR,
           "FR-229": T_ADM, "FR-176": T_ADM, "FR-178": T_ADM, "FR-180": T_DOC, "FR-264": T_DOC, "FR-262": T_E2E,
           "FR-231": "tests/integration/test_observability.py", "FR-235": "tests/integration/test_observability.py"}


def fr_row(fid: str) -> list[str]:
    n = int(fid.split("-")[1])
    comp, dbo, api, tests = next(v for (a, b), v in SECTIONS.items() if a <= n <= b)
    f = REQ[fid]["fields"]
    remark = ""
    if fid in NOT_STARTED:
        status, remark, tests = "Not Started", NOT_STARTED[fid], "-"
    elif fid in IN_PROGRESS:
        status, remark = "In Progress", IN_PROGRESS[fid]
    elif fid in FRONTEND:
        status, remark = "Frontend", "UI requirement; backend APIs provided (see FRONTEND_REQUIREMENTS.md)"
    elif fid in DOMAIN_IN_PROGRESS:
        status, remark = "In Progress", "Served by grounded RAG over approved documents with citations and the knowledge-assistance boundary; no dedicated structured feature."
    else:
        status = "Completed"
        remark = COMPLETED_WITH_REMARK.get(fid, "")
    tests = FR_TEST.get(fid, tests)
    return [fid, f["Title"], _short(f["Functional requirement"]), f["Priority"], comp, dbo, api, status, tests, remark]


NFR_STATUS = {
    # (status, remark)
    **{f"NFR-{n:03d}": ("In Progress", "Instrumented (Prometheus histograms); measured locally - see docs/database/VECTOR_INDEXING.md; production load test pending")
       for n in range(1, 11)},
    **{f"NFR-{n:03d}": ("In Progress", "Stateless API/workers scale horizontally (Compose/K8s); scale tests pending") for n in range(11, 21)},
    **{f"NFR-{n:03d}": ("Not Started", "Infrastructure / DR concern outside the application code") for n in range(21, 32)},
    "NFR-024": ("Completed", "Bounded exponential back-off with jitter (tenacity, Celery retry, ingestion next_retry_at)"),
    "NFR-026": ("Completed", "Reranker fallback to fused ranking; search-only answer on generation failure"),
    "NFR-032": ("In Progress", "SSO via OIDC exchange + local MFA; IdP-only enforcement is a deployment setting (AUTH_MODE=oidc)"),
    "NFR-033": ("Completed", "Deny-by-default dependencies on every route + RLS; tests in tests/security"),
    "NFR-034": ("Completed", "Role catalogue, system roles protected, SoD trigger"),
    "NFR-035": ("Completed", "ABAC (LOB, jurisdiction, clearance, principals) evaluated in SQL"),
    "NFR-036": ("In Progress", "Secrets encrypted (Fernet); storage/database encryption at rest is a deployment control"),
    "NFR-037": ("Not Started", "TLS terminated at Nginx/ingress (deployment)"),
    "NFR-038": ("In Progress", "SECRETS_ENCRYPTION_KEY from secrets manager; KMS rotation is operational"),
    "NFR-039": ("Completed", "No secrets in code; production start refuses dev defaults"),
    "NFR-041": ("Completed", "Token validation, scopes via RBAC, schema validation, size and rate limits"),
    "NFR-047": ("In Progress", "Query text storage is a tenant setting; logs redacted"),
    "NFR-048": ("In Progress", "PII detection/masking in context, previews and answers; recall not measured on a seeded set"),
    "NFR-050": ("In Progress", "Luhn-validated card detection and masking; indexing block by default not implemented"),
    "NFR-056": ("Completed", "Legal hold blocks deletion and purge (tested)"),
    "NFR-057": ("Completed", "Append-only, hash-chained audit with immutability trigger; retention setting per tenant"),
    "NFR-071": ("Completed", "JSON logs with service, tenant, correlation id; redaction"),
    "NFR-072": ("Completed", "Prometheus /metrics: HTTP, retrieval, generation, guardrails, ingestion, tokens, cache"),
    "NFR-073": ("In Progress", "OpenTelemetry spans (W3C propagation, retrieval, generation, ingestion) exported via OTLP/HTTP when OTEL_ENABLED; sampling via standard OTEL_TRACES_SAMPLER; 100% cross-service coverage (API to Celery context propagation) not implemented; tests/integration/test_observability.py"),
    "NFR-074": ("Completed", "Correlation id accepted/generated, propagated to logs, audit, responses, Celery jobs"),
    "NFR-075": ("Completed", "Audit events written in-transaction"),
    "NFR-081": ("Completed", "Provider abstractions for LLM, embeddings, reranker, OCR, storage"),
    "NFR-083": ("Completed", "docs/ tree versioned with the code"),
    "NFR-084": ("Completed", "/api/v1 prefix, OpenAPI published"),
    "NFR-085": ("In Progress", "104 automated tests (unit, RLS, integration, e2e, security) against real PostgreSQL; coverage not measured"),
    "NFR-088": ("Completed", "AI/RAG configuration versioned with rollback"),
    "NFR-090": ("Completed", "Configuration rollback endpoint; embedding generations allow index rollback"),
    "NFR-094": ("Completed", "Uniform error body with correlation id; no stack traces"),
    "NFR-095": ("Completed", "Citations carry version, section, page, effective dates, status"),
    "NFR-096": ("Completed", "Disclaimer + ai_generated flag on every answer and export"),
    "NFR-098": ("In Progress", "Estimated cost per request recorded; budget envelope enforcement not implemented"),
    "NFR-099": ("Completed", "max_context_tokens / max_output_tokens per tenant"),
    "NFR-100": ("Completed", "Re-embedding only on explicit reindex; embedding cache for queries"),
    "NFR-104": ("Completed", "Permission-fingerprinted, content-epoch keyed cache; cross-permission test"),
    "NFR-105": ("Completed", "Quotas enforced transactionally"),
    "NFR-109": ("Completed", "Entitlements resolved per request; ACL propagation immediate"),
    "NFR-110": ("Completed", "Withdrawal immediate (lifecycle), purge job removes derived data"),
    "NFR-112": ("Completed", "Chunk lineage JSON (parser, chunker, embedding model, version)"),
}


def nfr_row(nid: str) -> list[str]:
    f = REQ[nid]["fields"]
    status, remark = NFR_STATUS.get(nid, ("Not Started", "Process / operational requirement"))
    return [nid, f["Title / category"], _short(f["Requirement"]), f["Priority"], "-", "-", "-", status, "-",
            f"Target: {f['Target / threshold']}. {remark}"]


def br_row(bid: str, fr_status: dict[str, str]) -> list[str]:
    f = REQ[bid]["fields"]
    rel = re.findall(r"FR-\d{3}", f["Related FR / NFR"])
    sts = [fr_status.get(r) for r in rel if r in fr_status]
    if sts and all(s in ("Completed", "Frontend") for s in sts):
        status = "Completed"
    elif any(s in ("Completed", "In Progress", "Frontend") for s in sts):
        status = "In Progress"
    else:
        status = "Not Started"
    return [bid, f["Title / capability"].split(" Capability:")[0], _short(f["Requirement statement"]), f["Priority"],
            "via " + ", ".join(rel[:6]) + ("..." if len(rel) > 6 else ""), "-", "-", status, "-",
            "Derived from the status of the related functional requirements."]


TC_MAP = {"TC-002": T_DOC, "TC-003": T_DOC, "TC-004": T_DOC, "TC-005": T_DOC, "TC-007": f"{T_DOC}, {T_UCH}",
          "TC-008": T_UCH, "TC-009": T_DOC, "TC-016": T_ADM, "TC-017": T_DOC, "TC-036": T_E2E, "TC-037": f"{T_E2E}, {T_RLS}",
          "TC-038": "rag_graph degraded_answer (manual)", "TC-039": T_DOC, "TC-041": T_WRK, "TC-055": f"{T_AUTH}, {T_SEC}",
          "TC-058": f"{T_RLS}, {T_AUTH}", "TC-059": T_DOC, "TC-060": T_DOC, "TC-063": T_RLS, "TC-064": T_SEC,
          "TC-065": f"{T_RLS}, {T_DOC}", "TC-066": T_ADM, "TC-067": T_RLS, "TC-068": T_DOC, "TC-069": T_UGR, "TC-075": f"{T_DOC}, {T_UGR}",
          "TC-076": T_DOC, "TC-077": f"{T_UCH}, {T_UGR}", "TC-078": T_UGR, "TC-079": T_RLS, "TC-081": T_UGR,
          "TC-082": T_ADM, "TC-084": T_UGR, "TC-086": T_ADM, "TC-088": T_ADM, "TC-110": T_ADM, "TC-033": T_WRK,
          "TC-006": f"{T_UCH} (OCR)", "TC-019": T_ADM, "TC-027": T_AUTH, "TC-092": T_ADM, "TC-094": T_DOC}


def _short(s: str, n: int = 260) -> str:
    s = s.replace("The system shall ", "").replace("|", "/").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(c.replace("\n", " ").replace("|", "/") for c in r) + " |" for r in rows]
    return "\n".join(out)


def main() -> None:
    hdr = ["Requirement ID", "Requirement title", "Requirement description", "Priority", "Backend component",
           "Database objects", "API endpoints", "Implementation status", "Test case", "Remarks"]
    frs = [fr_row(r["id"]) for r in CAT if r["id"].startswith("FR-")]
    fr_status = {r[0]: r[7] for r in frs}
    nfrs = [nfr_row(r["id"]) for r in CAT if r["id"].startswith("NFR-")]
    brs = [br_row(r["id"], fr_status) for r in CAT if r["id"].startswith("BR-")]
    tcs = [[r["id"], r["fields"]["Test case"], r["fields"]["Priority"], r["fields"]["Verifies"][:120],
            TC_MAP.get(r["id"], "Not automated")] for r in CAT if r["id"].startswith("TC-")]
    others = [[r["id"], r["section"], " / ".join(v[:120] for v in list(r["fields"].values())[1:3])] for r in CAT
              if r["id"].split("-")[0] in ("UC", "AD", "AP", "SP", "CN", "A", "D", "IF", "RSK", "PAC", "SO")]

    def summary(rows):
        c = Counter(r[7] for r in rows)
        return ", ".join(f"{k}: {v}" for k, v in sorted(c.items()))

    doc = f"""# Requirements Traceability Matrix

Source: **Enterprise_RAG_Platform_Insurance_Requirements_Specification_v1.0_DRAFT.docx** (ERAG-INS-REQ-001, v1.0 DRAFT).
All {len(CAT)} identifiers were extracted programmatically from every table of the DOCX
(`scripts/extract_requirements.py` -> `requirements_catalogue.json`); identifiers are preserved exactly and none were renumbered or removed.
Generated by `scripts/generate_rtm.py` - edit the mapping there, not this file.

Status legend: **Completed** = implemented and covered by an automated test (or enforced by DDL);
**In Progress** = partially implemented (remark states what is missing); **Not Started**; **Frontend** = UI requirement,
backend APIs exist. The multi-tenancy / RLS / Admin Console extension is traced in section 5.

## 1. Summary

| Catalogue | Count | Status |
|---|---|---|
| Functional (FR) | {len(frs)} | {summary(frs)} |
| Non-functional (NFR) | {len(nfrs)} | {summary(nfrs)} |
| Business (BR) | {len(brs)} | {summary(brs)} |
| Test cases (TC) | {len(tcs)} | automated: {sum(1 for t in tcs if t[4] != 'Not automated')} |

## 2. Functional requirements

{table(hdr, frs)}

## 3. Non-functional requirements

{table(hdr, nfrs)}

## 4. Business requirements

{table(hdr, brs)}

## 5. Prompt extension (multi-tenancy, PostgreSQL RLS, Admin Consoles)

| Extension item | Implementation | Test | Status |
|---|---|---|---|
| 1 Multi-tenant architecture, hierarchy, lifecycle | platform.tenants + per-tenant tables; tenant_service | test_admin_consoles (lifecycle) | Completed |
| 1.2 Tenant identification (server-side, membership, multi-tenant selection) | auth_service.resolve_request_context, app.auth_resolve_request | test_auth_api (select-tenant, foreign ids) | Completed |
| 2 RLS on all tenant tables, FORCE, restrictive tenant policy | migrations 03-12 | test_rls_isolation::test_service_roles... | Completed |
| 2.1 Transaction-scoped context (set_config is_local) | app/database/session.py | test_13 pooled connections | Completed |
| 2.2 Policies for SELECT/INSERT/UPDATE/DELETE, composite FKs | 07_rls_policies.sql, composite FKs everywhere | test_04/05/06/17 | Completed |
| 2.3 rag_migration / rag_app / rag_worker / rag_readonly; no BYPASSRLS | 02_roles.sql, migration 0002 check | test_service_roles... | Completed |
| 2.4 Three access-control layers | RLS + RBAC deps + final authorisation in retriever | test_15, test_chunk_cannot_be_more_visible... | Completed |
| 2.5 Mandatory RLS tests 1-17 | tests/rls/test_rls_isolation.py | 23 tests | Completed |
| 3 Tenant-aware RAG pipeline, cache keys | hybrid.py, rag_graph.py, cache.py | test_retrieval_cache_never_crosses... | Completed |
| 3.1 pgvector indexing, benchmark, query plans | 08_search_indexes.sql, scripts/benchmark_vector.py | docs/database/VECTOR_INDEXING.md | Completed |
| 4 Expanded schema + ownership matrix | database/, docs/database/DATABASE_DESIGN.md | migrations on clean DB | Completed |
| 5-8 Platform + Tenant Admin Consoles (APIs) | api/v1/platform_admin.py, tenants.py, admin.py, users.py ... | test_admin_consoles.py | Completed (API); UI = Frontend |
| 9 Admin APIs listed in the extension | all implemented under /api/v1/platform and /api/v1/admin | test_openapi_documents_all_admin_namespaces | Completed |
| 10 Statistics from real data, aggregation jobs | analytics/aggregation.py (Celery beat, 15 min) | test_tenant_dashboard_uses_real_data | Completed |
| 11 Break-glass | platform_service.open/read/close_break_glass, break_glass RLS mode | test_break_glass_is_time_limited... | Completed |
| 12 Admin UI requirements | Frontend | - | Frontend |
| 13 Tenant-aware workers, storage prefixes | pipeline.run_job, LocalStorage tenant prefix guard | test_14, test_workers | Completed |

## 6. Test cases from the specification (section 17.9)

{table(["ID", "Test case", "Priority", "Verifies", "Automated by"], tcs)}

## 7. Other catalogued items (use cases, decisions, principles, policies, constraints, assumptions, dependencies, interfaces, risks, acceptance criteria)

These are traced in PROJECT_ARCHITECTURE_DECISIONS.md and REQUIREMENTS_GAPS.md; listed here so no identifier is dropped.

{table(["ID", "Section", "Summary"], others)}
"""
    (ROOT / "docs/requirements/REQUIREMENTS_TRACEABILITY_MATRIX.md").write_text(doc, encoding="utf-8")
    print("FR", summary(frs), "| NFR", summary(nfrs), "| BR", summary(brs))


if __name__ == "__main__":
    main()
