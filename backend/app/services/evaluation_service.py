"""RAG evaluation: golden datasets, runs and results (FR-192, FR-200..FR-215).

Retrieval runs execute under the *evaluator's own user permissions* (a test
persona), never under an administrative content-bypass, so evaluation also
proves the permission model (FR-208).  Each run records a configuration
snapshot for reproducibility (FR-213).
"""
from __future__ import annotations

import json
import statistics
import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.database.session import SecurityContext, scoped_session
from app.rag.citations.validator import validate_citations
from app.rag.embeddings.providers import normalise_terms
from app.rag.evaluation.metrics import DEFAULT_GATES, dedupe_preserving, hit_rate, ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank
from app.rag.retrieval.hybrid import HybridRetriever, SearchFilters
from app.rag.workflows.rag_graph import RagWorkflow
from app.security.context import RequestContext
from app.services import config_service
from app.services.audit import tenant_audit


def create_dataset(db: Session, sec: SecurityContext, name: str, purpose: str, description: str | None) -> dict[str, Any]:
    did = uuid.uuid4()
    version = int(db.execute(text("SELECT COALESCE(max(version), 0) + 1 FROM eval.evaluation_datasets WHERE name = :n"),
                             {"n": name}).scalar_one())
    db.execute(text("""INSERT INTO eval.evaluation_datasets (tenant_id, dataset_id, name, version, purpose, description, created_by)
                       VALUES (:t, :d, :n, :v, :p, :ds, :by)"""),
               {"t": sec.tenant_id, "d": did, "n": name, "v": version, "p": purpose, "ds": description, "by": sec.user_id})
    tenant_audit(db, tenant_id=sec.tenant_id, category="configuration", event_type="evaluation_dataset_created",  # type: ignore[arg-type]
                 actor_user_id=sec.user_id, resource_type="evaluation_dataset", resource_id=did)
    return get_dataset(db, did)


def get_dataset(db: Session, dataset_id: uuid.UUID) -> dict[str, Any]:
    row = db.execute(text("SELECT * FROM eval.evaluation_datasets WHERE dataset_id = :d"), {"d": dataset_id}).mappings().first()
    if row is None:
        raise NotFound("Dataset not found")
    out = dict(row)
    out["questions"] = [dict(q) for q in db.execute(text(
        "SELECT * FROM eval.evaluation_questions WHERE dataset_id = :d ORDER BY created_at"), {"d": dataset_id}).mappings().all()]
    return out


def list_datasets(db: Session) -> list[dict[str, Any]]:
    return [dict(r) for r in db.execute(text("""SELECT d.*, (SELECT count(*) FROM eval.evaluation_questions q
                                                              WHERE q.dataset_id = d.dataset_id) AS question_count
                                                  FROM eval.evaluation_datasets d ORDER BY d.created_at DESC""")).mappings().all()]


def add_questions(db: Session, sec: SecurityContext, dataset_id: uuid.UUID, questions: list[dict[str, Any]]) -> int:
    get_dataset(db, dataset_id)
    for q in questions:
        db.execute(text("""INSERT INTO eval.evaluation_questions (tenant_id, dataset_id, question, expected_answer,
                                  expected_document_ids, expected_chunk_ids, answerable, category, line_of_business,
                                  jurisdiction, difficulty, is_critical)
                           VALUES (:t, :d, :q, :a, CAST(:docs AS uuid[]), CAST(:chunks AS uuid[]), :ans, :cat, :lob, :jur, :dif, :crit)"""),
                   {"t": sec.tenant_id, "d": dataset_id, "q": q["question"], "a": q.get("expected_answer"),
                    "docs": [str(x) for x in q.get("expected_document_ids") or []],
                    "chunks": [str(x) for x in q.get("expected_chunk_ids") or []], "ans": q.get("answerable", True),
                    "cat": q.get("category"), "lob": q.get("line_of_business"), "jur": q.get("jurisdiction"),
                    "dif": q.get("difficulty"), "crit": q.get("is_critical", False)})
    return len(questions)


