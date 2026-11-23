"""Fixed-window rate limiting per tenant + identity (FR-197, NFR-041)."""
from __future__ import annotations

import logging
import time

from app.core.config import get_settings
from app.core.errors import RateLimited
from app.utils.cache import get_cache

log = logging.getLogger("app.ratelimit")


def enforce_rate_limit(identity: str, kind: str = "api") -> None:
    s = get_settings()
    limit = s.chat_rate_limit_per_minute if kind == "chat" else s.rate_limit_per_minute
    window = int(time.time() // 60)
    try:
        count = get_cache().incr(f"rl:{kind}:{identity}:{window}", ttl=61)
    except Exception:  # cache outage must not take the API down; log loudly
        log.warning("rate limiter unavailable; request allowed", extra={"kind": kind})
        return
    if count > limit:
        raise RateLimited(f"Rate limit exceeded ({limit} requests per minute)")
