"""Ollama provider: ollama-host or ollama-incluster (section 3.5).

The only difference between the two modes is OLLAMA_URL in the ConfigMap:
http://host.minikube.internal:11434 (host) or http://ollama:11434 (in-cluster).
"""

from __future__ import annotations

import httpx

from ...config import Settings
from ...routes import metrics
from ...schemas import Answer, Passage
from .prompt import GenerationError, answer_schema, generate_validated


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings   # ollama_url, llm_model, temperature
        self.client = httpx.Client(timeout=httpx.Timeout(settings.llm_timeout_s, connect=5.0))

    def _chat(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "stream": False,
            # constrained decoding: Ollama restricts sampling to this JSON schema
            "format": answer_schema(),
            "options": {"temperature": self.settings.temperature,
                        "num_predict": self.settings.max_output_tokens},
        }
        try:
            r = self.client.post(f"{self.settings.ollama_url.rstrip('/')}/api/chat", json=payload)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise GenerationError(f"ollama call failed: {type(exc).__name__}") from exc
        body = r.json()
        metrics.TOKENS.labels(direction="in").inc(body.get("prompt_eval_count", 0) or 0)
        metrics.TOKENS.labels(direction="out").inc(body.get("eval_count", 0) or 0)
        return str(body.get("message", {}).get("content", ""))

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        return generate_validated(self._chat, question, passages)
