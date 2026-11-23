"""Stateful RAG workflow on LangGraph (spec 6.8, 6.9, 8.5.2; extension 3).

Nodes: validate_input -> analyze_query -> rewrite_query -> authorize ->
hybrid_retrieval (vector + FTS + exact, RRF, dedupe, final authorisation) ->
rerank -> select_context -> check_sufficiency -> generate -> validate_citations
-> output_guardrails -> persist.

Conditional routes: blocked input, insufficient context (reformulate once, then
abstain), model failure (degraded search-only answer), human review, success.

Tenant and user identity travel in the typed state and the bound database
session (RLS context); the LLM only ever receives chunks that passed RLS, the
explicit ACL predicate and the final authorisation re-check.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
import time
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any, TypedDict

from dateutil import parser as dateparser
from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermissionDenied
from app.integrations.provider_registry import resolve_provider
from app.observability.metrics import ANSWERS, GENERATION_LATENCY, GUARDRAIL_DECISIONS
from app.observability.tracing import span
from app.rag.chunking.chunker import count_tokens
from app.rag.citations.validator import validate_citations
from app.rag.generation.llm import INSUFFICIENT, build_chat_model
from app.rag.generation.prompts import ANSWER_TEMPLATE, PROMPT_VERSION
from app.rag.guardrails.detectors import (
    RULES_VERSION,
    mask_pii,
    neutralise_links,
    regulated_decision_statements,
    scan_injection,
    scan_input,
)
from app.rag.ingestion.insurance_metadata import JURISDICTIONS, extract_identifiers
from app.rag.reranking.rerankers import build_reranker
from app.rag.retrieval.hybrid import HybridRetriever, RetrievedChunk, SearchFilters
from app.security.context import RequestContext
from app.services.config_service import AiConfig, RagConfig
from app.utils.clock import utc_today

log = logging.getLogger("app.rag")
HIGH_RISK = re.compile(r"\b(exclusion|excluded|coverage|covered|authority|limit|sum insured|deductible|excess|"
                       r"waiting period|pre-?authori[sz]ation|fraud)\b", re.I)
_FOLLOW_UP = re.compile(r"^(and|what about|how about|also|then|is it|does it|what if|same for|and for)\b|\b(it|that|this|they|those)\b", re.I)
_ASOF = re.compile(r"\b(?:as of|as at|on|effective|in force on)\s+(\d{1,2}[ /.-][A-Za-z0-9]{1,9}[ /.-]\d{2,4}|\d{4}-\d{2}-\d{2})", re.I)
SAFE_DECISION_MESSAGE = ("I can provide the approved guidance that applies, but I cannot approve, reject, accept, decline "
                         "or determine final coverage or premiums. Please refer the decision to the responsible "
                         "claims or underwriting authority.")
SAFE_BLOCK_MESSAGE = "This request cannot be processed because it conflicts with the platform's usage policy."


class RagState(TypedDict, total=False):
    question: str
    history: list[dict[str, str]]
    filters: SearchFilters
    as_of: date | None
    rewritten_query: str
    entities: dict[str, Any]
    status: str                      # running | answered | abstained | blocked | error | needs_review
    reason: str | None
    candidates: list[RetrievedChunk]
    context: list[RetrievedChunk]
    sources_text: str
    answer: str
    citations: list[dict[str, Any]]
    evidence_strength: str
    warnings: list[str]
    guardrail_events: list[dict[str, Any]]
    attempts: int
    usage: dict[str, Any]
    diagnostics: dict[str, Any]
    timings: dict[str, float]
    model_failed: bool


class RagWorkflow:
    def __init__(self, db: Session, ctx: RequestContext, rag: RagConfig, ai: AiConfig, tenant_name: str,
                 token_sink: Callable[[str], None] | None = None) -> None:
        self.db, self.ctx, self.rag, self.ai = db, ctx, rag, ai
        self.tenant_name = tenant_name
        self.retriever = HybridRetriever(db, ctx, rag, ai)
        self.token_sink = token_sink
        self.graph = self._build()

    # ---------------------------------------------------------------- graph
    def _build(self):
        g = StateGraph(RagState)
        for name in ("validate_input", "analyze_query", "rewrite_query", "authorize", "hybrid_retrieval", "rerank",
                     "select_context", "check_sufficiency", "reformulate", "generate", "degraded_answer",
                     "validate_citations", "output_guardrails", "abstain", "finalize"):
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "validate_input")
        g.add_conditional_edges("validate_input", lambda s: "finalize" if s.get("status") in ("blocked", "abstained") else "analyze_query")
        g.add_edge("analyze_query", "rewrite_query")
        g.add_edge("rewrite_query", "authorize")
        g.add_edge("authorize", "hybrid_retrieval")
        g.add_edge("hybrid_retrieval", "rerank")
        g.add_edge("rerank", "select_context")
        g.add_edge("select_context", "check_sufficiency")
        g.add_conditional_edges("check_sufficiency", self._route_sufficiency,
                                {"generate": "generate", "reformulate": "reformulate", "abstain": "abstain"})
        g.add_edge("reformulate", "hybrid_retrieval")
        g.add_conditional_edges("generate", lambda s: "degraded_answer" if s.get("model_failed") else
                                ("abstain" if s.get("status") == "abstained" else "validate_citations"))
        g.add_edge("degraded_answer", "finalize")
        g.add_edge("validate_citations", "output_guardrails")
        g.add_edge("output_guardrails", "finalize")
        g.add_edge("abstain", "finalize")
        g.add_edge("finalize", END)
        return g.compile()

    def run(self, question: str, history: list[dict[str, str]], filters: SearchFilters) -> RagState:
        state: RagState = {"question": question, "history": history, "filters": filters, "status": "running",
                           "warnings": [], "guardrail_events": [], "attempts": 0, "usage": {}, "diagnostics": {},
                           "timings": {}, "citations": [], "evidence_strength": "none", "model_failed": False}
        return self.graph.invoke(state)

    # ---------------------------------------------------------------- helpers
    def _event(self, s: RagState, stage: str, rule: str, decision: str, severity: str, category: str,
               detail: dict | None = None) -> None:
        s["guardrail_events"].append({"stage": stage, "rule_id": rule, "decision": decision, "severity": severity,
                                      "category": category, "detail": detail or {}})
        GUARDRAIL_DECISIONS.labels(stage, decision).inc()

    # ---------------------------------------------------------------- nodes
    def validate_input(self, s: RagState) -> RagState:
        q = (s["question"] or "").strip()
        if not q or len(q) > 4000:
            s.update(status="blocked", reason="invalid_input", answer="Please enter a question of up to 4000 characters.")
            return s
        res = scan_input(q)
        mode = (self.rag.guardrails or {}).get("prompt_injection", "block")
        for d in res.detections:
            if d.category == "prompt_injection" and d.severity == "high" and mode == "block":
                self._event(s, "input", d.rule_id, "block", "high", "prompt_injection")
                s.update(status="blocked", reason=f"prompt_injection:{d.rule_id}", answer=SAFE_BLOCK_MESSAGE)
                return s
            if d.category == "moderation":
                self._event(s, "input", d.rule_id, "block", "high", "moderation")
                s.update(status="blocked", reason="moderation", answer=SAFE_BLOCK_MESSAGE)
                return s
            if d.category == "knowledge_boundary" and (self.rag.guardrails or {}).get("regulated_decision", "block") == "block":
                self._event(s, "input", d.rule_id, "abstain", "medium", "knowledge_boundary")
                s.update(status="abstained", reason="regulated_decision", answer=SAFE_DECISION_MESSAGE)
                return s
            self._event(s, "input", d.rule_id, "alert", d.severity, d.category)
        return s

    def analyze_query(self, s: RagState) -> RagState:
        q = s["question"]
        entities: dict[str, Any] = {"identifiers": extract_identifiers(q)}
        low = q.lower()
        entities["jurisdictions"] = sorted({c for n, c in JURISDICTIONS.items() if re.search(r"\b" + re.escape(n) + r"\b", low)})
        m = _ASOF.search(q)
        as_of = s["filters"].as_of
        if m and not as_of:
            try:
                as_of = dateparser.parse(m.group(1), dayfirst=True).date()
                s["filters"].as_of = as_of
                s["warnings"].append(f"Answer reflects documents in force on {as_of.isoformat()}")
            except (ValueError, OverflowError):
                pass
        s["as_of"] = as_of
        s["entities"] = entities
        return s

    def rewrite_query(self, s: RagState) -> RagState:
        q = s["question"]
        rewritten = q
        hist = [h for h in s.get("history") or [] if h.get("role") == "user"]
        # Only real follow-ups borrow context from the previous question. Short self-contained questions
        # ("Hello", "Assignment") must not pick up unrelated history.
        if self.rag.query_rewriting and hist and _FOLLOW_UP.search(q):
            prev = hist[-1]["content"]
            keep = [w for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", prev) if w.lower() not in q.lower()][:8]
            rewritten = f"{q} (context: {' '.join(keep)})" if keep else q
        s["rewritten_query"] = rewritten
        return s

    def authorize(self, s: RagState) -> RagState:
        if self.ctx.tenant_id is None or self.ctx.user_id is None:
            raise PermissionDenied("tenant context required")
        if not ({"search.use", "chat.use"} & self.ctx.permissions):
            raise PermissionDenied("search or chat permission required")
        s["diagnostics"]["policy_scope_hash"] = self.ctx.permission_fingerprint()
        return s

    def hybrid_retrieval(self, s: RagState) -> RagState:
        t = time.perf_counter()
        out = self.retriever.search(s["rewritten_query"], s["filters"], mode="hybrid",
                                    top_k=max(self.rag.rerank_top_n, self.rag.final_top_k), rerank=False)
        s["candidates"] = out.results
        s["diagnostics"]["retrieval"] = out.diagnostics
        s["diagnostics"]["cache_hit"] = out.cache_hit
        s["timings"]["retrieval_ms"] = round((time.perf_counter() - t) * 1000, 1)
        return s

    def rerank(self, s: RagState) -> RagState:
        cands = s.get("candidates") or []
        if not self.rag.rerank_enabled or not cands:
            return s
        t = time.perf_counter()
        try:
            rr = build_reranker(resolve_provider(self.db, self.ai.reranker_provider), self.ai.reranker_model)
            scores = rr.score(s["rewritten_query"], [c.content for c in cands])
            for c, sc in zip(cands, scores, strict=True):
                c.rerank_score, c.score = float(sc), float(sc)
            cands.sort(key=lambda c: (-(c.rerank_score or 0), -c.rrf_score))
            s["diagnostics"]["reranker"] = rr.name
        except Exception as exc:
            s["diagnostics"]["reranker"] = "fallback:fused"
            s["warnings"].append("Reranking unavailable; results ordered by fused relevance")
            log.warning("reranker failed: %s", type(exc).__name__)
        s["timings"]["rerank_ms"] = round((time.perf_counter() - t) * 1000, 1)
        return s

    def select_context(self, s: RagState) -> RagState:
        budget = self.rag.max_context_tokens
        chosen: list[RetrievedChunk] = []
        used = 0
        blocks: list[str] = []
        seen_parents: set[uuid.UUID] = set()
        for c in (s.get("candidates") or [])[: self.rag.final_top_k * 2]:
            if c.score < self.rag.min_relevance:
                continue
            body = c.content
            if c.parent_chunk_id and c.parent_content and c.parent_chunk_id not in seen_parents \
                    and count_tokens(c.parent_content) <= budget // 2:
                body = c.parent_content  # parent-child: give the model the whole section (FR-074)
                seen_parents.add(c.parent_chunk_id)
            if c.injection_flag or scan_injection(body).flagged:
                # Indirect injection: drop instruction-like lines, keep the facts (FR-136)
                cleaned = "\n".join(l for l in body.split("\n") if not scan_injection(l).flagged)
                self._event(s, "evidence", "indirect_injection", "sanitise", "medium", "prompt_injection",
                            {"chunk_id": str(c.chunk_id)})
                body = cleaned
            if (self.rag.guardrails or {}).get("pii_context", "mask") == "mask" and c.sensitivity_tags:
                body, _ = mask_pii(body)
            t = count_tokens(body)
            if used + t > budget:
                continue
            used += t
            chosen.append(c)
            sid = f"S{len(chosen)}"
            meta = " ".join(f'{k}="{html.escape(str(v or ""), quote=True)}"' for k, v in (
                ("title", c.title), ("version", c.version_label), ("section", c.section_path), ("page", c.page_from),
                ("effective_from", c.effective_from), ("status", c.lifecycle_state)))
            # Escape markup in untrusted text so a passage can never close or forge a <source> block
            blocks.append(f'<source id="{sid}" {meta}>\n{html.escape(body, quote=False)}\n</source>')
            if c.low_confidence:
                s["warnings"].append(f"{sid} comes from a low-confidence OCR page; verify against the original")
            if c.lifecycle_state == "superseded":
                s["warnings"].append(f"{sid} is a superseded version used for the as-of date")
            if len(chosen) >= self.rag.final_top_k:
                break
        s["context"] = chosen
        s["sources_text"] = "\n".join(blocks)
        s["diagnostics"]["context_tokens"] = used
        s["diagnostics"]["omitted_candidates"] = max(0, len(s.get("candidates") or []) - len(chosen))
        juris = {j for c in chosen for j in (c.jurisdictions or [])}
        wanted = set(s.get("entities", {}).get("jurisdictions") or [])
        if wanted and juris and not (juris & wanted):
            s["warnings"].append("Sources come from a different jurisdiction than the one in your question")
        return s

    def _route_sufficiency(self, s: RagState) -> str:
        if s.get("context"):
            return "generate"
        return "reformulate" if s.get("attempts", 0) < 1 else "abstain"

    def check_sufficiency(self, s: RagState) -> RagState:
        ctx = s.get("context") or []
        if ctx:
            top = max(c.score for c in ctx)
            agree = len({c.document_id for c in ctx})
            s["evidence_strength"] = "high" if top >= 0.75 and len(ctx) >= 2 else ("medium" if top >= 0.45 else "low")
            s["diagnostics"]["distinct_documents"] = agree
        return s

    def reformulate(self, s: RagState) -> RagState:
        s["attempts"] = s.get("attempts", 0) + 1
        terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{2,}", s["rewritten_query"])
        s["rewritten_query"] = " OR ".join(dict.fromkeys(terms)) if terms else s["rewritten_query"]
        s["diagnostics"]["reformulated_query"] = s["rewritten_query"]
        return s

    def abstain(self, s: RagState) -> RagState:
        if s.get("status") != "abstained":
            s["status"] = "abstained"
            s["reason"] = s.get("reason") or "insufficient_evidence"
        if not s.get("answer") or s.get("answer") == INSUFFICIENT:
            searched = ", ".join(sorted({c.title for c in s.get("candidates") or []})[:3]) or "the collections you can access"
            s["answer"] = ("I could not find sufficient approved evidence to answer this question. I searched "
                           f"{searched}. Try rephrasing, narrowing the product or jurisdiction, or raise a knowledge "
                           "gap with the collection owner.")
        s["evidence_strength"] = "none"
        return s

    def _messages(self, s: RagState) -> list[BaseMessage]:
        history = " | ".join(f"{h['role']}: {h['content'][:200]}" for h in (s.get("history") or [])[-4:])
        return ANSWER_TEMPLATE.format_messages(tenant_name=self.tenant_name, as_of=(s.get("as_of") or utc_today()).isoformat(),
                                               history=history, sources=s["sources_text"], question=s["question"])

    def generate(self, s: RagState) -> RagState:
        with span("rag.generate", **{"llm.provider": self.ai.llm_provider, "llm.model": self.ai.chat_model,
                                     "rag.context_chunks": len(s.get("context") or []),
                                     "llm.streaming": self.token_sink is not None}) as sp:
            out = self._generate(s)
            usage = out.get("usage") or {}
            sp.set_attribute("llm.input_tokens", int(usage.get("input_tokens", 0)))
            sp.set_attribute("llm.output_tokens", int(usage.get("output_tokens", 0)))
            sp.set_attribute("llm.failed", bool(out.get("model_failed")))
            return out

    def _generate(self, s: RagState) -> RagState:
        msgs = self._messages(s)
        endpoint = resolve_provider(self.db, self.ai.llm_provider)
        model = build_chat_model(endpoint, self.ai.chat_model, self.ai.temperature, self.ai.max_output_tokens)
        t = time.perf_counter()
        try:
            if self.token_sink:
                parts, usage = [], {}
                guard = _SentenceGuard(self.token_sink)
                for chunk in model.stream(msgs):
                    if chunk.content:
                        parts.append(chunk.content)
                        guard.feed(chunk.content)
                    if getattr(chunk, "usage_metadata", None):
                        usage = dict(chunk.usage_metadata)
                guard.close()
                answer = "".join(parts)
                if not usage:
                    usage = {"input_tokens": sum(count_tokens(m.content) for m in msgs), "output_tokens": count_tokens(answer)}
            else:
                res = model.invoke(msgs)
                answer = res.content if isinstance(res.content, str) else str(res.content)
                usage = dict(res.usage_metadata or {}) or {"input_tokens": sum(count_tokens(m.content) for m in msgs),
                                                          "output_tokens": count_tokens(answer)}
        except Exception as exc:
            log.warning("generation failed (%s); degrading to search-only answer", type(exc).__name__)
            s["model_failed"] = True
            s["usage"] = {"provider": endpoint.code, "model": self.ai.chat_model, "input_tokens": 0, "output_tokens": 0,
                          "status": "error"}
            return s
        elapsed = time.perf_counter() - t
        GENERATION_LATENCY.labels(endpoint.provider_type).observe(elapsed)
        s["timings"]["generation_ms"] = round(elapsed * 1000, 1)
        s["usage"] = {"provider": endpoint.code, "model": self.ai.chat_model,
                      "input_tokens": int(usage.get("input_tokens", 0)), "output_tokens": int(usage.get("output_tokens", 0)),
                      "status": "success", "latency_ms": int(elapsed * 1000)}
        if answer.strip().startswith(INSUFFICIENT):
            s["status"] = "abstained"
            s["reason"] = "insufficient_evidence"
            s["answer"] = INSUFFICIENT
            return s
        s["answer"] = answer
        return s

    def degraded_answer(self, s: RagState) -> RagState:
        lines = [f"- {c.title} ({c.section_path or 'section n/a'}, page {c.page_from}) [S{i}]"
                 for i, c in enumerate(s.get("context") or [], start=1)]
        s["answer"] = ("Answer generation is temporarily unavailable. The most relevant approved sources are:\n"
                       + "\n".join(lines))
        s["status"] = "answered"
        s["warnings"].append("Degraded mode: generation unavailable, search results only")
        s["citations"] = self._citations(s, [f"S{i}" for i in range(1, len(lines) + 1)], set())
        return s

    def _citations(self, s: RagState, cited: list[str], unsupported: set[str]) -> list[dict[str, Any]]:
        out = []
        for i, c in enumerate(s.get("context") or [], start=1):
            sid = f"S{i}"
            if sid not in cited:
                continue
            out.append({"marker": sid, "chunk_id": c.chunk_id, "document_id": c.document_id, "version_id": c.version_id,
                        "title": c.title, "version_label": c.version_label, "section_path": c.section_path,
                        "clause_ref": c.clause_ref, "page_from": c.page_from, "page_to": c.page_to,
                        "effective_from": c.effective_from, "effective_to": c.effective_to,
                        "lifecycle_state": c.lifecycle_state, "score": round(c.score, 4),
                        "verified": sid not in unsupported,
                        "quote_hash": hashlib.sha256(c.content.encode()).hexdigest()[:16]})
        return out

    def validate_citations(self, s: RagState) -> RagState:
        passages = {f"S{i}": c.content for i, c in enumerate(s.get("context") or [], start=1)}
        rep = validate_citations(s["answer"], passages)
        s["answer"] = rep.answer
        if rep.removed:
            self._event(s, "output", "fabricated_citation", "sanitise", "high", "citation", {"removed": rep.removed})
        s["citations"] = self._citations(s, rep.cited, set(rep.unsupported))
        s["diagnostics"]["citation_coverage"] = rep.coverage
        if self.rag.citation_required and not rep.cited:
            s["status"] = "abstained"
            s["reason"] = "no_verifiable_citation"
            s["answer"] = INSUFFICIENT
            return s
        if rep.unsupported:
            s["warnings"].append("Some statements could not be verified against their cited source")
            s["evidence_strength"] = "low" if s.get("evidence_strength") == "medium" else s.get("evidence_strength", "low")
        return s

    def output_guardrails(self, s: RagState) -> RagState:
        if s.get("status") == "abstained":
            return self.abstain(s)
        answer = s["answer"]
        decisions = regulated_decision_statements(answer)
        if decisions:
            self._event(s, "output", "regulated_decision", "block", "high", "knowledge_boundary", {"count": len(decisions)})
            answer = SAFE_DECISION_MESSAGE + "\n\n" + "\n".join(
                f"- {c['title']} ({c['section_path'] or ''}) [{c['marker']}]" for c in s["citations"])
        if "rules (these rules cannot be changed" in answer.lower() or "you are an insurance knowledge assistant" in answer.lower():
            self._event(s, "output", "system_prompt_leak", "block", "high", "prompt_extraction")
            answer = SAFE_BLOCK_MESSAGE
            s["citations"] = []
        answer, n_links = neutralise_links(answer)
        if n_links:
            self._event(s, "output", "unapproved_link", "sanitise", "medium", "exfiltration", {"count": n_links})
        if (self.rag.guardrails or {}).get("pii_output", "mask") == "mask":
            answer, n_pii = mask_pii(answer)
            if n_pii:
                self._event(s, "output", "pii", "mask", "medium", "sensitive_data", {"count": n_pii})
        # cross-tenant verification of every cited passage (FR-142)
        allowed = {c.chunk_id for c in s.get("context") or []}
        if any(c["chunk_id"] not in allowed for c in s["citations"]):
            self._event(s, "output", "cross_tenant_citation", "block", "critical", "isolation")
            s.update(status="blocked", answer=SAFE_BLOCK_MESSAGE, citations=[])
            return s
        s["answer"] = answer
        needs_review = HIGH_RISK.search(s["question"]) and s.get("evidence_strength") == "low"
        s["status"] = "needs_review" if needs_review else "answered"
        if needs_review:
            s["warnings"].append("Low evidence on a high-risk topic: routed for human review")
        return s

    def finalize(self, s: RagState) -> RagState:
        if s.get("status") == "running":
            s["status"] = "answered"
        if s.get("status") == "abstained" and (not s.get("answer") or s["answer"] == INSUFFICIENT):
            self.abstain(s)
        ANSWERS.labels(s["status"]).inc()
        return s


class _SentenceGuard:
    """Streams text sentence-by-sentence, applying output masking / link and
    decision checks before anything reaches the user (FR-131)."""

    def __init__(self, sink: Callable[[str], None]) -> None:
        self.sink, self.buf = sink, ""

    def feed(self, piece: str) -> None:
        self.buf += piece
        while True:
            m = re.search(r"(?<=[.!?])\s+", self.buf)
            if not m:
                break
            sent, self.buf = self.buf[: m.end()], self.buf[m.end():]
            self._emit(sent)

    def _emit(self, sent: str) -> None:
        if sent.strip().startswith(INSUFFICIENT):
            return
        if regulated_decision_statements(sent):
            sent = "[statement withheld: regulated decision] "
        sent, _ = neutralise_links(sent)
        sent, _ = mask_pii(sent)
        self.sink(sent)

    def close(self) -> None:
        if self.buf:
            self._emit(self.buf)
            self.buf = ""


def persist_guardrail_events(db: Session, ctx: RequestContext, events: list[dict[str, Any]], conversation_id: uuid.UUID | None,
                             message_id: uuid.UUID | None, correlation_id: str) -> None:
    import json

    for e in events:
        db.execute(text("""INSERT INTO ai.guardrail_events (tenant_id, user_id, conversation_id, message_id, stage, rule_id,
                                  rule_version, decision, severity, category, correlation_id, detail)
                           VALUES (:t, :u, :c, :m, :st, :r, :rv, :d, :sev, :cat, :cid, CAST(:det AS jsonb))"""),
                   {"t": ctx.tenant_id, "u": ctx.user_id, "c": conversation_id, "m": message_id, "st": e["stage"],
                    "r": e["rule_id"], "rv": RULES_VERSION, "d": e["decision"], "sev": e["severity"],
                    "cat": e["category"], "cid": correlation_id, "det": json.dumps(e.get("detail") or {}, default=str)})


__all__ = ["RagWorkflow", "RagState", "persist_guardrail_events", "PROMPT_VERSION"]
