"""Hosted free-tier provider (Groq, Google AI Studio, OpenRouter): OpenAI-compatible.

The key arrives as LLM_API_KEY from a Kubernetes Secret created on the command
line. It never appears in a file we commit, and never in a log line.
"""

from __future__ import annotations

import httpx

from ...config import Settings
from ...routes import metrics
from ...schemas import Answer, Passage
from .prompt import GenerationError, dumps_schema, generate_validated


class HostedProvider:
    name = "hosted"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings   # hosted_base_url, llm_model, llm_api_key, temperature
        if not settings.hosted_base_url or not settings.llm_api_key:
            raise ValueError("LLM_PROVIDER=hosted needs HOSTED_BASE_URL and the LLM_API_KEY Secret")
        self.client = httpx.Client(timeout=httpx.Timeout(settings.llm_timeout_s, connect=5.0))

    def _chat(self, messages: list[dict[str, str]]) -> str:
        # JSON mode is the most widely supported enforcement on free tiers; the schema
        # itself travels in the system message, and Pydantic validates the result.
        messages = [{"role": messages[0]["role"],
                     "content": messages[0]["content"] + "\n\nJSON schema:\n" + dumps_schema()},
                    *messages[1:]]
        payload = {"model": self.settings.llm_model, "messages": messages,
                   "temperature": self.settings.temperature,
                   "max_tokens": self.settings.max_output_tokens,
                   "response_format": {"type": "json_object"}}
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        try:
            r = self.client.post(f"{self.settings.hosted_base_url.rstrip('/')}/chat/completions",
                                 json=payload, headers=headers)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            # never include the request (it carries the key) in the error
            raise GenerationError(f"hosted call failed: {type(exc).__name__}") from None
        body = r.json()
        usage = body.get("usage") or {}
        metrics.TOKENS.labels(direction="in").inc(usage.get("prompt_tokens", 0) or 0)
        metrics.TOKENS.labels(direction="out").inc(usage.get("completion_tokens", 0) or 0)
        return str(body["choices"][0]["message"]["content"] or "")

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        return generate_validated(self._chat, question, passages)
