"""Stage 4: Embed. One vector per chunk, from the pinned model only."""

from __future__ import annotations

import json
import time

import httpx

from .config import IndexerSettings

BATCH = 32
TIMEOUT_S = 300.0


def document_prefix(model: str) -> str:
    """nomic-embed-text is trained with task prefixes; documents and queries differ.
    The API uses the matching 'search_query: ' prefix (api/app/retrieval/embedder.py)."""
    return "search_document: " if "nomic" in model else ""


def embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
    """Embed with settings.embed_model and nothing else.

    With Ollama: POST {ollama_url}/api/embed with {"model": ..., "input": [texts]}
    returns {"embeddings": [[...], ...]}. Batched: one request per chunk is slow.
    """
    prefix = document_prefix(settings.embed_model)
    vectors: list[list[float]] = []
    with httpx.Client(timeout=TIMEOUT_S) as client:
        for start in range(0, len(texts), BATCH):
            batch = [prefix + t for t in texts[start:start + BATCH]]
            vectors.extend(_embed_batch(client, settings, batch))
            print(json.dumps({"logger": "rahbar.indexer.embed", "msg": "embedded",
                              "done": len(vectors), "total": len(texts)}), flush=True)
    dims = {len(v) for v in vectors}
    if len(dims) > 1:
        raise RuntimeError(f"embedding model returned mixed dimensions: {sorted(dims)}")
    return vectors


def _embed_batch(client: httpx.Client, settings: IndexerSettings,
                 batch: list[str], attempts: int = 3) -> list[list[float]]:
    url = f"{settings.ollama_url.rstrip('/')}/api/embed"
    for attempt in range(1, attempts + 1):
        try:
            r = client.post(url, json={"model": settings.embed_model, "input": batch})
            r.raise_for_status()
            vectors = r.json()["embeddings"]
            if len(vectors) != len(batch):
                raise RuntimeError(f"asked for {len(batch)} vectors, got {len(vectors)}")
            return [[float(x) for x in v] for v in vectors]
        except (httpx.HTTPError, KeyError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"embedding failed after {attempts} attempts: {exc}") from exc
            time.sleep(2 * attempt)   # Ollama may still be loading the model
    raise AssertionError("unreachable")
