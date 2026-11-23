"""Shared API schemas: pagination envelope, errors, generic messages (FR-195, extension 9)."""
from __future__ import annotations

from datetime import date
from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    correlation_id: str
    details: list[dict[str, Any]] = []


class ErrorResponse(BaseModel):
    error: ErrorBody


class Message(BaseModel):
    message: str


class PageParams:
    def __init__(self, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> None:
        self.limit, self.offset = limit, offset


class DateRange:
    def __init__(self, start: date | None = Query(None, description="inclusive start date (default: 30 days ago)"),
                 end: date | None = Query(None, description="inclusive end date (default: today)")) -> None:
        self.start, self.end = start, end


class Reason(ApiModel):
    reason: str = Field(min_length=10, max_length=1000)


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Authentication required or invalid"},
    403: {"model": ErrorResponse, "description": "Permission denied / tenant unavailable"},
    404: {"model": ErrorResponse, "description": "Not found (or not visible to the caller)"},
    409: {"model": ErrorResponse, "description": "Conflict"},
    422: {"model": ErrorResponse, "description": "Validation failed"},
    429: {"model": ErrorResponse, "description": "Rate limit or quota exceeded"},
}
