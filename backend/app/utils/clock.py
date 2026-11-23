"""UTC clock helpers: business dates are always UTC dates (connections also run with timezone=UTC)."""
from __future__ import annotations

from datetime import UTC, date, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_today() -> date:
    return utc_now().date()
