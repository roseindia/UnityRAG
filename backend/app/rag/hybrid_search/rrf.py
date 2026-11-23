"""Reciprocal Rank Fusion (FR-088): RRF_score = sum_i weight_i / (k + rank_i).

Only already-authorised branch results are fused (the branches run under the
caller's RLS context with explicit ACL / tenant predicates), so fusion can
never combine unauthorised results (extension 3).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class BranchHit:
    chunk_id: uuid.UUID
    score: float


@dataclass
class FusedHit:
    chunk_id: uuid.UUID
    rrf_score: float
    branch_ranks: dict[str, int] = field(default_factory=dict)
    branch_scores: dict[str, float] = field(default_factory=dict)


def reciprocal_rank_fusion(branches: dict[str, list[BranchHit]], weights: dict[str, float] | None = None,
                           k: int = 60) -> list[FusedHit]:
    if k <= 0:
        raise ValueError("RRF constant k must be positive")
    weights = weights or {}
    fused: dict[uuid.UUID, FusedHit] = {}
    for branch, hits in branches.items():
        w = weights.get(branch, 1.0)
        if w <= 0:
            continue
        seen: set[uuid.UUID] = set()
        rank = 0
        for hit in hits:
            if hit.chunk_id in seen:  # dedupe inside a branch: keep best rank
                continue
            seen.add(hit.chunk_id)
            rank += 1
            f = fused.setdefault(hit.chunk_id, FusedHit(hit.chunk_id, 0.0))
            f.rrf_score += w / (k + rank)
            f.branch_ranks[branch] = rank
            f.branch_scores[branch] = round(float(hit.score), 6)
    return sorted(fused.values(), key=lambda f: (-f.rrf_score, min(f.branch_ranks.values())))
