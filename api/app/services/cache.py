"""Semantic cache (section 3.3), in Redis. ADR 0003 says why Redis and not Chroma.

A hit is a previous question whose embedding has cosine similarity >= CACHE_THRESHOLD
(from the ConfigMap) with this one, asked against the SAME index.

Invalidation on re-index: every entry lives under a key that names the index it was
answered from (`rahbar:cache:<index_id>`). The indexer stamps a new index_id on each run,
so the moment the new index is live, lookups go to a new, empty key: old answers are
never served. The first pod that sees the new index_id also deletes the old keys.

Never cached: follow-up questions, abstentions, fallbacks, anything without citations.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any, Protocol

log = logging.getLogger("rahbar.cache")
PREFIX = "rahbar:cache:"

_FOLLOWUP_START = re.compile(r"^\s*(and|also|but|so|then|what about|how about|what if|"
                             r"why not|same for|and if)\b", re.I)
_PRONOUN = re.compile(r"\b(it|that|this|those|these|they|them|he|she|its|there)\b", re.I)


def is_followup(question: str) -> bool:
    """A follow-up depends on an earlier turn, so its meaning is not in its own words and
    a cached answer for the same words could be wrong. 'And for MS?' / 'What about it?'"""
    words = question.split()
    return bool(_FOLLOWUP_START.match(question)) or (len(words) <= 6 and bool(_PRONOUN.search(question)))


def should_cache(question: str, response: dict[str, Any], used_fallback: bool) -> bool:
    """never_cache rules: a cached mistake is served to everyone."""
    return (not used_fallback and not is_followup(question)
            and bool(response.get("answered_from_context")) and bool(response.get("citations")))


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else -1.0


class Cache(Protocol):
    enabled: bool

    def ping(self) -> bool: ...
    def lookup(self, index_id: str, vector: list[float]) -> tuple[dict[str, Any], float] | None: ...
    def store(self, index_id: str, vector: list[float], question: str,
              response: dict[str, Any]) -> None: ...


class NullCache:
    """No Redis configured (unit tests, `make dev`): every lookup misses."""

    enabled = False

    def ping(self) -> bool:
        return True

    def lookup(self, index_id: str, vector: list[float]) -> tuple[dict[str, Any], float] | None:
        return None

    def store(self, index_id: str, vector: list[float], question: str,
              response: dict[str, Any]) -> None:
        return None


class SemanticCache:
    enabled = True

    def __init__(self, client: Any, threshold: float, ttl_s: int, max_entries: int) -> None:
        self.r = client
        self.threshold = threshold
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self._current_index: str | None = None

    @classmethod
    def from_url(cls, url: str, threshold: float, ttl_s: int, max_entries: int) -> SemanticCache:
        import redis

        client = redis.Redis.from_url(url, socket_timeout=1.0, socket_connect_timeout=1.0)
        return cls(client, threshold, ttl_s, max_entries)

    def ping(self) -> bool:
        return bool(self.r.ping())

    def _key(self, index_id: str) -> str:
        return PREFIX + index_id

    def invalidate_other_generations(self, index_id: str) -> int:
        """Expire every entry answered from an older index."""
        stale = [k for k in self.r.scan_iter(match=PREFIX + "*", count=100)
                 if (k.decode() if isinstance(k, bytes) else k) != self._key(index_id)]
        if stale:
            self.r.delete(*stale)
            log.info("cache invalidated after re-index", extra={"index_id": index_id,
                                                                "keys_deleted": len(stale)})
        return len(stale)

    def _observe(self, index_id: str) -> None:
        if index_id != self._current_index:
            self.invalidate_other_generations(index_id)
            self._current_index = index_id

    def lookup(self, index_id: str, vector: list[float]) -> tuple[dict[str, Any], float] | None:
        try:
            self._observe(index_id)
            best: tuple[dict[str, Any], float] | None = None
            for raw in self.r.lrange(self._key(index_id), 0, self.max_entries - 1):
                entry = json.loads(raw)
                sim = cosine(vector, entry["v"])
                if sim >= self.threshold and (best is None or sim > best[1]):
                    best = (entry["r"], sim)
            return best
        except Exception as exc:          # a cache outage must never fail a question
            log.warning("cache lookup failed", extra={"error": type(exc).__name__})
            return None

    def store(self, index_id: str, vector: list[float], question: str,
              response: dict[str, Any]) -> None:
        try:
            key = self._key(index_id)
            entry = json.dumps({"q": question, "v": vector, "r": response})
            pipe = self.r.pipeline()
            pipe.lpush(key, entry)
            pipe.ltrim(key, 0, self.max_entries - 1)
            pipe.expire(key, self.ttl_s)
            pipe.execute()
        except Exception as exc:
            log.warning("cache store failed", extra={"error": type(exc).__name__})


def build_cache(redis_url: str, threshold: float, ttl_s: int, max_entries: int) -> Cache:
    if not redis_url:
        return NullCache()
    return SemanticCache.from_url(redis_url, threshold, ttl_s, max_entries)
