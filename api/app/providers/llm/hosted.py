"""Hosted free-tier provider (Groq, Google AI Studio, OpenRouter): OpenAI-compatible.

The key arrives as LLM_API_KEY from a Kubernetes Secret created on the command
line. It never appears in a file we commit, and never in a log line.
"""

from __future__ import annotations

import re
import time

import httpx

from ...config import Settings
from ...routes import metrics
from ...schemas import Answer, Passage
from .prompt import GenerationError, dumps_schema, generate_validated


MAX_RATE_LIMIT_RETRIES = 2
MAX_RATE_LIMIT_WAIT_S = 30.0


def _retry_after(response: httpx.Response) -> float:
    """Seconds to wait from Retry-After, or from 'try again in 12.3s' in the body."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return max(0.5, float(header))
        except ValueError:
            pass
    m = re.search(r"try again in ([0-9.]+)s", response.text)
    return max(0.5, float(m.group(1))) if m else 5.0


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
        payload: dict = {"model": self.settings.llm_model, "messages": messages,
                         "temperature": self.settings.temperature,
                         "max_tokens": self.settings.max_output_tokens,
                         "response_format": {"type": "json_object"}}
        if self.settings.reasoning_effort:      # reasoning models (gpt-oss): fewer hidden tokens
            payload["reasoning_effort"] = self.settings.reasoning_effort
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        url = f"{self.settings.hosted_base_url.rstrip('/')}/chat/completions"
        r = None
        for attempt in range(1, MAX_RATE_LIMIT_RETRIES + 2):
            try:
                r = self.client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                # never include the request (it carries the key) in the error
                raise GenerationError(f"hosted call failed: {type(exc).__name__}") from None
            if r.status_code == 429 and attempt <= MAX_RATE_LIMIT_RETRIES:
                # free tiers limit tokens per minute: wait as told, then try again
                wait = min(_retry_after(r), MAX_RATE_LIMIT_WAIT_S)
                metrics.FALLBACKS.labels(reason="rate_limit_wait").inc()
                time.sleep(wait)
                continue
            break
        assert r is not None
        if r.status_code == 400 and "json_validate_failed" in r.text:
            # the provider rejected invalid JSON itself: hand back an invalid reply so the
            # shared validate-then-retry-once path (prompt.generate_validated) takes over
            return ""
        if r.status_code >= 400:
            raise GenerationError(f"hosted call failed: HTTP {r.status_code}")
        body = r.json()
        usage = body.get("usage") or {}
        metrics.TOKENS.labels(direction="in").inc(usage.get("prompt_tokens", 0) or 0)
        metrics.TOKENS.labels(direction="out").inc(usage.get("completion_tokens", 0) or 0)
        return str(body["choices"][0]["message"]["content"] or "")

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        return generate_validated(self._chat, question, passages)
