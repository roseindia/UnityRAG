import uuid

import pytest

from app.rag.evaluation.metrics import hit_rate, ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank
from app.rag.hybrid_search.rrf import BranchHit, reciprocal_rank_fusion

A, B, C, D = (uuid.uuid4() for _ in range(4))


def test_rrf_formula_and_weights():
    fused = reciprocal_rank_fusion({"vector": [BranchHit(A, .9), BranchHit(B, .8)], "fulltext": [BranchHit(B, 3), BranchHit(C, 1)]},
                                   {"vector": 1.0, "fulltext": 2.0}, k=60)
    scores = {f.chunk_id: f.rrf_score for f in fused}
    assert scores[B] == pytest.approx(1 / 62 + 2 / 61)
    assert scores[A] == pytest.approx(1 / 61) and scores[C] == pytest.approx(2 / 62)
    assert fused[0].chunk_id == B and fused[0].branch_ranks == {"vector": 2, "fulltext": 1}


def test_rrf_dedupes_within_branch_and_ignores_zero_weight():
    fused = reciprocal_rank_fusion({"vector": [BranchHit(A, 1), BranchHit(A, .5), BranchHit(B, .4)], "exact": [BranchHit(D, 1)]},
                                   {"exact": 0}, k=10)
    assert [f.chunk_id for f in fused] == [A, B]
    assert fused[1].branch_ranks["vector"] == 2
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({}, k=0)


def test_retrieval_metrics():
    ret, rel = ["a", "x", "b", "y"], {"a", "b"}
    assert recall_at_k(ret, rel, 3) == 1.0 and recall_at_k(ret, rel, 1) == 0.5
    assert precision_at_k(ret, rel, 2) == 0.5
    assert reciprocal_rank(["x", "a"], rel) == 0.5
    assert 0 < ndcg_at_k(ret, rel, 4) < 1 and ndcg_at_k(["a", "b"], rel, 2) == pytest.approx(1.0)
    assert hit_rate(["x"], rel, 1) == 0.0
