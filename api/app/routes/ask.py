"""POST /api/ask. The Ingress sends /api/* here unchanged, so the prefix stays."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ..schemas import AskRequest, AskResponse
from ..services.answer import run

router = APIRouter(prefix="/api")


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request, response: Response) -> AskResponse:
    state = request.app.state
    outcome = run(body.question, state.retriever, state.provider, state.settings, state.cache)
    response.headers["X-Cache"] = "HIT" if outcome.cached else "MISS"
    return outcome.response
