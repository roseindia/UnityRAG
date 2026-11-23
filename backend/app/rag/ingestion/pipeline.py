"""Asynchronous, idempotent ingestion pipeline (spec 6.3, FR-026..FR-053,
extension 13).

Executed by the worker under a *worker* security context bound to exactly one
tenant (the job's tenant, read from the job row - never from the message
payload alone; the payload's tenant must match).  Every retry re-establishes
the same context.  Persisting chunks / embeddings is one transaction: either the
new version is fully indexed and published (atomic switch from the previous
version, FR-047) or nothing changes.

Stages: validate tenant -> load -> malware scan -> parse (+OCR) -> normalise ->
classify + insurance metadata -> near-duplicate check -> chunk -> injection /
PII scan -> embed -> persist pages, chunks, embeddings (FTS generated) ->
verify -> publish -> ACL propagation -> audit + metrics.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import SecurityContext, scoped_session
from app.integrations.malware import MalwareDetected, ScannerUnavailable, scan_bytes
from app.integrations.provider_registry import resolve_provider
from app.integrations.storage import get_storage
from app.observability.metrics import INGESTION_JOBS, INGESTION_STAGE_LATENCY
from app.observability.tracing import span
from app.rag.chunking.chunker import CHUNKER_VERSION, Chunk, chunk_document
from app.rag.embeddings.providers import build_embeddings, vector_literal
from app.rag.guardrails.detectors import RULES_VERSION, scan_injection, sensitivity_tags
from app.rag.ingestion.insurance_metadata import extract_metadata
from app.rag.parsers.base import ParsedDocument, UnsupportedFormat
from app.rag.parsers.registry import parse_document
from app.services import config_service
from app.services.audit import tenant_audit
from app.services.usage_service import record_model_usage

log = logging.getLogger("app.ingestion")

TRANSIENT = (OperationalError, httpx.TransportError, httpx.TimeoutException, TimeoutError, ScannerUnavailable,
             ConnectionError)


class PermanentIngestionError(Exception):
    def __init__(self, code: str, message: str, quarantine: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.quarantine = quarantine


class TenantNotOperational(Exception):
    pass


@dataclass
class JobOutcome:
    status: str
    chunks: int = 0
    pages: int = 0
    detail: dict[str, Any] | None = None


def _ctx(tenant_id: uuid.UUID, user_id: uuid.UUID | None) -> SecurityContext:
    return SecurityContext.worker(tenant_id, user_id)


def _stage(tenant_id: uuid.UUID, job_id: uuid.UUID, stage: str, message: str, level: str = "info",
           detail: dict[str, Any] | None = None) -> None:
    """Progress is written in its own short transaction so monitoring sees it live."""
    with scoped_session(_ctx(tenant_id, None), role="worker") as db:
        db.execute(text("UPDATE ingest.ingestion_jobs SET stage = :s WHERE job_id = :j"), {"s": stage, "j": job_id})
        db.execute(text("""INSERT INTO ingest.ingestion_job_logs (tenant_id, job_id, stage, level, message, detail)
                           VALUES (:t, :j, :s, :l, :m, CAST(:d AS jsonb))"""),
                   {"t": tenant_id, "j": job_id, "s": stage, "l": level, "m": message[:1000],
                    "d": json.dumps(detail or {}, default=str)})


def _remove_repeated_headers(doc: ParsedDocument) -> int:
    """Identify repeated headers / footers (FR-063) and drop them from page text."""
    if len(doc.pages) < 3:
        return 0
    edges: Counter[str] = Counter()
    for p in doc.pages:
        lines = [l.strip() for l in p.text.split("\n") if l.strip()]
        for l in lines[:2] + lines[-2:]:
            edges[re.sub(r"\d+", "#", l)] += 1
    repeated = {k for k, v in edges.items() if v >= max(3, int(len(doc.pages) * 0.6)) and len(k) < 120}
    removed = 0
    for p in doc.pages:
        kept = []
        for l in p.text.split("\n"):
            if re.sub(r"\d+", "#", l.strip()) in repeated:
                removed += 1
                continue
            kept.append(l)
        p.text = "\n".join(kept)
    return removed


def _simhash(text_: str) -> int:
    v = [0] * 64
    for w in re.findall(r"\w{3,}", text_.lower()):
        h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "big")
        for i in range(64):
            v[i] += 1 if h >> i & 1 else -1
    return sum(1 << i for i in range(64) if v[i] > 0)


def _load(db: Session, job_id: uuid.UUID) -> dict[str, Any]:
    row = db.execute(text("""
        SELECT j.*, d.collection_id, d.title, d.document_type, d.insurance_line, d.jurisdictions, d.effective_from,
               d.effective_to, d.classification, d.classification_confidence, d.current_version_id, d.legal_hold,
               d.lifecycle_state, v.storage_uri, v.original_filename, v.checksum_sha256, v.version_seq,
               c.auto_publish, t.status AS tenant_status
          FROM ingest.ingestion_jobs j
          JOIN platform.tenants t ON t.tenant_id = j.tenant_id
          LEFT JOIN content.documents d ON d.document_id = j.document_id
          LEFT JOIN content.document_versions v ON v.version_id = j.version_id
          LEFT JOIN content.collections c ON c.collection_id = d.collection_id
         WHERE j.job_id = :j FOR UPDATE OF j"""), {"j": job_id}).mappings().first()
    if row is None:
        raise PermanentIngestionError("job_not_found", "job not found in tenant context")
    return dict(row)


def run_job(tenant_id: uuid.UUID, job_id: uuid.UUID) -> JobOutcome:
    """Entry point used by the Celery task (and synchronously by tests)."""
    with span("ingestion.job", **{"tenant.id": str(tenant_id), "ingestion.job_id": str(job_id)}) as sp:
        outcome = _run_job(tenant_id, job_id)
        sp.set_attribute("ingestion.status", outcome.status)
        sp.set_attribute("ingestion.chunks", outcome.chunks)
        return outcome


def _run_job(tenant_id: uuid.UUID, job_id: uuid.UUID) -> JobOutcome:
    t0 = time.perf_counter()
    with scoped_session(_ctx(tenant_id, None), role="worker") as db:
        job = _load(db, job_id)
        if job["tenant_id"] != tenant_id:  # defence in depth; RLS already guarantees this
            raise PermanentIngestionError("tenant_mismatch", "job tenant does not match task tenant")
        if job["status"] in ("succeeded", "cancelled", "dead_letter"):
            return JobOutcome(status=job["status"])  # idempotent replay
        if job["tenant_status"] not in ("active", "trial") and job["job_type"] != "delete":
            db.execute(text("UPDATE ingest.ingestion_jobs SET status = 'deferred', stage = 'tenant_not_operational' "
                            "WHERE job_id = :j"), {"j": job_id})
            raise TenantNotOperational(job["tenant_status"])
        db.execute(text("""UPDATE ingest.ingestion_jobs SET status = 'running', attempt = attempt + 1,
                                  started_at = COALESCE(started_at, now()), error_code = NULL, error_message = NULL
                            WHERE job_id = :j"""), {"j": job_id})
    initiated_by = job["initiated_by"]
    try:
        if job["job_type"] == "delete":
            outcome = _purge(tenant_id, job)
        elif job["job_type"] == "reembed":
            outcome = _reembed(tenant_id, job)
        else:
            outcome = _ingest(tenant_id, job)
    except Exception as exc:
        _record_failure(tenant_id, job, exc)
        raise
    with scoped_session(_ctx(tenant_id, initiated_by), role="worker") as db:
        db.execute(text("""UPDATE ingest.ingestion_jobs SET status = 'succeeded', stage = 'done', finished_at = now(),
                                  stats = CAST(:s AS jsonb) WHERE job_id = :j"""),
                   {"j": job_id, "s": json.dumps({"chunks": outcome.chunks, "pages": outcome.pages,
                                                  "seconds": round(time.perf_counter() - t0, 2), **(outcome.detail or {})})})
        db.execute(text("UPDATE platform.tenant_usage SET active_ingestion_jobs = GREATEST(active_ingestion_jobs - 1, 0) "
                        "WHERE tenant_id = :t"), {"t": tenant_id})
        tenant_audit(db, tenant_id=tenant_id, category="ingestion", event_type=f"{job['job_type']}_succeeded",
                     actor_type="service", actor_user_id=initiated_by, resource_type="document",
                     resource_id=job["document_id"], detail={"job_id": str(job_id), "chunks": outcome.chunks,
                                                              "status": outcome.status})
    INGESTION_JOBS.labels("succeeded").inc()
    return outcome


def _record_failure(tenant_id: uuid.UUID, job: dict[str, Any], exc: Exception) -> None:
    transient = isinstance(exc, TRANSIENT)
    quarantine = isinstance(exc, MalwareDetected) or (isinstance(exc, PermanentIngestionError) and exc.quarantine)
    code = getattr(exc, "code", None) or type(exc).__name__
    exhausted = job["attempt"] + 1 >= job["max_attempts"]
    if isinstance(exc, TenantNotOperational):
        status = "deferred"
    elif transient and not exhausted:
        status = "retrying"
    elif transient:
        status = "dead_letter"
    else:
        status = "failed"
    message = str(exc)[:500]
    with scoped_session(_ctx(tenant_id, job["initiated_by"]), role="worker") as db:
        db.execute(text("""UPDATE ingest.ingestion_jobs SET status = :s, error_code = :c, error_message = :m,
                                  finished_at = CASE WHEN :s IN ('failed', 'dead_letter') THEN now() END,
                                  next_retry_at = CASE WHEN :s = 'retrying' THEN now() + make_interval(secs => LEAST(300, 2 ^ attempt * 5)) END
                            WHERE job_id = :j"""), {"s": status, "c": code[:80], "m": message, "j": job["job_id"]})
        db.execute(text("""INSERT INTO ingest.ingestion_job_logs (tenant_id, job_id, stage, level, message, detail)
                           VALUES (:t, :j, 'error', 'error', :m, CAST(:d AS jsonb))"""),
                   {"t": tenant_id, "j": job["job_id"], "m": f"{code}: {message}",
                    "d": json.dumps({"transient": transient, "attempt": job["attempt"] + 1, "status": status})})
        if job["document_id"] and status in ("failed", "dead_letter"):
            new_state = "quarantined" if quarantine else "failed"
            db.execute(text("""UPDATE content.documents SET lifecycle_state = :st
                                WHERE document_id = :d AND current_version_id IS NULL"""),
                       {"st": new_state, "d": job["document_id"]})
            db.execute(text("UPDATE content.document_versions SET state = :st WHERE version_id = :v"),
                       {"st": "quarantined" if quarantine else "failed", "v": job["version_id"]})
        if status in ("failed", "dead_letter"):
            db.execute(text("UPDATE platform.tenant_usage SET active_ingestion_jobs = GREATEST(active_ingestion_jobs - 1, 0) "
                            "WHERE tenant_id = :t"), {"t": tenant_id})
        tenant_audit(db, tenant_id=tenant_id, category="ingestion", event_type=f"{job['job_type']}_{status}",
                     outcome="failure", actor_type="service", actor_user_id=job["initiated_by"],
                     resource_type="document", resource_id=job["document_id"],
                     detail={"job_id": str(job["job_id"]), "error_code": code, "quarantine": quarantine})
        if quarantine:
            db.execute(text("""INSERT INTO ai.guardrail_events (tenant_id, stage, rule_id, rule_version, decision, severity,
                                      category, detail) VALUES (:t, 'ingestion', :r, :v, 'quarantine', 'high', 'malware_or_active_content',
                                      CAST(:d AS jsonb))"""),
                       {"t": tenant_id, "r": code[:60], "v": RULES_VERSION,
                        "d": json.dumps({"document_id": str(job["document_id"])})})
    INGESTION_JOBS.labels(status).inc()


def _ingest(tenant_id: uuid.UUID, job: dict[str, Any]) -> JobOutcome:
    s = get_settings()
    job_id, doc_id, ver_id = job["job_id"], job["document_id"], job["version_id"]
    if doc_id is None or ver_id is None:
        raise PermanentIngestionError("missing_document", "job has no document version")
    timings: dict[str, float] = {}

    def timed(stage: str):
        class _T:
            def __enter__(self_inner):
                self_inner.t = time.perf_counter()

            def __exit__(self_inner, *a):
                timings[stage] = round(time.perf_counter() - self_inner.t, 3)
                INGESTION_STAGE_LATENCY.labels(stage).observe(timings[stage])
        return _T()

    _stage(tenant_id, job_id, "load", "loading original file")
    data = get_storage().get(tenant_id, job["storage_uri"])
    if hashlib.sha256(data).hexdigest() != job["checksum_sha256"]:
        raise PermanentIngestionError("checksum_mismatch", "stored file does not match recorded checksum", quarantine=True)

    with timed("malware_scan"):
        verdict = scan_bytes(data)
    if not verdict.clean:
        raise MalwareDetected(verdict.signature or "unknown")
    _stage(tenant_id, job_id, "malware_scan", "scan skipped (no scanner configured)" if verdict.skipped else "clean",
           level="warning" if verdict.skipped else "info", detail={"scanner": verdict.scanner})

    try:
        with timed("parse"):
            parsed = parse_document(data, job["original_filename"])
    except UnsupportedFormat as exc:
        raise PermanentIngestionError("unsupported_format", str(exc)) from exc
    if any(f in ("pdf_javascript", "pdf_auto_action", "pdf_embedded_files") for f in parsed.security_flags):
        # Active content is never parsed further (FR-137): quarantine for review.
        raise PermanentIngestionError("active_content", ",".join(parsed.security_flags), quarantine=True)
    removed = _remove_repeated_headers(parsed)
    ocr_pages = [p for p in parsed.pages if p.extraction == "ocr"]
    low_conf = [p.page_number for p in parsed.pages if p.ocr_confidence is not None and p.ocr_confidence < s.ocr_min_confidence]
    full_text = parsed.full_text
    if not full_text.strip():
        raise PermanentIngestionError("no_text", "no extractable text (OCR unavailable or empty document)")
    _stage(tenant_id, job_id, "parse", f"parsed {len(parsed.pages)} pages with {parsed.parser}",
           detail={"format": parsed.format, "ocr_pages": len(ocr_pages), "low_confidence_pages": low_conf,
                   "security_flags": parsed.security_flags, "headers_removed": removed})

    with timed("metadata"):
        meta = extract_metadata(job["title"] or parsed.title, full_text)

    with scoped_session(_ctx(tenant_id, job["initiated_by"]), role="worker") as db:
        rag = config_service.active_rag_config(db)
        ai = config_service.active_ai_config(db)
        endpoint = resolve_provider(db, ai.embedding_provider)
        # near-duplicate detection (FR-039)
        sim = _simhash(full_text)
        dup_of = None
        for other_doc, value in db.execute(text("""SELECT v.document_id, m.value FROM content.document_metadata m
                                                    JOIN content.document_versions v ON v.version_id = m.version_id
                                                   WHERE m.key = 'content_simhash' AND v.document_id <> :d"""),
                                           {"d": doc_id}).all():
            if bin(int(value) ^ sim).count("1") <= 3:
                dup_of = other_doc
                break

    with timed("chunk"):
        chunks = chunk_document(parsed.pages, strategy=rag.chunking_strategy, chunk_size=rag.chunk_size,
                                chunk_overlap=rag.chunk_overlap, parent_child=rag.parent_child,
                                title=job["title"] or parsed.title)
    if not chunks:
        raise PermanentIngestionError("no_chunks", "document produced no chunks")
    page_conf = {p.page_number: p.ocr_confidence for p in parsed.pages}
    flagged: list[tuple[Chunk, str]] = []
    tags: dict[int, list[str]] = {}
    for c in chunks:
        res = scan_injection(c.text)
        if res.flagged:
            flagged.append((c, ",".join(d.rule_id for d in res.detections)))
        tags[c.index] = sensitivity_tags(c.text)
    _stage(tenant_id, job_id, "chunk", f"{len(chunks)} chunks ({CHUNKER_VERSION})",
           detail={"injection_flagged": len(flagged), "strategy": rag.chunking_strategy})

    embeddable = [c for c in chunks if c.chunk_type != "parent"]
    embedder = build_embeddings(endpoint, ai.embedding_model, ai.embedding_dimensions)
    t_emb = time.perf_counter()
    with timed("embed"):
        vectors = embedder.embed_documents([c.text for c in embeddable])
    emb_ms = int((time.perf_counter() - t_emb) * 1000)
    _stage(tenant_id, job_id, "embed", f"{len(vectors)} embeddings with {ai.embedding_model}",
           detail={"dimensions": ai.embedding_dimensions})

    with timed("persist"), scoped_session(_ctx(tenant_id, job["initiated_by"]), role="worker") as db:
        doc = db.execute(text("SELECT * FROM content.documents WHERE document_id = :d FOR UPDATE"), {"d": doc_id}).mappings().one()
        # idempotency: a retried job replaces whatever a previous attempt left for this version
        db.execute(text("DELETE FROM content.document_chunks WHERE version_id = :v"), {"v": ver_id})
        db.execute(text("DELETE FROM content.document_pages WHERE version_id = :v"), {"v": ver_id})
        db.execute(text("DELETE FROM content.document_metadata WHERE version_id = :v AND source = 'extracted'"), {"v": ver_id})
        for p in parsed.pages:
            db.execute(text("""INSERT INTO content.document_pages (tenant_id, version_id, document_id, page_number,
                                      page_label, text, extraction, ocr_confidence, low_confidence, char_count)
                               VALUES (:t, :v, :d, :n, :l, :tx, :e, :c, :lc, :cc)"""),
                       {"t": tenant_id, "v": ver_id, "d": doc_id, "n": p.page_number, "l": p.label, "tx": p.text,
                        "e": p.extraction, "c": p.ocr_confidence,
                        "lc": p.ocr_confidence is not None and p.ocr_confidence < s.ocr_min_confidence,
                        "cc": len(p.text)})
        for key, value, conf in meta.as_pairs() + [("content_simhash", str(sim), 1.0), ("format", parsed.format, 1.0)]:
            db.execute(text("""INSERT INTO content.document_metadata (tenant_id, version_id, key, value, source, confidence)
                               VALUES (:t, :v, :k, :val, 'extracted', :c) ON CONFLICT DO NOTHING"""),
                       {"t": tenant_id, "v": ver_id, "k": key, "val": value, "c": conf})
        # document-level metadata: user-supplied values win over extracted ones
        doc_type = doc["document_type"] if doc["document_type"] != "other" else meta.document_type
        db.execute(text("""UPDATE content.documents SET document_type = :dt,
                                  classification_confidence = COALESCE(classification_confidence, :conf),
                                  insurance_line = COALESCE(insurance_line, :lob),
                                  jurisdictions = CASE WHEN cardinality(jurisdictions) = 0 THEN :jur ELSE jurisdictions END,
                                  effective_from = COALESCE(effective_from, :ef), effective_to = COALESCE(effective_to, :et),
                                  duplicate_of = :dup, title = CASE WHEN (title = '' OR title = CAST(:stem AS text)) AND CAST(:title AS text) IS NOT NULL THEN CAST(:title AS text) ELSE title END
                            WHERE document_id = :d"""),
                   {"dt": doc_type, "conf": meta.document_type_confidence, "lob": meta.insurance_line,
                    "jur": meta.jurisdictions, "ef": meta.effective_from, "et": meta.effective_to, "dup": dup_of,
                    "title": parsed.title, "stem": job["original_filename"].rsplit(".", 1)[0], "d": doc_id})
        doc = db.execute(text("SELECT * FROM content.documents WHERE document_id = :d"), {"d": doc_id}).mappings().one()
        chunk_ids: dict[int, uuid.UUID] = {}
        for c in chunks:
            cid = uuid.uuid4()
            chunk_ids[c.index] = cid
            lc = any((page_conf.get(n) is not None and page_conf[n] < s.ocr_min_confidence)
                     for n in range(c.page_from, c.page_to + 1))
            db.execute(text("""INSERT INTO content.document_chunks (tenant_id, chunk_id, document_id, version_id, collection_id,
                                      parent_chunk_id, chunk_index, chunk_type, title, section_path, clause_ref, page_from,
                                      page_to, content, identifiers, fts_config, token_count, content_hash, low_confidence,
                                      injection_flag, sensitivity_tags, document_type, line_of_business, product,
                                      jurisdictions, classification_rank, lifecycle_state, effective_from, effective_to,
                                      allow_principals, deny_principals, lineage)
                               VALUES (:t, :id, :d, :v, :col, :parent, :idx, :ct, :title, :sp, :cr, :pf, :pt, :content,
                                       :ids, CAST(:fts AS regconfig), :tok, :hash, :lc, :inj, :tags, :dt, :lob, :prod,
                                       :jur, :rank, 'processing', :ef, :et, :allow, :deny, CAST(:lin AS jsonb))"""),
                       {"t": tenant_id, "id": cid, "d": doc_id, "v": ver_id, "col": doc["collection_id"],
                        "parent": chunk_ids.get(c.parent_index) if c.parent_index is not None else None,
                        "idx": c.index, "ct": c.chunk_type, "title": doc["title"], "sp": c.section_path,
                        "cr": c.clause_ref, "pf": c.page_from, "pt": c.page_to, "content": c.text,
                        "ids": " ".join(c.identifiers), "fts": _fts_config(doc["language"]), "tok": c.token_count,
                        "hash": c.content_hash, "lc": lc, "inj": any(f[0] is c for f in flagged),
                        "tags": tags[c.index], "dt": doc["document_type"], "lob": doc["insurance_line"],
                        "prod": doc["product"], "jur": doc["jurisdictions"], "rank": doc["classification_rank"],
                        "ef": doc["effective_from"], "et": doc["effective_to"], "allow": doc["allow_principals"],
                        "deny": doc["deny_principals"],
                        "lin": json.dumps({"parser": parsed.parser, "chunker": CHUNKER_VERSION,
                                           "extraction": sorted({parsed.pages[min(c.page_from, len(parsed.pages)) - 1].extraction}),
                                           "embedding_model": ai.embedding_model, "version_id": str(ver_id)})})
        db.execute(text("UPDATE content.chunk_embeddings SET is_active = false WHERE document_id = :d AND is_active"),
                   {"d": doc_id})
        for c, vec in zip(embeddable, vectors, strict=True):
            db.execute(text("""INSERT INTO content.chunk_embeddings (tenant_id, chunk_id, document_id, model_name, dimensions,
                                      embedding, classification_rank, line_of_business, jurisdictions, lifecycle_state,
                                      allow_principals, deny_principals)
                               VALUES (:t, :c, :d, :m, :dim, CAST(:e AS vector), :rank, :lob, :jur, 'processing', :allow, :deny)"""),
                       {"t": tenant_id, "c": chunk_ids[c.index], "d": doc_id, "m": ai.embedding_model,
                        "dim": ai.embedding_dimensions, "e": vector_literal(vec), "rank": doc["classification_rank"],
                        "lob": doc["insurance_line"], "jur": doc["jurisdictions"], "allow": doc["allow_principals"],
                        "deny": doc["deny_principals"]})
        # verification (spec stage 20): every chunk indexed for FTS, every embeddable chunk vectorised
        counts = db.execute(text("""SELECT count(*) FILTER (WHERE content_tsv IS NOT NULL) AS fts,
                                           (SELECT count(*) FROM content.chunk_embeddings e WHERE e.document_id = :d AND e.is_active) AS emb
                                      FROM content.document_chunks WHERE version_id = :v"""),
                            {"v": ver_id, "d": doc_id}).mappings().one()
        if counts["fts"] != len(chunks) or counts["emb"] != len(embeddable):
            raise PermanentIngestionError("verification_failed", f"index verification failed: {dict(counts)}")
        for c, rules in flagged:
            db.execute(text("""INSERT INTO ai.guardrail_events (tenant_id, user_id, stage, rule_id, rule_version, decision,
                                      severity, category, detail)
                               VALUES (:t, :u, 'ingestion', :r, :rv, 'sanitise', 'medium', 'indirect_prompt_injection',
                                       CAST(:d AS jsonb))"""),
                       {"t": tenant_id, "u": job["initiated_by"], "r": rules[:60], "rv": RULES_VERSION,
                        "d": json.dumps({"document_id": str(doc_id), "chunk_index": c.index})})
        # publication: atomic switch from previous version (FR-047, FR-250, FR-251)
        publish = bool(job["auto_publish"])
        previous = doc["current_version_id"]
        if publish:
            if previous and previous != ver_id:
                db.execute(text("UPDATE content.document_versions SET state = 'superseded' WHERE version_id = :p"), {"p": previous})
                db.execute(text("UPDATE content.document_versions SET supersedes_version_id = :p WHERE version_id = :v"),
                           {"p": previous, "v": ver_id})
            db.execute(text("""UPDATE content.document_versions SET state = 'published', published_at = now(), page_count = :pc,
                                      parser = :parser, ocr_applied = :ocr, chunker_version = :cv, embedding_model = :em,
                                      embedding_dimensions = :ed, detected_format = :fmt,
                                      extraction_confidence = :xc WHERE version_id = :v"""),
                       {"pc": len(parsed.pages), "parser": parsed.parser, "ocr": bool(ocr_pages), "cv": CHUNKER_VERSION,
                        "em": ai.embedding_model, "ed": ai.embedding_dimensions, "fmt": parsed.format,
                        "xc": _mean([p.ocr_confidence for p in ocr_pages]), "v": ver_id})
            db.execute(text("UPDATE content.documents SET lifecycle_state = 'published', current_version_id = :v WHERE document_id = :d"),
                       {"v": ver_id, "d": doc_id})
        else:
            db.execute(text("UPDATE content.document_versions SET state = 'indexed', page_count = :pc, parser = :parser WHERE version_id = :v"),
                       {"pc": len(parsed.pages), "parser": parsed.parser, "v": ver_id})
            db.execute(text("""UPDATE content.documents SET lifecycle_state = CASE WHEN current_version_id IS NULL
                                      THEN 'in_review' ELSE lifecycle_state END WHERE document_id = :d"""), {"d": doc_id})
        db.execute(text("SELECT app.refresh_document_acl(:d)"), {"d": doc_id})
        old_chunks = db.execute(text("SELECT count(*) FROM content.document_chunks WHERE document_id = :d AND version_id <> :v"),
                                {"d": doc_id, "v": ver_id}).scalar_one()
        db.execute(text("UPDATE platform.tenant_usage SET chunks_count = chunks_count + :n WHERE tenant_id = :t"),
                   {"n": len(chunks), "t": tenant_id})
        record_model_usage(db, purpose="ingestion_embedding", provider=ai.embedding_provider, model=ai.embedding_model,
                           input_tokens=sum(c.token_count for c in embeddable), output_tokens=0, latency_ms=emb_ms,
                           user_id=job["initiated_by"])
        tenant_audit(db, tenant_id=tenant_id, category="document_update",
                     event_type="version_published" if publish else "version_indexed", actor_type="service",
                     actor_user_id=job["initiated_by"], resource_type="document_version", resource_id=ver_id,
                     detail={"document_id": str(doc_id), "previous_version_id": str(previous) if previous else None,
                             "chunks": len(chunks), "superseded_chunks_retained": old_chunks,
                             "embedding_model": ai.embedding_model, "parser": parsed.parser})
    _stage(tenant_id, job_id, "publish", "published" if publish else "indexed; awaiting owner approval",
           detail={"timings": timings})
    return JobOutcome(status="published" if publish else "indexed", chunks=len(chunks), pages=len(parsed.pages),
                      detail={"timings": timings, "duplicate_of": str(dup_of) if dup_of else None})


def _fts_config(language: str | None) -> str:
    allowed = {"english", "simple", "french", "german", "spanish", "italian", "portuguese", "dutch"}
    return language if language in allowed else "english"


def _mean(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _reembed(tenant_id: uuid.UUID, job: dict[str, Any]) -> JobOutcome:
    """Re-embed a document's current chunks with the tenant's active model (FR-081)."""
    with scoped_session(_ctx(tenant_id, job["initiated_by"]), role="worker") as db:
        ai = config_service.active_ai_config(db)
        endpoint = resolve_provider(db, ai.embedding_provider)
        rows = db.execute(text("""SELECT c.chunk_id, c.content FROM content.document_chunks c
                                   JOIN content.documents d ON d.document_id = c.document_id
                                  WHERE c.document_id = :d AND c.version_id = d.current_version_id AND c.chunk_type <> 'parent'
                                  ORDER BY c.chunk_index"""), {"d": job["document_id"]}).all()
    vectors = build_embeddings(endpoint, ai.embedding_model, ai.embedding_dimensions).embed_documents([r[1] for r in rows])
    with scoped_session(_ctx(tenant_id, job["initiated_by"]), role="worker") as db:
        gen = (db.execute(text("SELECT COALESCE(max(index_generation), 0) FROM content.chunk_embeddings WHERE document_id = :d"),
                          {"d": job["document_id"]}).scalar_one() or 0) + 1
        for (cid, _), vec in zip(rows, vectors, strict=True):
            db.execute(text("""INSERT INTO content.chunk_embeddings (tenant_id, chunk_id, document_id, model_name, dimensions,
                                      index_generation, is_active, embedding)
                               VALUES (:t, :c, :d, :m, :dim, :g, false, CAST(:e AS vector))"""),
                       {"t": tenant_id, "c": cid, "d": job["document_id"], "m": ai.embedding_model,
                        "dim": ai.embedding_dimensions, "g": gen, "e": vector_literal(vec)})
        # atomic cut-over: new generation active, previous generations retired
        db.execute(text("UPDATE content.chunk_embeddings SET is_active = (index_generation = :g) WHERE document_id = :d"),
                   {"g": gen, "d": job["document_id"]})
        db.execute(text("SELECT app.refresh_document_acl(:d)"), {"d": job["document_id"]})
    return JobOutcome(status="reembedded", chunks=len(rows), detail={"generation": gen})


def _purge(tenant_id: uuid.UUID, job: dict[str, Any]) -> JobOutcome:
    """Deletion propagation to chunks, embeddings, pages, files and caches (FR-051, FR-241, NFR-110)."""
    from app.utils.cache import get_cache

    doc_id = job["document_id"]
    with scoped_session(_ctx(tenant_id, job["initiated_by"]), role="worker") as db:
        doc = db.execute(text("SELECT * FROM content.documents WHERE document_id = :d FOR UPDATE"), {"d": doc_id}).mappings().first()
        if doc is None:
            return JobOutcome(status="already_purged")
        if doc["legal_hold"]:
            raise PermanentIngestionError("legal_hold", "document is under legal hold; purge blocked")
        uris = list(db.execute(text("SELECT storage_uri FROM content.document_versions WHERE document_id = :d"), {"d": doc_id}).scalars())
        n_chunks = db.execute(text("DELETE FROM content.document_chunks WHERE document_id = :d"), {"d": doc_id}).rowcount
        db.execute(text("DELETE FROM content.document_pages WHERE document_id = :d"), {"d": doc_id})
        db.execute(text("UPDATE content.documents SET lifecycle_state = 'withdrawn', deleted_at = COALESCE(deleted_at, now()) "
                        "WHERE document_id = :d"), {"d": doc_id})
        db.execute(text("UPDATE content.document_versions SET state = 'withdrawn', withdrawn_at = now() WHERE document_id = :d"),
                   {"d": doc_id})
        db.execute(text("""UPDATE platform.tenant_usage SET chunks_count = GREATEST(chunks_count - :n, 0),
                                  storage_bytes = GREATEST(storage_bytes - :b, 0), documents_count = GREATEST(documents_count - 1, 0),
                                  content_epoch = content_epoch + 1 WHERE tenant_id = :t"""),
                   {"n": n_chunks, "b": doc["size_bytes"], "t": tenant_id})
        for uri in uris:
            get_storage().delete(tenant_id, uri)
        tenant_audit(db, tenant_id=tenant_id, category="document_deletion", event_type="purge_completed",
                     actor_type="service", actor_user_id=job["initiated_by"], resource_type="document", resource_id=doc_id,
                     detail={"chunks_purged": n_chunks, "files_purged": len(uris),
                             "stores": ["document_chunks", "chunk_embeddings", "document_pages", "object_storage", "cache"]})
    get_cache().delete_prefix(f"rag:{tenant_id}:")
    return JobOutcome(status="purged", chunks=n_chunks, detail={"files": len(uris)})
