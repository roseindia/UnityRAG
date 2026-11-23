"""OpenTelemetry tracing (FR-231, NFR-073).

When OTEL_ENABLED=true the process installs an SDK TracerProvider that exports
spans over OTLP/HTTP.  The exporter reads the standard OpenTelemetry variables
(OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_HEADERS, ...), and the sampler
can be set with OTEL_TRACES_SAMPLER / OTEL_TRACES_SAMPLER_ARG.  When disabled the
OpenTelemetry API's no-op tracer is used, so instrumentation costs nothing.

Span attributes carry identifiers, counts and timings only - never query text,
document content, prompts or answers (FR-232 / "do not log confidential content").
"""
from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import propagate, trace

from app.core.config import get_settings

log = logging.getLogger("app.tracing")
_configured = False

tracer = trace.get_tracer("unityrag")


def configure_tracing(service: str) -> bool:
    """Install the SDK provider once per process.  Returns True when exporting."""
    global _configured
    s = get_settings()
    if _configured or not s.otel_enabled:
        return _configured
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": f"{s.otel_service_name}-{service}",
                                                        "deployment.environment": s.environment}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True
    log.info("OpenTelemetry tracing enabled", extra={"service": service})
    return True


def extract_context(headers: Mapping[str, str]) -> Any:
    """W3C trace-context (traceparent / tracestate) from incoming request headers."""
    return propagate.extract(dict(headers))


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """Child span with safe scalar attributes (None values are dropped)."""
    with tracer.start_as_current_span(name) as sp:
        for k, v in attributes.items():
            if v is not None:
                sp.set_attribute(k, v if isinstance(v, (bool, int, float, str)) else str(v))
        yield sp


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None
