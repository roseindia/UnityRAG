"""Conversation management (FR-019, FR-188); owner-scoped by RLS."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import tx
from app.dependencies.auth import require
from app.schemas.common import ERROR_RESPONSES, Message, Page, PageParams
from app.schemas.rag import ConversationCreate, ConversationRename
from app.security.context import RequestContext
from app.services import chat_service

router = APIRouter(prefix="/conversations", tags=["Conversations"], responses=ERROR_RESPONSES)
USE = "chat.use"


@router.post("", status_code=201)
def create(body: ConversationCreate, ctx: RequestContext = Depends(require(USE))) -> dict:
    with tx(ctx, "user") as db:
        return chat_service.create_conversation(db, ctx, body.title, body.context)


@router.get("", response_model=Page[dict])
def list_(q: str | None = None, page: PageParams = Depends(), ctx: RequestContext = Depends(require(USE))) -> Page[dict]:
    with tx(ctx, "user") as db:
        items, total = chat_service.list_conversations(db, q, page.limit, page.offset)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/{conversation_id}")
def get(conversation_id: uuid.UUID, ctx: RequestContext = Depends(require(USE))) -> dict:
    with tx(ctx, "user") as db:
        return chat_service.get_conversation(db, conversation_id) | {"messages": chat_service.messages(db, conversation_id)}


@router.put("/{conversation_id}")
def rename(conversation_id: uuid.UUID, body: ConversationRename, ctx: RequestContext = Depends(require(USE))) -> dict:
    with tx(ctx, "user") as db:
        return chat_service.rename(db, conversation_id, body.title)


@router.delete("/{conversation_id}", response_model=Message)
def delete(conversation_id: uuid.UUID, ctx: RequestContext = Depends(require(USE))) -> Message:
    with tx(ctx, "user") as db:
        chat_service.delete(db, ctx, conversation_id)
    return Message(message="Conversation deleted")


@router.get("/{conversation_id}/export")
def export(conversation_id: uuid.UUID, ctx: RequestContext = Depends(require(USE))) -> dict:
    with tx(ctx, "user") as db:
        return chat_service.export(db, ctx, conversation_id)


@router.get("/{conversation_id}/messages/{message_id}/sources",
            summary="Citations of an answer, re-verified against the caller's current access")
def sources(conversation_id: uuid.UUID, message_id: uuid.UUID, ctx: RequestContext = Depends(require(USE))) -> list[dict]:
    with tx(ctx, "user") as db:
        chat_service.get_conversation(db, conversation_id)
        return chat_service.verified_sources(db, ctx, message_id)
