"""Runtime configuration, read once from environment variables.

On the cluster these variables come from your ConfigMap and Secret (section 4.1).
Nothing here is baked into the image, so one image runs in every environment.
Add your own keys (relevance floor, cache settings, ...) the same way.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    # Which implementations to load. "stub" needs no cluster, no model, no network.
    retriever: str = "stub"          # RETRIEVER: stub | chroma
    llm_provider: str = "stub"       # LLM_PROVIDER: stub | ollama-host | ollama-incluster | hosted

    # The embedding pin (section 4.4). The indexer reads the same ConfigMap key.
    embed_model: str = "nomic-embed-text"

    # Vector store
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    collection: str = "rahbar"

    # Retrieval and generation
    top_k: int = 5
    temperature: float = 0.2
    llm_model: str = "llama3.2:3b"
    ollama_url: str = "http://host.minikube.internal:11434"
    hosted_base_url: str = ""        # e.g. an OpenAI-compatible endpoint
    llm_api_key: str = field(default="", repr=False)   # from the Secret; never log it
    llm_timeout_s: float = 90.0      # a hung model call must not hold a worker forever
    max_output_tokens: int = 700

    # Grounding (3.4): a passage below this cosine similarity is not evidence.
    relevance_floor: float = 0.70

    # Semantic cache (3.3). Empty REDIS_URL disables the cache (unit tests, local dev).
    redis_url: str = ""
    cache_threshold: float = 0.93
    cache_ttl_s: int = 86400
    cache_max_entries: int = 500

    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings(
        retriever=os.environ.get("RETRIEVER", "stub"),
        llm_provider=os.environ.get("LLM_PROVIDER", "stub"),
        embed_model=os.environ.get("EMBED_MODEL", "nomic-embed-text"),
        chroma_host=os.environ.get("CHROMA_HOST", "chroma"),
        chroma_port=_int("CHROMA_PORT", 8000),
        collection=os.environ.get("CHROMA_COLLECTION", "rahbar"),
        top_k=_int("TOP_K", 5),
        temperature=_float("TEMPERATURE", 0.2),
        llm_model=os.environ.get("LLM_MODEL", "llama3.2:3b"),
        ollama_url=os.environ.get("OLLAMA_URL", "http://host.minikube.internal:11434"),
        hosted_base_url=os.environ.get("HOSTED_BASE_URL", ""),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        llm_timeout_s=_float("LLM_TIMEOUT_S", 90.0),
        max_output_tokens=_int("MAX_OUTPUT_TOKENS", 700),
        relevance_floor=_float("RELEVANCE_FLOOR", 0.70),
        redis_url=os.environ.get("REDIS_URL", ""),
        cache_threshold=_float("CACHE_THRESHOLD", 0.93),
        cache_ttl_s=_int("CACHE_TTL_S", 86400),
        cache_max_entries=_int("CACHE_MAX_ENTRIES", 500),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
