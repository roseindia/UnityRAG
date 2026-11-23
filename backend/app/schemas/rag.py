"""Search and chat schemas (FR-186, FR-187)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import Field

from app.rag.retrieval.hybrid import SearchFilters
from app.schemas.common import ApiModel


class FilterIn(ApiModel):
    collection_ids: list[uuid.UUID] = []
    document_types: list[str] = []
    lines_of_business: list[str] = []
    jurisdictions: list[str] = []
    products: list[str] = []
    document_ids: list[uuid.UUID] = []
    as_of: date | None = Field(None, description="effective-date-aware retrieval (as-of date)")
    include_superseded: bool = False

    def to_filters(self) -> SearchFilters:
        return SearchFilters(**self.model_dump())


class SearchRequest(ApiModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["hybrid", "vector", "fulltext"] = "hybrid"
    top_k: int | None = Field(None, ge=1, le=50)
    rerank: bool | None = None
    filters: FilterIn = FilterIn()


class ChatRequest(ApiModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    filters: FilterIn = FilterIn()
    stream: bool = False


class ConversationCreate(ApiModel):
    title: str | None = Field(None, max_length=200)
    context: dict | None = None


class ConversationRename(ApiModel):
    title: str = Field(min_length=1, max_length=200)


class FeedbackIn(ApiModel):
    message_id: uuid.UUID | None = None
    search_id: uuid.UUID | None = None
    rating: Literal[-1, 1] | None = None
    category: Literal["rating", "incorrect", "outdated", "unsafe", "missing_source", "wrong_version", "access",
                      "document_error", "other"] = "rating"
    comment: str | None = Field(None, max_length=2000)
