"""RAG chat (FR-014, FR-187): JSON or Server-Sent Events streaming."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import tx
from app.dependencies.auth import require
from app.schemas.common import ERROR_RESPONSES
from app.schemas.rag import ChatRequest, FeedbackIn
from app.security.context import RequestContext
from app.services import chat_service

router = APIRouter(tags=["Chat"], responses=ERROR_RESPONSES)


@router.post("/chat", summary="Ask a question; answer with verified citations, evidence strength and warnings")
def chat(body: ChatRequest, ctx: RequestContext = Depends(require("chat.use"))):
    if body.stream:
        return StreamingResponse(chat_service.ask_stream(ctx, message=body.message, conversation_id=body.conversation_id,
                                                         filters=body.filters.to_filters()),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
    return chat_service.ask(ctx, message=body.message, conversation_id=body.conversation_id, filters=body.filters.to_filters())


@router.post("/chat/stream", summary="Streaming chat (SSE: meta, token*, final, done)")
def chat_stream(body: ChatRequest, ctx: RequestContext = Depends(require("chat.use"))) -> StreamingResponse:
    return StreamingResponse(chat_service.ask_stream(ctx, message=body.message, conversation_id=body.conversation_id,
                                                     filters=body.filters.to_filters()),
                             media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/feedback", status_code=201, summary="Rate an answer or report an issue")
def feedback(body: FeedbackIn, ctx: RequestContext = Depends(require("feedback.submit"))) -> dict:
    with tx(ctx, "user") as db:
        return chat_service.submit_feedback(db, ctx, message_id=body.message_id, rating=body.rating, category=body.category,
                                            comment=body.comment, search_id=body.search_id)