def approve_dataset(db: Session, sec: SecurityContext, dataset_id: uuid.UUID) -> dict[str, Any]:
    ds = get_dataset(db, dataset_id)
    if ds["created_by"] == sec.user_id:
        raise ValidationFailed("The approver must differ from the dataset author (FR-200)")
    db.execute(text("UPDATE eval.evaluation_datasets SET status = 'approved', approved_by = :u WHERE dataset_id = :d"),
               {"u": sec.user_id, "d": dataset_id})
    return get_dataset(db, dataset_id)


def run_evaluation(ctx: RequestContext, dataset_id: uuid.UUID, *, mode: str = "retrieval", k: int = 10,
                   gates: dict[str, float] | None = None) -> dict[str, Any]:
    if mode not in ("retrieval", "end_to_end"):
        raise ValidationFailed("mode must be retrieval or end_to_end")
    gates = {**DEFAULT_GATES, **(gates or {})}
    admin = ctx.security("tenant_admin")
    run_id = uuid.uuid4()
    with scoped_session(admin) as db:
        ds = get_dataset(db, dataset_id)
        ai, rag = config_service.active_ai_config(db), config_service.active_rag_config(db)
        snapshot = {"ai_config": ai.__dict__, "rag_config": {k_: v for k_, v in rag.__dict__.items()},
                    "evaluator_user_id": str(ctx.user_id), "k": k}
        db.execute(text("""INSERT INTO eval.evaluation_runs (tenant_id, run_id, dataset_id, status, mode, k, config_snapshot,
                                  evaluator_user_id, initiated_by, started_at)
                           VALUES (:t, :r, :d, 'running', :m, :k, CAST(:s AS jsonb), :u, :u, now())"""),
                   {"t": ctx.tenant_id, "r": run_id, "d": dataset_id, "m": mode, "k": k,
                    "s": json.dumps(snapshot, default=str), "u": ctx.user_id})
    rows: list[dict[str, Any]] = []
    for q in ds["questions"]:
        t0 = time.perf_counter()
        with scoped_session(ctx.security("user")) as db:  # evaluator persona: normal user permissions
            filters = SearchFilters()
            out = HybridRetriever(db, ctx, rag, ai).search(q["question"], filters, mode="hybrid", top_k=k)
            docs = dedupe_preserving([str(r.document_id) for r in out.results])
            chunks = [str(r.chunk_id) for r in out.results]
            exp_docs = {str(x) for x in q["expected_document_ids"] or []}
            exp_chunks = {str(x) for x in q["expected_chunk_ids"] or []}
            retrieved, relevant = (chunks, exp_chunks) if exp_chunks else (docs, exp_docs)
            m: dict[str, Any] = {}
            if q["answerable"] and relevant:
                m.update(recall_at_k=recall_at_k(retrieved, relevant, k), precision_at_k=precision_at_k(retrieved, relevant, k),
                         mrr=reciprocal_rank(retrieved, relevant), ndcg_at_k=ndcg_at_k(retrieved, relevant, k),
                         hit_rate=hit_rate(retrieved, relevant, k))
            status = None
            if mode == "end_to_end":
                tenant = db.execute(text("SELECT name FROM platform.tenants WHERE tenant_id = :t"), {"t": ctx.tenant_id}).scalar()
                st = RagWorkflow(db, ctx, rag, ai, tenant or "").run(q["question"], [], SearchFilters())
                status = st["status"]
                abstained = status in ("abstained", "blocked")
                m["abstention_correct"] = abstained != bool(q["answerable"])
                if not abstained:
                    passages = {f"S{i}": c.content for i, c in enumerate(st.get("context") or [], start=1)}
                    rep = validate_citations(st["answer"], passages)
                    m["citation_coverage"] = rep.coverage
                    m["faithfulness"] = 1.0 - (len(rep.unsupported) / max(1, len(rep.cited))) if rep.cited else 0.0
                    if q.get("expected_answer"):
                        exp_terms = set(normalise_terms(q["expected_answer"]))
                        got = set(normalise_terms(st["answer"]))
                        m["answer_relevance"] = round(len(exp_terms & got) / max(1, len(exp_terms)), 3)
                m["tokens"] = (st.get("usage") or {}).get("input_tokens", 0) + (st.get("usage") or {}).get("output_tokens", 0)
        latency = int((time.perf_counter() - t0) * 1000)
        rows.append({"question_id": q["question_id"], "chunks": chunks, "docs": docs, "metrics": m, "status": status,
                     "latency": latency, "critical": q["is_critical"]})
    summary: dict[str, Any] = {"questions": len(rows)}
    keys = {"recall_at_k", "precision_at_k", "mrr", "ndcg_at_k", "hit_rate", "citation_coverage", "faithfulness",
            "answer_relevance"}
    for key in keys:
        vals = [r["metrics"][key] for r in rows if key in r["metrics"]]
        if vals:
            summary[key] = round(statistics.fmean(vals), 4)
    ab = [r["metrics"]["abstention_correct"] for r in rows if "abstention_correct" in r["metrics"]]
    if ab:
        summary["abstention_accuracy"] = round(sum(ab) / len(ab), 4)
    lat = [r["latency"] for r in rows]
    if lat:
        summary["p95_latency_ms"] = sorted(lat)[max(0, int(len(lat) * 0.95) - 1)]
    gate_results = {g: summary[g] >= thr for g, thr in gates.items() if g in summary}
    gate_passed = all(gate_results.values()) if gate_results else None
    summary["gates"] = {"thresholds": {g: gates[g] for g in gate_results}, "results": gate_results}
    with scoped_session(admin) as db:
        for r in rows:
            passed = None
            if r["metrics"]:
                passed = all(r["metrics"].get(g, 1) >= gates.get(g, 0) for g in ("recall_at_k",) if g in r["metrics"])
            db.execute(text("""INSERT INTO eval.evaluation_results (tenant_id, run_id, question_id, retrieved_chunk_ids,
                                      retrieved_document_ids, metrics, answer_status, passed, latency_ms)
                               VALUES (:t, :r, :q, CAST(:c AS uuid[]), CAST(:d AS uuid[]), CAST(:m AS jsonb), :s, :p, :l)"""),
                       {"t": ctx.tenant_id, "r": run_id, "q": r["question_id"], "c": r["chunks"], "d": r["docs"],
                        "m": json.dumps(r["metrics"]), "s": r["status"], "p": passed, "l": r["latency"]})
        db.execute(text("""UPDATE eval.evaluation_runs SET status = 'succeeded', finished_at = now(), summary = CAST(:s AS jsonb),
                                  gate_passed = :g WHERE run_id = :r"""),
                   {"s": json.dumps(summary), "g": gate_passed, "r": run_id})
        tenant_audit(db, tenant_id=ctx.tenant_id, category="configuration", event_type="evaluation_run_completed",  # type: ignore[arg-type]
                     actor_user_id=ctx.user_id, resource_type="evaluation_run", resource_id=run_id,
                     detail={"dataset_id": str(dataset_id), "gate_passed": gate_passed, "mode": mode})
        return get_run(db, run_id)


def get_run(db: Session, run_id: uuid.UUID) -> dict[str, Any]:
    row = db.execute(text("SELECT * FROM eval.evaluation_runs WHERE run_id = :r"), {"r": run_id}).mappings().first()
    if row is None:
        raise NotFound("Run not found")
    out = dict(row)
    out["results"] = [dict(r) for r in db.execute(text(
        "SELECT question_id, metrics, answer_status, passed, latency_ms, retrieved_document_ids FROM eval.evaluation_results "
        "WHERE run_id = :r"), {"r": run_id}).mappings().all()]
    return out


def list_runs(db: Session, dataset_id: uuid.UUID | None, limit: int = 50) -> list[dict[str, Any]]:
    where = "WHERE dataset_id = :d" if dataset_id else ""
    return [dict(r) for r in db.execute(text(f"""SELECT run_id, dataset_id, status, mode, k, summary, gate_passed, started_at,
                                                       finished_at FROM eval.evaluation_runs {where}
                                                 ORDER BY created_at DESC LIMIT :l"""),
                                        {"d": dataset_id, "l": limit}).mappings().all()]
