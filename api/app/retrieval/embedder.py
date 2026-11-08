"""Query embedding with the pinned model (EMBED_MODEL), through Ollama.

The indexer embeds documents with the same model and the matching document prefix
(indexer/pipeline/embed.py). Two models' vectors are not comparable, and the failure is
silent, so the model name is checked against the index at startup and on every /readyz
(app/services/readiness.py).
"""

from __future__ import annotations

from collections import OrderedDict

import httpx

from ..config import Settings


def query_prefix(model: str) -> str:
    return "search_query: " if "nomic" in model else ""


class OllamaEmbedder:
    def __init__(self, settings: Settings, cache_size: int = 256) -> None:
        self.model = settings.embed_model
        self.url = f"{settings.ollama_url.rstrip('/')}/api/embed"
        self.client = httpx.Client(timeout=30.0)
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size

    def embed_query(self, text: str) -> list[float]:
        """One vector for one question. Memoised: the cache and the retriever both need
        the same vector for the same request."""
        if text in self._cache:
            self._cache.move_to_end(text)
            return self._cache[text]
        r = self.client.post(self.url, json={"model": self.model,
                                             "input": [query_prefix(self.model) + text]})
        r.raise_for_status()
        vector = [float(x) for x in r.json()["embeddings"][0]]
        self._cache[text] = vector
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return vector
