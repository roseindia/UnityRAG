"""RAG chat, streaming, conversation persistence and citation re-verification
(FR-014, FR-017..FR-020, FR-109, FR-132, FR-187, FR-188, FR-247)."""
from __future__ import annotations

import hashlib
import json
import queue
import threading
import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.context import get_correlation_id, set_correlation_id
from app.core.errors import Conflict, NotFound, PermissionDenied
from app.database.session import scoped_session
from app.middleware.rate_limit import enforce_rate_limit
from app.rag.generation.prompts import PROMPT_VERSION
from app.rag.guardrails.detectors import RULES_VERSION
from app.rag.retrieval.hybrid import SearchFilters
from app.rag.workflows.rag_graph import RagState, RagWorkflow, persist_guardrail_events
from app.security.context import RequestContext
from app.services import config_service, quota_service
from app.services.audit import tenant_audit
from app.services.search_service import log_search
from app.services.usage_service import record_model_usage

DISCLAIMER = ("AI-generated knowledge assistance based on approved documents. Verify the cited sources; this is not "
              "a claims, underwriting or coverage decision.")


# --- conversations -----------------------------------------------------------------------
def create_conversation(db: Session, ctx: RequestContext, title: str | None, context: dict | None) -> dict[str, Any]:
    cid = uuid.uuid4()
    days = db.execute(text("SELECT conversation_retention_days FROM platform.tenant_settings WHERE tenant_id = :t"),
                      {"t": ctx.tenant_id}).scalar() or 365
    db.execute(text("""INSERT INTO rag.conversations (tenant_id, conversation_id, user_id, title, context, retention_until)
                       VALUES (:t, :c, :u, :ti, CAST(:ctx AS jsonb), CURRENT_DATE + :d)"""),
               {"t": ctx.tenant_id, "c": cid, "u": ctx.user_id, "ti": (title or "New conversation")[:200],
                "ctx": json.dumps(context or {}, default=str), "d": int(days)})
    return get_conversation(db, cid)


def get_conversation(db: Session, conversation_id: uuid.UUID) -> dict[str, Any]:
    row = db.execute(text("""SELECT conversation_id, title, context, status, message_count, legal_hold, created_at, updated_at
                               FROM rag.conversations WHERE conversation_id = :c AND status = 'active'"""),
                     {"c": conversation_id}).mappings().first()
    if row is None:
        raise NotFound("Conversation not found")
    return dict(row)


