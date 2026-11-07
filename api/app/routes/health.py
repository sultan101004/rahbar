"""Liveness and readiness (section 4.3). They answer different questions."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ..services import readiness

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Is the process alive? Must never touch Chroma, Redis or the LLM."""
    return {"status": "alive"}


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, object]:
    """Can this pod take traffic? 503, naming the failed dependency, unless Chroma is
    reachable, the collection is non-empty (count() > 0), the embedding model matches
    EMBED_MODEL, and Redis answers. A 503 removes the pod from the Service; it is not
    restarted."""
    state = request.app.state
    ok, checks = readiness.check(state.retriever, state.cache, state.settings)
    if not ok:
        response.status_code = 503
    return {"status": "ready" if ok else "not ready", "checks": checks}
