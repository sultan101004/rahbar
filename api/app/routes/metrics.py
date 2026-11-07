"""Prometheus metrics at /metrics (section 4.8).

Request count and latency, plus the pipeline's own signals: retrieval and generation
latency, cache hits and misses, abstentions, fallbacks, and tokens in and out.
Cache hit ratio = rahbar_cache_lookups_total{result="hit"} / sum(rahbar_cache_lookups_total).
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

router = APIRouter()

REQUESTS = Counter("rahbar_requests_total", "HTTP requests", ["path", "status"])
LATENCY = Histogram(
    "rahbar_request_seconds",
    "HTTP request latency",
    ["path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
RETRIEVAL_LATENCY = Histogram(
    "rahbar_retrieval_seconds", "Embed + vector search latency",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
GENERATION_LATENCY = Histogram(
    "rahbar_generation_seconds", "LLM generation latency (including one retry)",
    buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120),
)
CACHE = Counter("rahbar_cache_lookups_total", "Semantic cache lookups", ["result"])
ABSTENTIONS = Counter("rahbar_abstentions_total", "Answers declined", ["reason"])
FALLBACKS = Counter("rahbar_fallbacks_total", "Canned fallbacks served", ["reason"])
TOKENS = Counter("rahbar_llm_tokens_total", "LLM tokens", ["direction"])
CITATIONS_DROPPED = Counter("rahbar_citations_dropped_total",
                            "Model citations removed because no retrieved chunk matched them")


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
