"""Embedding providers behind the LangChain `Embeddings` interface (FR-042, FR-079, FR-080, NFR-081).

* LocalHashingEmbeddings - offline, deterministic signed feature-hashing of
  normalised word uni/bi-grams and character n-grams with an insurance synonym
  map.  Intended for development, air-gapped evaluation and tests; it captures
  lexical / morphological similarity, not deep semantics.
* OpenAICompatibleEmbeddings - OpenAI, Azure OpenAI, vLLM / LM Studio and any
  OpenAI-compatible endpoint.
* OllamaEmbeddings - local Ollama (/api/embed).
* HuggingFaceTEIEmbeddings - Hugging Face text-embeddings-inference (/embed).
Every provider validates the returned dimension against the configured one
before vectors are persisted (dimension compatibility gate).
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from itertools import pairwise
from typing import Any

import httpx
from langchain_core.embeddings import Embeddings
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.integrations.provider_registry import ProviderEndpoint

SYNONYMS = {
    "car": "vehicle", "auto": "vehicle", "automobile": "vehicle", "motorcar": "vehicle",
    "excess": "deductible", "copay": "copayment", "co-payment": "copayment",
    "hospitalisation": "hospitalization", "hospitalised": "hospitalized", "authorisation": "authorization",
    "preauthorisation": "preauthorization", "pre-authorisation": "preauthorization", "pre-authorization": "preauthorization",
    "flooding": "flood", "inundation": "flood", "theft": "burglary", "stolen": "burglary",
    "insurer": "company", "policyholder": "insured", "assured": "insured", "beneficiary": "nominee",
    "premium": "premium", "lapse": "lapsed", "revive": "revival", "reinstatement": "revival",
    "cancel": "cancellation", "terminate": "cancellation", "cover": "coverage", "covered": "coverage",
    "exclude": "exclusion", "excluded": "exclusion", "exclusions": "exclusion",
}
_WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_STOP = set("a an the of to in on for and or is are was were be been by with as at from that this these those it its "
            "which who whom what when where how if then than any all such shall will may can not no do does".split())


def _stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "edly", "ed", "ies", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def normalise_terms(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text.lower()):
        w = SYNONYMS.get(w, w)
        if w in _STOP:
            continue
        out.append(_stem(w))
    return out


class LocalHashingEmbeddings(Embeddings):
    provider = "local"

    def __init__(self, model_name: str = "hashing-v1", dimensions: int = 384) -> None:
        self.model_name = model_name
        self.dimensions = dimensions

    def _features(self, text: str) -> dict[str, float]:
        terms = normalise_terms(text)
        feats: dict[str, float] = {}
        for t in terms:
            feats["w:" + t] = feats.get("w:" + t, 0.0) + 1.0
            if len(t) >= 5:
                for i in range(len(t) - 3):
                    g = "c:" + t[i:i + 4]
                    feats[g] = feats.get(g, 0.0) + 0.25
        for a, b in pairwise(terms):
            feats["b:" + a + "_" + b] = feats.get("b:" + a + "_" + b, 0.0) + 0.7
        return feats

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        for feat, weight in self._features(text).items():
            h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dimensions
            sign = 1.0 if h[4] & 1 else -1.0
            vec[idx] += sign * (1.0 + math.log(weight)) if weight >= 1 else sign * weight
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def _retryable(exc: BaseException) -> bool:
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException)) or (
        isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (408, 409, 429, 500, 502, 503, 504))


class _HttpEmbeddings(Embeddings):
    batch_size = 64

    def __init__(self, endpoint: ProviderEndpoint, model_name: str, dimensions: int,
                 transport: httpx.BaseTransport | None = None, timeout: float = 30.0) -> None:
        self.endpoint = endpoint
        self.provider = endpoint.code
        self.model_name = model_name
        self.dimensions = dimensions
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def _request(self, batch: list[str]) -> list[list[float]]:  # pragma: no cover - abstract
        raise NotImplementedError

    @retry(retry=retry_if_exception(_retryable), stop=stop_after_attempt(5),
           wait=wait_exponential_jitter(initial=1, max=30), reraise=True)
    def _call(self, batch: list[str]) -> list[list[float]]:
        vectors = self._request(batch)
        for v in vectors:
            if len(v) != self.dimensions:
                raise ValueError(f"embedding dimension mismatch: model returned {len(v)}, configured {self.dimensions}")
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(self._call(texts[i:i + self.batch_size]))
            time.sleep(0)  # cooperative yield; provider-side rate limits handled by retry/backoff
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._call([text])[0]


class OpenAICompatibleEmbeddings(_HttpEmbeddings):
    def _request(self, batch: list[str]) -> list[list[float]]:
        ep = self.endpoint
        headers: dict[str, str] = {"Content-Type": "application/json"}
        body: dict[str, Any] = {"input": batch, "model": self.model_name}
        if ep.provider_type == "azure_openai":
            url = f"{(ep.base_url or '').rstrip('/')}/openai/deployments/{self.model_name}/embeddings"
            params = {"api-version": ep.api_version or "2024-06-01"}
            headers["api-key"] = ep.api_key or ""
        else:
            url = f"{(ep.base_url or 'https://api.openai.com/v1').rstrip('/')}/embeddings"
            params = {}
            if ep.api_key:
                headers["Authorization"] = f"Bearer {ep.api_key}"
        if self.model_name.startswith("text-embedding-3"):
            body["dimensions"] = self.dimensions
        r = self._client.post(url, json=body, headers=headers, params=params)
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]


class OllamaEmbeddings(_HttpEmbeddings):
    def _request(self, batch: list[str]) -> list[list[float]]:
        r = self._client.post(f"{(self.endpoint.base_url or 'http://localhost:11434').rstrip('/')}/api/embed",
                              json={"model": self.model_name, "input": batch})
        r.raise_for_status()
        return r.json()["embeddings"]


class HuggingFaceTEIEmbeddings(_HttpEmbeddings):
    def _request(self, batch: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.endpoint.api_key}"} if self.endpoint.api_key else {}
        r = self._client.post(f"{(self.endpoint.base_url or '').rstrip('/')}/embed",
                              json={"inputs": batch, "normalize": True, "truncate": True}, headers=headers)
        r.raise_for_status()
        return r.json()


def build_embeddings(endpoint: ProviderEndpoint, model_name: str, dimensions: int,
                     transport: httpx.BaseTransport | None = None) -> Embeddings:
    if endpoint.provider_type == "local":
        return LocalHashingEmbeddings(model_name, dimensions)
    if endpoint.provider_type in ("openai", "azure_openai", "openai_compatible"):
        return OpenAICompatibleEmbeddings(endpoint, model_name, dimensions, transport)
    if endpoint.provider_type == "ollama":
        return OllamaEmbeddings(endpoint, model_name, dimensions, transport)
    if endpoint.provider_type == "huggingface":
        return HuggingFaceTEIEmbeddings(endpoint, model_name, dimensions, transport)
    raise ValueError(f"unsupported embedding provider type {endpoint.provider_type}")


def vector_literal(vec: list[float]) -> str:
    """pgvector text representation, bound as a parameter (never interpolated)."""
    return "[" + ",".join(f"{v:.7f}" for v in vec) + "]"
