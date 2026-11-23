"""Model usage metering and cost estimation (FR-177, FR-220, FR-221, NFR-078, NFR-098).

Costs are ESTIMATES computed from the catalogue price per 1k tokens; the API
labels them as such.  When provider billing data is integrated it replaces
the estimate for the affected period.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.context import get_correlation_id
from app.integrations.provider_registry import model_pricing
from app.observability.metrics import TOKENS


def estimate_cost(db: Session, provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    cin, cout = model_pricing(db, provider, model)
    return round(input_tokens / 1000 * cin + output_tokens / 1000 * cout, 6)


def record_model_usage(db: Session, *, purpose: str, provider: str, model: str, input_tokens: int,
                       output_tokens: int, latency_ms: int | None, user_id: uuid.UUID | None,
                       department_id: uuid.UUID | None = None, status: str = "success") -> float:
    cost = estimate_cost(db, provider, model, input_tokens, output_tokens)
    db.execute(text("""INSERT INTO ai.tenant_model_usage (tenant_id, user_id, department_id, purpose, provider, model,
                              input_tokens, output_tokens, latency_ms, estimated_cost, status, correlation_id)
                       VALUES (app.current_tenant_id(), :u, :d, :p, :prov, :m, :i, :o, :l, :c, :s, :cid)"""),
               {"u": user_id, "d": department_id, "p": purpose, "prov": provider, "m": model, "i": input_tokens,
                "o": output_tokens, "l": latency_ms, "c": cost, "s": status, "cid": get_correlation_id()})
    TOKENS.labels(purpose, "in").inc(input_tokens)
    TOKENS.labels(purpose, "out").inc(output_tokens)
    return cost
