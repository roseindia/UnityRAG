"""Rerankers (FR-089, NFR-008, NFR-026).

* LexicalOverlapReranker - local BM25-style scorer over normalised insurance
  terms with phrase and identifier bonuses (no external dependency).
* HttpCrossEncoderReranker - cross-encoder served by Hugging Face TEI
  (/rerank) or any Cohere/Jina-compatible endpoint.
Callers fall back to the fused ranking if a reranker fails.
"""
from __future__ import annotations

import math
import re
from typing import Protocol

import httpx

from app.integrations.provider_registry import ProviderEndpoint
from app.rag.embeddings.providers import normalise_terms


class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class LexicalOverlapReranker:
    name = "lexical-overlap-v1"

    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b

    def score(self, query: str, passages: list[str]) -> list[float]:
        q_terms = list(dict.fromkeys(normalise_terms(query)))
        if not q_terms or not passages:
            return [0.0] * len(passages)
        docs = [normalise_terms(p) for p in passages]
        avg = sum(len(d) for d in docs) / len(docs) or 1.0
        n = len(docs)
        df = {t: sum(1 for d in docs if t in d) for t in q_terms}
        q_low = query.lower()
        phrases = [m for m in re.findall(r"\"([^\"]+)\"", q_low)]
        ids = re.findall(r"\b[A-Z]{2,6}[-/ ]?\d{2,}[A-Z0-9/-]*\b|\b\d+(?:\.\d+)+\b", query)
        out = []
        for passage, d in zip(passages, docs, strict=True):
            tf: dict[str, int] = {}
            for t in d:
                tf[t] = tf.get(t, 0) + 1
            s = 0.0
            for t in q_terms:
                if t not in tf:
                    continue
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                f = tf[t]
                s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / avg))
            coverage = sum(1 for t in q_terms if t in tf) / len(q_terms)
            low = passage.lower()
            s += 1.5 * sum(1 for ph in phrases if ph in low)
            s += 2.0 * sum(1 for i in ids if i.lower() in low)
            out.append(round(1 / (1 + math.exp(-(s * 0.5 + 3 * coverage - 3))), 6))
        return out


class HttpCrossEncoderReranker:
    def __init__(self, endpoint: ProviderEndpoint, model: str, transport: httpx.BaseTransport | None = None,
                 timeout: float = 10.0) -> None:
        self.endpoint, self.name = endpoint, model
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def score(self, query: str, passages: list[str]) -> list[float]:
        headers = {"Authorization": f"Bearer {self.endpoint.api_key}"} if self.endpoint.api_key else {}
        r = self._client.post(f"{(self.endpoint.base_url or '').rstrip('/')}/rerank",
                              json={"query": query, "texts": passages, "documents": passages, "model": self.name,
                                    "raw_scores": False}, headers=headers)
        r.raise_for_status()
        data = r.json()
        items = data.get("results", data) if isinstance(data, dict) else data
        scores = [0.0] * len(passages)
        for item in items:
            idx = item.get("index")
            val = item.get("score", item.get("relevance_score", 0.0))
            if idx is not None and 0 <= idx < len(passages):
                scores[idx] = float(val)
        return scores


def build_reranker(endpoint: ProviderEndpoint, model: str) -> Reranker:
    if endpoint.provider_type == "local":
        return LexicalOverlapReranker()
    return HttpCrossEncoderReranker(endpoint, model)
