"""Search API: vector, full-text and hybrid search without generation (FR-186)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies.auth import require
from app.schemas.common import ERROR_RESPONSES, Page, PageParams
from app.schemas.rag import SearchRequest
from app.security.context import RequestContext
from app.services import search_service

router = APIRouter(prefix="/search", tags=["Search"], responses=ERROR_RESPONSES)


@router.post("", summary="Hybrid / vector / full-text search over authorised content")
def search(body: SearchRequest, ctx: RequestContext = Depends(require("search.use"))) -> dict:
    return search_service.search(ctx, query=body.query, filters=body.filters.to_filters(), mode=body.mode,
                                 top_k=body.top_k, rerank=body.rerank)


@router.post("/vector", summary="Semantic (pgvector) search only")
def vector(body: SearchRequest, ctx: RequestContext = Depends(require("search.use"))) -> dict:
    return search_service.search(ctx, query=body.query, filters=body.filters.to_filters(), mode="vector", top_k=body.top_k,
                                 rerank=body.rerank)


@router.post("/fulltext", summary="PostgreSQL full-text (+ exact identifier) search only")
def fulltext(body: SearchRequest, ctx: RequestContext = Depends(require("search.use"))) -> dict:
    return search_service.search(ctx, query=body.query, filters=body.filters.to_filters(), mode="fulltext",
                                 top_k=body.top_k, rerank=body.rerank)


@router.get("/facets", summary="Filter facets with counts, limited to documents the caller may see")
def facets(ctx: RequestContext = Depends(require("search.use"))) -> dict:
    return search_service.facets(ctx)


@router.get("/history", response_model=Page[dict], summary="The caller's search history")
def history(page: PageParams = Depends(), ctx: RequestContext = Depends(require("search.use"))) -> Page[dict]:
    items, total = search_service.history(ctx, page.limit, page.offset)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)
