"""Structured JSON logging with correlation IDs and redaction (FR-232, NFR-071)."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

from app.core.context import get_correlation_id, get_log_tenant

_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(password|secret|api[_-]?key|authorization|token)(\"?\s*[:=]\s*\"?)([^\s\",}]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[NUMBER]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]+"), "Bearer [REDACTED]"),
]


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def _trace_id() -> str | None:
    from opentelemetry import trace

    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


class JsonFormatter(logging.Formatter):
    _std = set(vars(logging.LogRecord("x", 0, "x", 0, "x", None, None)).keys()) | {"message", "asctime"}

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "correlation_id": get_correlation_id(),
            "tenant_id": get_log_tenant(),
            "trace_id": _trace_id(),
            "message": redact(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in self._std and not key.startswith("_"):
                payload[key] = redact(str(value)) if isinstance(value, str) else value
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", service: str = "api") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "urllib3", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
