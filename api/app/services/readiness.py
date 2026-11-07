"""Readiness (section 4.3) and the embedding-pin guardrail (section 4.4).

Ready means: Chroma reachable, the collection exists and is non-empty, the collection was
built with the same EMBED_MODEL this pod is pinned to, and Redis (if configured) answers.
Liveness (/healthz) deliberately calls none of this.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import Settings

log = logging.getLogger("rahbar.readiness")


def pin_conflict(index_model: str | None, settings: Settings) -> str | None:
    """A message naming the conflict when the index's embedding model != EMBED_MODEL."""
    if index_model is None:
        return (f"index has no embed_model metadata; API pinned to EMBED_MODEL="
                f"{settings.embed_model!r}. Re-run the indexer Job.")
    if index_model != settings.embed_model:
        return (f"embedding model mismatch: index built with {index_model!r}, API pinned to "
                f"EMBED_MODEL={settings.embed_model!r}. Vectors from different models are not "
                f"comparable; refusing to serve. Re-index or restore the ConfigMap.")
    return None


def check(retriever: Any, cache: Any, settings: Settings) -> tuple[bool, dict[str, str]]:
    checks: dict[str, str] = {}
    ok = True
    index_info = getattr(retriever, "index_info", None)
    if index_info is None:
        checks["chroma"] = "skipped (stub retriever)"
    else:
        try:
            info = index_info(fresh=True)
        except Exception as exc:
            ok = False
            checks["chroma"] = f"unreachable or no collection: {type(exc).__name__}"
        else:
            if info.count <= 0:
                ok = False
                checks["chroma"] = "collection is empty: run the indexer Job"
            else:
                checks["chroma"] = f"ok ({info.count} chunks, index {info.index_id})"
            conflict = pin_conflict(info.embed_model, settings)
            if conflict:
                ok = False
                checks["embed_model"] = conflict
            else:
                checks["embed_model"] = f"ok ({settings.embed_model})"
    if not getattr(cache, "enabled", False):
        checks["redis"] = "skipped (no REDIS_URL)"
    else:
        try:
            cache.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            ok = False
            checks["redis"] = f"unreachable: {type(exc).__name__}"
    return ok, checks


def startup_pin_check(retriever: Any, settings: Settings) -> str | None:
    """Run once in the lifespan. Logs the exact conflict; /readyz keeps refusing until fixed."""
    index_info = getattr(retriever, "index_info", None)
    if index_info is None:
        return None
    try:
        info = index_info(fresh=True)
    except Exception as exc:
        log.warning("index not available at startup; staying not-ready until it is",
                    extra={"error": type(exc).__name__})
        return None
    conflict = pin_conflict(info.embed_model, settings)
    if conflict:
        log.error("EMBEDDING PIN CONFLICT", extra={"index_embed_model": info.embed_model,
                                                   "api_embed_model": settings.embed_model,
                                                   "index_dimension": info.dimension,
                                                   "detail": conflict})
    else:
        log.info("embedding pin verified", extra={"embed_model": settings.embed_model,
                                                  "dimension": info.dimension})
    return conflict
