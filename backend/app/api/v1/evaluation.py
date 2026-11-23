"""RAG evaluation API (FR-192, FR-200..FR-215)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import admin, tx
from app.schemas.admin import DatasetCreate, EvaluationRunRequest, QuestionIn
from app.schemas.common import ERROR_RESPONSES
from app.security.context import RequestContext
from app.services import evaluation_service

router = APIRouter(prefix="/admin/evaluation", tags=["Tenant Admin - RAG Evaluation"], responses=ERROR_RESPONSES)


@router.get("/datasets")
def datasets(ctx: RequestContext = Depends(admin("evaluation.manage", write=False))) -> list[dict]:
    with tx(ctx, "tenant_admin") as db:
        return evaluation_service.list_datasets(db)


@router.post("/datasets", status_code=201)
def create_dataset(body: DatasetCreate, ctx: RequestContext = Depends(admin("evaluation.manage"))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return evaluation_service.create_dataset(db, ctx.security("tenant_admin"), body.name, body.purpose, body.description)


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: uuid.UUID, ctx: RequestContext = Depends(admin("evaluation.manage", write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return evaluation_service.get_dataset(db, dataset_id)


@router.post("/datasets/{dataset_id}/questions", status_code=201)
def add_questions(dataset_id: uuid.UUID, body: list[QuestionIn], ctx: RequestContext = Depends(admin("evaluation.manage"))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        n = evaluation_service.add_questions(db, ctx.security("tenant_admin"), dataset_id, [q.model_dump() for q in body])
    return {"added": n}


@router.post("/datasets/{dataset_id}/approve", summary="Approve a dataset (approver must differ from author)")
def approve(dataset_id: uuid.UUID, ctx: RequestContext = Depends(admin("evaluation.manage"))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return evaluation_service.approve_dataset(db, ctx.security("tenant_admin"), dataset_id)


@router.post("/datasets/{dataset_id}/runs", status_code=201,
             summary="Run an evaluation under the caller's own (user-level) permissions; returns metrics and gate outcome")
def run(dataset_id: uuid.UUID, body: EvaluationRunRequest, ctx: RequestContext = Depends(admin("evaluation.run"))) -> dict:
    return evaluation_service.run_evaluation(ctx, dataset_id, mode=body.mode, k=body.k, gates=body.gates)


@router.get("/runs")
def runs(dataset_id: uuid.UUID | None = None, ctx: RequestContext = Depends(admin("evaluation.run", write=False))) -> list[dict]:
    with tx(ctx, "tenant_admin") as db:
        return evaluation_service.list_runs(db, dataset_id)


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, ctx: RequestContext = Depends(admin("evaluation.run", write=False))) -> dict:
    with tx(ctx, "tenant_admin") as db:
        return evaluation_service.get_run(db, run_id)
