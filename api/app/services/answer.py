"""Turns a question into an AskResponse: the query pipeline of section 3.2.

1 receive (validated by AskRequest: 3-500 chars)   5 augment   (providers/llm/prompt.py)
2 cache check (skipped for follow-ups)            6 generate  (provider, low temperature)
3 embed with the pinned model                     7 validate  (retry once, then fallback)
4 retrieve top-k, superseded filtered out         8 store the turn, and a cache entry if safe

Each step lives in its own module so it can be tested alone; this function only wires
them together and logs one line per request.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider
from ..providers.llm.prompt import GenerationError
from ..retrieval.base import Retriever
from ..routes import metrics
from ..schemas import AskResponse, Passage, RetrievedRef
from . import grounding
from .cache import Cache, NullCache, is_followup, should_cache

log = logging.getLogger("rahbar.answer")


@dataclass
class Outcome:
    response: AskResponse
    cached: bool = False


def _refs(passages: list[Passage]) -> list[RetrievedRef]:
    return [RetrievedRef(chunk_id=p.chunk_id, source=p.source, section=p.section,
                         page=p.page, score=p.score) for p in passages]


def answer_question(question: str, retriever: Retriever, provider: LLMProvider,
                    settings: Settings, cache: Cache | None = None) -> AskResponse:
    return run(question, retriever, provider, settings, cache).response


def run(question: str, retriever: Retriever, provider: LLMProvider, settings: Settings,
        cache: Cache | None = None) -> Outcome:
    cache = cache or NullCache()
    rid = request_id_var.get()
    followup = is_followup(question)

    # 2. cache check: needs the question vector and the live index id
    vector: list[float] | None = None
    index_id = ""
    embed_query = getattr(retriever, "embed_query", None)
    if cache.enabled and embed_query is not None and not followup:
        try:
            qvec: list[float] = embed_query(question)
            vector = qvec
            index_id = retriever.index_info().index_id  # type: ignore[attr-defined]
            hit = cache.lookup(index_id, qvec)
        except Exception as exc:
            log.warning("cache check skipped", extra={"error": type(exc).__name__})
            hit = None
        if hit:
            metrics.CACHE.labels(result="hit").inc()
            cached_body, sim = hit
            log.info("answered", extra={"cache": "hit", "cache_similarity": round(sim, 4),
                                        "answered_from_context": True})
            return Outcome(AskResponse(**{**cached_body, "request_id": rid}), cached=True)
        metrics.CACHE.labels(result="miss").inc()
    elif cache.enabled:
        metrics.CACHE.labels(result="skip").inc()

    # 3-4. embed + retrieve
    started = time.perf_counter()
    passages = retriever.retrieve(question, k=settings.top_k)
    metrics.RETRIEVAL_LATENCY.observe(time.perf_counter() - started)

    # floor: decide abstention before spending a model call
    evidence = grounding.above_floor(passages, settings.relevance_floor)
    used_fallback = False
    dropped = 0
    if not evidence:
        answer = grounding.abstention("no retrieved passage cleared the relevance floor")
        metrics.ABSTENTIONS.labels(reason="below_floor").inc()
    else:
        # 5-7. augment, generate, validate (retry inside the provider), fallback here
        started = time.perf_counter()
        try:
            answer = provider.generate(question, evidence)
        except GenerationError as exc:
            log.warning("generation failed, serving fallback", extra={"error": str(exc)})
            answer = grounding.fallback()
            used_fallback = True
            metrics.FALLBACKS.labels(reason="generation").inc()
        metrics.GENERATION_LATENCY.observe(time.perf_counter() - started)
        # cite only what was retrieved for THIS request
        answer, dropped = grounding.enforce_citations(answer, evidence)
        if dropped:
            metrics.CITATIONS_DROPPED.inc(dropped)
        if not answer.answered_from_context and not used_fallback:
            metrics.ABSTENTIONS.labels(reason="model_declined").inc()

    response = AskResponse(
        request_id=rid, answer=answer.answer, citations=answer.citations,
        answered_from_context=answer.answered_from_context, confidence=answer.confidence,
        retrieved=_refs(passages), provider=provider.name,
    )
    # 8. one structured line per request: where five of six failure stages are visible
    log.info("answered", extra={
        "cache": "miss" if cache.enabled else "off", "retriever": retriever.name,
        "provider": provider.name, "top_k": settings.top_k,
        "chunk_ids": [p.chunk_id for p in passages],
        "scores": [round(p.score, 4) for p in passages],
        "lexical": [p.chunk_id for p in passages if p.lexical],
        "evidence": len(evidence), "floor": settings.relevance_floor,
        "answered_from_context": response.answered_from_context,
        "citations_dropped": dropped, "fallback": used_fallback, "followup": followup,
    })
    body: dict[str, Any] = response.model_dump()
    if vector is not None and index_id and should_cache(question, body, used_fallback):
        cache.store(index_id, vector, question, body)
    return Outcome(response)
