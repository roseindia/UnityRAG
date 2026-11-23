"""Chat models behind LangChain's BaseChatModel interface (FR-134, AD-04, AD-05, NFR-081).

* ExtractiveChatModel - offline, deterministic "local" model that composes an
  answer exclusively from sentences of the supplied sources and cites them.
  Used when no LLM endpoint is configured (development, air-gapped
  evaluation, automated tests).  It cannot hallucinate beyond its context.
* OpenAICompatibleChatModel - OpenAI, Azure OpenAI, Ollama (/v1), vLLM, TGI
  and other OpenAI-compatible chat-completions endpoints, with streaming.
"""
from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from typing import Any

import httpx
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import ConfigDict

from app.integrations.provider_registry import ProviderEndpoint
from app.rag.chunking.chunker import count_tokens
from app.rag.embeddings.providers import normalise_terms

_SOURCE = re.compile(r'<source id="(S\d+)"(?:\s+\w+="[^"]*")*\s*>\n?(.*?)\n?</source>', re.S)
_TITLE = re.compile(r'<source id="(S\d+)"\s+title="([^"]*)"')
_QUESTION = re.compile(r"<question>\n?(.*?)\n?</question>", re.S)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])|\n+")
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


def _strip_breadcrumb(line: str) -> str:
    """Remove the navigation prefix ("Title > Section > ") that chunking prepends to a passage.

    Chunks are flattened to one line, so the breadcrumb and the body share a line. Keep only the text
    after the last " > " instead of discarding the whole line, which dropped the evidence."""
    if " > " not in line or line.rstrip().endswith((".", ";", ":", "?")):
        return line
    return line.rsplit(" > ", 1)[1]


def _text_of(messages: list[BaseMessage]) -> str:
    return "\n".join(m.content if isinstance(m.content, str) else json.dumps(m.content) for m in messages)


class ExtractiveChatModel(BaseChatModel):
    model_name: str = "extractive-v1"
    max_sentences: int = 4

    @property
    def _llm_type(self) -> str:
        return "local-extractive"

    def _answer(self, prompt: str) -> str:
        sources = _SOURCE.findall(prompt)
        title_of = dict(_TITLE.findall(prompt))
        qm = _QUESTION.search(prompt)
        question = qm.group(1) if qm else prompt[-500:]
        q_terms = set(normalise_terms(question))
        if not sources or not q_terms:
            return INSUFFICIENT
        scored: list[tuple[float, int, str, str]] = []
        for order, (sid, body) in enumerate(sources):
            # drop contextual header lines ("Title > Section ...") that chunking / parent
            # expansion prepend - they are navigation, not evidence
            body = html.unescape(body)
            body = "\n".join(_strip_breadcrumb(l) for l in body.split("\n"))
            title = html.unescape(title_of.get(sid, "")).strip().lower()
            for sent in _SENT.split(body):
                sent = sent.strip(" -|")
                if len(sent) < 25 or sent.startswith("|") or sent.lower() == title:
                    continue
                terms = set(normalise_terms(sent))
                if not terms:
                    continue
                overlap = len(q_terms & terms)
                if overlap == 0:
                    continue
                score = overlap / len(q_terms) + 0.15 * overlap / (len(terms) ** 0.5) - 0.02 * order
                scored.append((score, order, sid, sent))
        scored.sort(key=lambda x: -x[0])
        if not scored or scored[0][0] < 0.34:
            return INSUFFICIENT
        picked, seen = [], set()
        for score, _, sid, sent in scored:
            key = sent.lower()[:80]
            if key in seen or score < scored[0][0] * 0.45:
                continue
            seen.add(key)
            picked.append(f"{sent.rstrip('.')}. [{sid}]")
            if len(picked) >= self.max_sentences:
                break
        return "Based on the approved sources: " + " ".join(picked)

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        prompt = _text_of(messages)
        answer = self._answer(prompt)
        msg = AIMessage(content=answer, usage_metadata={"input_tokens": count_tokens(prompt),
                                                        "output_tokens": count_tokens(answer),
                                                        "total_tokens": count_tokens(prompt) + count_tokens(answer)})
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        answer = self._answer(_text_of(messages))
        for piece in re.findall(r"\S+\s*", answer):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if run_manager:
                run_manager.on_llm_new_token(piece, chunk=chunk)
            yield chunk


class OpenAICompatibleChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    model_name: str
    provider_type: str = "openai"
    base_url: str | None = None
    api_key: str | None = None
    api_version: str | None = None
    temperature: float = 0.1
    max_tokens: int = 800
    timeout: float = 60.0
    transport: Any = None

    @property
    def _llm_type(self) -> str:
        return f"{self.provider_type}-chat"

    def _request(self, messages: list[BaseMessage], stream: bool) -> tuple[str, dict, dict, dict]:
        role = {"system": "system", "human": "user", "ai": "assistant"}
        body = {"model": self.model_name, "temperature": self.temperature, "max_tokens": self.max_tokens,
                "stream": stream, "messages": [{"role": role.get(m.type, "user"), "content": m.content} for m in messages]}
        headers = {"Content-Type": "application/json"}
        params: dict[str, str] = {}
        if self.provider_type == "azure_openai":
            url = f"{(self.base_url or '').rstrip('/')}/openai/deployments/{self.model_name}/chat/completions"
            params["api-version"] = self.api_version or "2024-06-01"
            headers["api-key"] = self.api_key or ""
        else:
            default = "http://localhost:11434/v1" if self.provider_type == "ollama" else "https://api.openai.com/v1"
            url = f"{(self.base_url or default).rstrip('/')}/chat/completions"
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
        if stream:
            body["stream_options"] = {"include_usage": True}
        return url, body, headers, params

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        url, body, headers, params = self._request(messages, stream=False)
        with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
            r = client.post(url, json=body, headers=headers, params=params)
            r.raise_for_status()
            data = r.json()
        content = data["choices"][0]["message"].get("content") or ""
        usage = data.get("usage") or {}
        msg = AIMessage(content=content, usage_metadata={"input_tokens": usage.get("prompt_tokens", 0),
                                                         "output_tokens": usage.get("completion_tokens", 0),
                                                         "total_tokens": usage.get("total_tokens", 0)})
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        url, body, headers, params = self._request(messages, stream=True)
        with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
            with client.stream("POST", url, json=body, headers=headers, params=params) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    data = json.loads(payload)
                    usage = data.get("usage")
                    choices = data.get("choices") or []
                    delta = (choices[0].get("delta") or {}).get("content") if choices else None
                    if delta:
                        chunk = ChatGenerationChunk(message=AIMessageChunk(content=delta))
                        if run_manager:
                            run_manager.on_llm_new_token(delta, chunk=chunk)
                        yield chunk
                    if usage:
                        yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata={
                            "input_tokens": usage.get("prompt_tokens", 0),
                            "output_tokens": usage.get("completion_tokens", 0),
                            "total_tokens": usage.get("total_tokens", 0)}))


def build_chat_model(endpoint: ProviderEndpoint, model: str, temperature: float, max_tokens: int,
                     transport: httpx.BaseTransport | None = None) -> BaseChatModel:
    if endpoint.provider_type == "local":
        return ExtractiveChatModel(model_name=model)
    return OpenAICompatibleChatModel(model_name=model, provider_type=endpoint.provider_type, base_url=endpoint.base_url,
                                     api_key=endpoint.api_key, api_version=endpoint.api_version,
                                     temperature=temperature, max_tokens=max_tokens, transport=transport)
