"""Retrieval and answer metrics (FR-201..FR-206, NFR-059..NFR-067, spec 14.2-14.4)."""
from __future__ import annotations

import math
from collections.abc import Sequence


def recall_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 1.0
    return len(set(retrieved[:k]) & relevant) / len(relevant)


def precision_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    top = list(retrieved[:k])
    if not top:
        return 0.0
    return sum(1 for r in top if r in relevant) / len(top)


def reciprocal_rank(retrieved: Sequence[str], relevant: set[str]) -> float:
    for i, r in enumerate(retrieved, start=1):
        if r in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    dcg, seen = 0.0, set()
    for i, r in enumerate(retrieved[:k], start=1):
        if r in relevant and r not in seen:
            dcg += 1.0 / math.log2(i + 1)
            seen.add(r)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def hit_rate(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    return 1.0 if set(retrieved[:k]) & relevant else 0.0


def dedupe_preserving(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(items))


DEFAULT_GATES = {"recall_at_k": 0.90, "mrr": 0.60, "ndcg_at_k": 0.80, "citation_coverage": 0.90,
                 "abstention_accuracy": 0.90, "faithfulness": 0.95}
