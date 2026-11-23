"""OpenTelemetry tracing, Prometheus metrics and structured-log correlation (FR-231, NFR-072, NFR-073)."""
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_EXPORTER = InMemorySpanExporter()


def _provider() -> InMemorySpanExporter:
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))
        trace.set_tracer_provider(provider)
    _EXPORTER.clear()
    return _EXPORTER


def test_request_retrieval_and_generation_spans_without_content(client, tenants):
    exporter = _provider()
    a = tenants["A"]
    parent_trace = "4bf92f3577b34da6a3ce929d0e0e4736"
    question = "What does the motor policy cover for flood damage?"
    r = client.post("/api/v1/chat", headers={**a["analyst"], "traceparent": f"00-{parent_trace}-00f067aa0ba902b7-01"},
                    json={"message": question})
    assert r.status_code == 200
    assert r.headers["X-Trace-ID"] == parent_trace  # W3C context propagated from the caller
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert "POST /api/v1/chat" in spans and spans["POST /api/v1/chat"].kind == trace.SpanKind.SERVER
    for name in ("rag.retrieve", "rag.retrieve.vector", "rag.retrieve.fulltext", "rag.generate"):
        assert name in spans, name
        assert format(spans[name].context.trace_id, "032x") == parent_trace
    assert spans["rag.generate"].attributes["llm.output_tokens"] > 0
    assert spans["rag.retrieve"].attributes["tenant.id"] == a["tenant"]["tenant_id"]
    # no query text / content in any span attribute
    for s in exporter.get_finished_spans():
        for v in (s.attributes or {}).values():
            assert "flood" not in str(v).lower()


def test_metrics_endpoint_exposes_rag_series(client, tenants):
    client.post("/api/v1/search", headers=tenants["A"]["analyst"], json={"query": "excess"})
    body = client.get("/metrics").text
    for series in ("http_requests_total", "rag_retrieval_seconds_bucket", "rag_cache_total"):
        assert series in body