def list_conversations(db: Session, q: str | None, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    where, params = "status = 'active'", {"l": limit, "o": offset}
    if q:
        where += " AND title ILIKE :q"
        params["q"] = f"%{q}%"
    total = db.execute(text(f"SELECT count(*) FROM rag.conversations WHERE {where}"), params).scalar_one()
    rows = db.execute(text(f"""SELECT conversation_id, title, message_count, created_at, updated_at FROM rag.conversations
                               WHERE {where} ORDER BY updated_at DESC LIMIT :l OFFSET :o"""), params).mappings().all()
    return [dict(r) for r in rows], int(total)


def messages(db: Session, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    get_conversation(db, conversation_id)
    rows = db.execute(text("""SELECT message_id, seq, role, content, answer_status, evidence_strength, rewritten_query, warnings,
                                     model_name, prompt_version, input_tokens, output_tokens, latency_ms, created_at
                                FROM rag.conversation_messages WHERE conversation_id = :c ORDER BY seq"""),
                      {"c": conversation_id}).mappings().all()
    out = []
    for r in rows:
        m = dict(r)
        m["citations"] = [dict(s) for s in db.execute(text(
            """SELECT ordinal, chunk_id, document_id, version_id, title, section_path, clause_ref, page_from, page_to, verified
                 FROM rag.message_sources WHERE message_id = :m ORDER BY ordinal"""), {"m": r["message_id"]}).mappings().all()]
        out.append(m)
    return out


def rename(db: Session, conversation_id: uuid.UUID, title: str) -> dict[str, Any]:
    res = db.execute(text("UPDATE rag.conversations SET title = :t WHERE conversation_id = :c AND status = 'active'"),
                     {"t": title[:200], "c": conversation_id})
    if res.rowcount == 0:
        raise NotFound("Conversation not found")
    return get_conversation(db, conversation_id)


def delete(db: Session, ctx: RequestContext, conversation_id: uuid.UUID) -> None:
    conv = get_conversation(db, conversation_id)
    if conv["legal_hold"]:
        raise Conflict("Conversation is under legal hold", code="legal_hold")
    db.execute(text("DELETE FROM rag.conversations WHERE conversation_id = :c"), {"c": conversation_id})
    tenant_audit(db, tenant_id=ctx.tenant_id, category="document_deletion", event_type="conversation_deleted",  # type: ignore[arg-type]
                 actor_user_id=ctx.user_id, resource_type="conversation", resource_id=conversation_id)


def export(db: Session, ctx: RequestContext, conversation_id: uuid.UUID) -> dict[str, Any]:
    conv = get_conversation(db, conversation_id)
    msgs = messages(db, conversation_id)
    tenant_audit(db, tenant_id=ctx.tenant_id, category="document_access", event_type="conversation_exported",  # type: ignore[arg-type]
                 actor_user_id=ctx.user_id, resource_type="conversation", resource_id=conversation_id)
    return {"conversation": conv, "messages": msgs, "disclaimer": DISCLAIMER, "exported_by": str(ctx.user_id)}


def verified_sources(db: Session, ctx: RequestContext, message_id: uuid.UUID) -> list[dict[str, Any]]:
    """Re-verify access to every citation when it is displayed (FR-109): sources
    whose document the user can no longer see are redacted."""
    rows = db.execute(text("""SELECT s.*, (SELECT count(*) FROM content.documents d WHERE d.document_id = s.document_id
                                            AND d.deleted_at IS NULL) AS visible,
                                     (SELECT d.current_version_id <> s.version_id FROM content.documents d
                                       WHERE d.document_id = s.document_id) AS superseded
                                FROM rag.message_sources s WHERE s.message_id = :m ORDER BY ordinal"""),
                      {"m": message_id}).mappings().all()
    if not rows and not db.execute(text("SELECT 1 FROM rag.conversation_messages WHERE message_id = :m"), {"m": message_id}).first():
        raise NotFound("Message not found")
    out = []
    for r in rows:
        if not r["visible"]:
            out.append({"ordinal": r["ordinal"], "redacted": True, "reason": "access_revoked_or_document_removed"})
            continue
        out.append({"ordinal": r["ordinal"], "redacted": False, "chunk_id": r["chunk_id"], "document_id": r["document_id"],
                    "version_id": r["version_id"], "title": r["title"], "section_path": r["section_path"],
                    "clause_ref": r["clause_ref"], "page_from": r["page_from"], "page_to": r["page_to"],
                    "verified": r["verified"], "superseded": bool(r["superseded"])})
    return out


# --- asking --------------------------------------------------------------------------------
def _prepare(db: Session, ctx: RequestContext, conversation_id: uuid.UUID | None, message: str,
             filters: SearchFilters) -> tuple[uuid.UUID, list[dict[str, str]], int, str]:
    if "chat.use" not in ctx.permissions:
        raise PermissionDenied("chat permission required")
    quota_service.consume(db, ctx.security("user"), "ai_requests", 1)
    if conversation_id is None:
        conv = create_conversation(db, ctx, message[:80], {"as_of": filters.as_of.isoformat() if filters.as_of else None})
        conversation_id = conv["conversation_id"]
    else:
        get_conversation(db, conversation_id)
    hist_rows = db.execute(text("""SELECT role, content FROM rag.conversation_messages WHERE conversation_id = :c
                                   ORDER BY seq DESC LIMIT 6"""), {"c": conversation_id}).mappings().all()
    history = [{"role": r["role"], "content": r["content"]} for r in reversed(hist_rows)]
    seq = int(db.execute(text("SELECT COALESCE(max(seq), 0) FROM rag.conversation_messages WHERE conversation_id = :c"),
                         {"c": conversation_id}).scalar_one())
    tenant_name = db.execute(text("SELECT name FROM platform.tenants WHERE tenant_id = :t"), {"t": ctx.tenant_id}).scalar() or "the organisation"
    return conversation_id, history, seq, tenant_name


def _persist(db: Session, ctx: RequestContext, conversation_id: uuid.UUID, seq: int, message: str, state: RagState,
             filters: SearchFilters, rag_version: int, latency_ms: int) -> dict[str, Any]:
    cid = get_correlation_id()
    user_msg, asst_msg = uuid.uuid4(), uuid.uuid4()
    for mid, s, role, content in ((user_msg, seq + 1, "user", message), (asst_msg, seq + 2, "assistant", state["answer"])):
        db.execute(text("""INSERT INTO rag.conversation_messages (tenant_id, message_id, conversation_id, user_id, seq, role,
                                  content, content_hash, answer_status, evidence_strength, rewritten_query, warnings,
                                  model_provider, model_name, prompt_version, guardrail_version, rag_config_version,
                                  input_tokens, output_tokens, latency_ms, correlation_id)
                           VALUES (:t, :m, :c, :u, :seq, :role, :content, :hash, :st, :ev, :rq, CAST(:w AS jsonb), :prov,
                                   :model, :pv, :gv, :rv, :it, :ot, :lat, :cid)"""),
                   {"t": ctx.tenant_id, "m": mid, "c": conversation_id, "u": ctx.user_id, "seq": s, "role": role,
                    "content": content, "hash": hashlib.sha256(content.encode()).hexdigest(),
                    "st": state["status"] if role == "assistant" else None,
                    "ev": state.get("evidence_strength") if role == "assistant" else None,
                    "rq": state.get("rewritten_query") if role == "assistant" else None,
                    "w": json.dumps(state.get("warnings") or [] if role == "assistant" else []),
                    "prov": (state.get("usage") or {}).get("provider") if role == "assistant" else None,
                    "model": (state.get("usage") or {}).get("model") if role == "assistant" else None,
                    "pv": PROMPT_VERSION if role == "assistant" else None,
                    "gv": RULES_VERSION if role == "assistant" else None, "rv": rag_version,
                    "it": (state.get("usage") or {}).get("input_tokens", 0) if role == "assistant" else 0,
                    "ot": (state.get("usage") or {}).get("output_tokens", 0) if role == "assistant" else 0,
                    "lat": latency_ms if role == "assistant" else None, "cid": cid})
    for i, c in enumerate(state.get("citations") or [], start=1):
        db.execute(text("""INSERT INTO rag.message_sources (tenant_id, message_id, user_id, ordinal, chunk_id, document_id,
                                  version_id, title, section_path, clause_ref, page_from, page_to, score, verified, quote_hash)
                           VALUES (:t, :m, :u, :o, :ch, :d, :v, :ti, :sp, :cr, :pf, :pt, :sc, :ver, :qh)"""),
                   {"t": ctx.tenant_id, "m": asst_msg, "u": ctx.user_id, "o": i, "ch": c["chunk_id"], "d": c["document_id"],
                    "v": c["version_id"], "ti": c["title"], "sp": c["section_path"], "cr": c["clause_ref"],
                    "pf": c["page_from"], "pt": c["page_to"], "sc": c["score"], "ver": c["verified"], "qh": c["quote_hash"]})
    db.execute(text("UPDATE rag.conversations SET message_count = message_count + 2 WHERE conversation_id = :c"),
               {"c": conversation_id})
    search_id = None
    if state.get("candidates") is not None and state.get("status") not in ("blocked",):
        search_id = log_search(db, ctx, query=state.get("rewritten_query") or message, mode="chat", filters=filters,
                               results=state.get("context") or [], latency_ms=latency_ms, rag_version=rag_version,
                               cache_hit=bool((state.get("diagnostics") or {}).get("cache_hit")),
                               conversation_id=conversation_id, message_id=asst_msg, candidates=state.get("candidates"))
    persist_guardrail_events(db, ctx, state.get("guardrail_events") or [], conversation_id, asst_msg, cid)
    usage = state.get("usage") or {}
    cost = 0.0
    if usage.get("model"):
        cost = record_model_usage(db, purpose="chat", provider=usage["provider"], model=usage["model"],
                                  input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0),
                                  latency_ms=usage.get("latency_ms"), user_id=ctx.user_id, department_id=ctx.department_id,
                                  status=usage.get("status", "success"))
        tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        # tokens are metered after the call; the request quota was reserved up front
        db.execute(text("UPDATE platform.tenant_usage SET ai_tokens_month = ai_tokens_month + :n WHERE tenant_id = :t"),
                   {"n": tokens, "t": ctx.tenant_id})
        tenant_audit(db, tenant_id=ctx.tenant_id, category="model_call", event_type="chat_completion",  # type: ignore[arg-type]
                     actor_type="service", actor_user_id=ctx.user_id, resource_type="message", resource_id=asst_msg,
                     detail={"provider": usage["provider"], "model": usage["model"], "input_tokens": usage.get("input_tokens"),
                             "output_tokens": usage.get("output_tokens"), "estimated_cost": cost, "status": usage.get("status")})
    tenant_audit(db, tenant_id=ctx.tenant_id, category="answer", event_type=f"answer_{state['status']}",  # type: ignore[arg-type]
                 actor_user_id=ctx.user_id, actor_account_id=ctx.account_id, resource_type="message", resource_id=asst_msg,
                 detail={"conversation_id": str(conversation_id), "evidence_strength": state.get("evidence_strength"),
                         "citations": [str(c["chunk_id"]) for c in state.get("citations") or []],
                         "content_hash": hashlib.sha256(state["answer"].encode()).hexdigest(), "prompt_version": PROMPT_VERSION,
                         "reason": state.get("reason"), "search_id": str(search_id) if search_id else None})
    db.execute(text("UPDATE platform.tenants SET last_activity_at = now() WHERE tenant_id = :t"), {"t": ctx.tenant_id})
    db.execute(text("UPDATE iam.users SET last_active_at = now() WHERE user_id = :u"), {"u": ctx.user_id})
    return {"conversation_id": conversation_id, "message_id": asst_msg, "user_message_id": user_msg,
            "answer": state["answer"], "status": state["status"], "evidence_strength": state.get("evidence_strength"),
            "citations": state.get("citations") or [], "warnings": state.get("warnings") or [],
            "rewritten_query": state.get("rewritten_query"), "disclaimer": DISCLAIMER,
            "ai_generated": True, "usage": {k: usage.get(k) for k in ("model", "input_tokens", "output_tokens")},
            "estimated_cost": cost, "latency_ms": latency_ms, "correlation_id": get_correlation_id(),
            "diagnostics": {k: v for k, v in (state.get("diagnostics") or {}).items() if k != "retrieval"}}


def ask(ctx: RequestContext, *, message: str, conversation_id: uuid.UUID | None, filters: SearchFilters) -> dict[str, Any]:
    import time

    enforce_rate_limit(f"{ctx.tenant_id}:{ctx.user_id}", kind="chat")
    t0 = time.perf_counter()
    with scoped_session(ctx.security("user")) as db:
        conversation_id, history, seq, tenant_name = _prepare(db, ctx, conversation_id, message, filters)
        rag = config_service.active_rag_config(db)
        ai = config_service.active_ai_config(db)
        state = RagWorkflow(db, ctx, rag, ai, tenant_name).run(message, history, filters)
        return _persist(db, ctx, conversation_id, seq, message, state, filters, rag.version,
                        int((time.perf_counter() - t0) * 1000))


def ask_stream(ctx: RequestContext, *, message: str, conversation_id: uuid.UUID | None,
               filters: SearchFilters) -> Iterator[str]:
    """Server-Sent Events: meta -> token* -> final -> done (AD-12).

    The rate limit is enforced HERE, before the generator is created, so that an
    exceeded limit is returned as a normal HTTP 429 instead of breaking a stream
    whose 200 headers were already sent."""
    enforce_rate_limit(f"{ctx.tenant_id}:{ctx.user_id}", kind="chat")
    return _stream_events(ctx, message=message, conversation_id=conversation_id, filters=filters)


def _stream_events(ctx: RequestContext, *, message: str, conversation_id: uuid.UUID | None,
                   filters: SearchFilters) -> Iterator[str]:
    import time

    q: queue.Queue[tuple[str, Any]] = queue.Queue()
    cid = get_correlation_id()

    def work() -> None:
        set_correlation_id(cid)
        t0 = time.perf_counter()
        try:
            with scoped_session(ctx.security("user")) as db:
                conv_id, history, seq, tenant_name = _prepare(db, ctx, conversation_id, message, filters)
                q.put(("meta", {"conversation_id": str(conv_id), "correlation_id": cid, "disclaimer": DISCLAIMER}))
                rag = config_service.active_rag_config(db)
                ai = config_service.active_ai_config(db)
                wf = RagWorkflow(db, ctx, rag, ai, tenant_name, token_sink=lambda t: q.put(("token", {"text": t})))
                state = wf.run(message, history, filters)
                result = _persist(db, ctx, conv_id, seq, message, state, filters, rag.version,
                                  int((time.perf_counter() - t0) * 1000))
            q.put(("final", result))
        except Exception as exc:  # surfaced to the client as an error event, never swallowed
            from app.core.errors import AppError

            code = exc.code if isinstance(exc, AppError) else "internal_error"
            msg = exc.message if isinstance(exc, AppError) else "An internal error occurred."
            q.put(("error", {"code": code, "message": msg, "correlation_id": cid}))
            if not isinstance(exc, AppError):
                import logging

                logging.getLogger("app.chat").exception("streaming chat failed")
        finally:
            q.put(("done", {}))

    threading.Thread(target=work, daemon=True, name="rag-stream").start()
    while True:
        event, data = q.get()
        yield f"event: {event}\ndata: {json.dumps(data, default=_json_default)}\n\n"
        if event == "done":
            break


def _json_default(o: Any) -> Any:
    if isinstance(o, (uuid.UUID, date)):
        return str(o)
    return str(o)


def submit_feedback(db: Session, ctx: RequestContext, *, message_id: uuid.UUID | None, rating: int | None, category: str,
                    comment: str | None, search_id: uuid.UUID | None = None) -> dict[str, Any]:
    if message_id and not db.execute(text("SELECT 1 FROM rag.conversation_messages WHERE message_id = :m AND role = 'assistant'"),
                                     {"m": message_id}).first():
        raise NotFound("Message not found")
    severity = {"unsafe": "high", "incorrect": "medium", "outdated": "medium", "access": "high"}.get(category, "low")
    fid = uuid.uuid4()
    db.execute(text("""INSERT INTO rag.feedback (tenant_id, feedback_id, user_id, message_id, search_id, rating, category,
                              comment, severity) VALUES (:t, :f, :u, :m, :s, :r, :c, :cm, :sev)"""),
               {"t": ctx.tenant_id, "f": fid, "u": ctx.user_id, "m": message_id, "s": search_id, "r": rating,
                "c": category, "cm": (comment or "")[:2000] or None, "sev": severity})
    tenant_audit(db, tenant_id=ctx.tenant_id, category="feedback", event_type="feedback_submitted",  # type: ignore[arg-type]
                 actor_user_id=ctx.user_id, resource_type="message", resource_id=message_id,
                 detail={"feedback_id": str(fid), "category": category, "rating": rating, "severity": severity})
    return {"feedback_id": fid, "status": "new", "severity": severity}
