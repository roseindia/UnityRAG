"""Prometheus metrics (golden signals + RAG specific, FR-231, FR-236, NFR-072)."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("http_request_duration_seconds", "HTTP latency", ["method", "route"],
                         buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30))
RETRIEVAL_LATENCY = Histogram("rag_retrieval_seconds", "Hybrid retrieval latency", ["branch"],
                              buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.8, 1.5, 3))
GENERATION_LATENCY = Histogram("rag_generation_seconds", "Answer generation latency", ["provider"],
                               buckets=(0.1, 0.5, 1, 2, 4, 8, 15, 25, 60))
ANSWERS = Counter("rag_answers_total", "Answers by status", ["status"])
GUARDRAIL_DECISIONS = Counter("rag_guardrail_decisions_total", "Guardrail decisions", ["stage", "decision"])
EMPTY_RETRIEVALS = Counter("rag_empty_retrievals_total", "Retrievals with no authorised result")
TOKENS = Counter("rag_model_tokens_total", "Model tokens", ["purpose", "direction"])
INGESTION_JOBS = Counter("ingestion_jobs_total", "Ingestion job outcomes", ["status"])
INGESTION_STAGE_LATENCY = Histogram("ingestion_stage_seconds", "Ingestion stage latency", ["stage"],
                                    buckets=(0.01, 0.05, 0.1, 0.5, 1, 5, 15, 60, 300))
CACHE_HITS = Counter("rag_cache_total", "Retrieval cache lookups", ["result"])
