# ADR 0004: Pluggable LLM provider (ollama-host by default) and what data leaves the cluster

## Status
Accepted · 8 November 2026

## Context
Generation can run on the laptop (Ollama), in the cluster (Ollama Deployment, at least 8 GB) or
at a hosted free tier (Groq, Google AI Studio, OpenRouter). Each choice changes cost, latency
and which data leaves our control.

## Decision
- `LLM_PROVIDER` in the ConfigMap selects the provider, behind one interface
  (`api/app/providers/llm/base.py`). Swapping provider is one file plus one ConfigMap value.
- **Default: `ollama-host`** with `llama3.2:3b`. The cluster reaches the laptop at
  `host.minikube.internal:11434`, with an egress NetworkPolicy to that one IP and port.
  Embeddings come from the same host (`nomic-embed-text`). Both the indexer and the API use it.
- `hosted` is implemented (OpenAI-compatible `/chat/completions` with JSON mode). The key comes
  only from the `rahbar-secret` Secret, created with `kubectl create secret`. It is never logged,
  never in `repr(Settings)`, and dropped from error messages.
- **Enforce, then validate:** Ollama gets the `Answer` JSON schema as `format`; the hosted
  provider gets JSON mode. Both are validated with Pydantic, retried once with the validation
  error, then fall back to a canned "could not produce a verified answer" (never a 500). Every
  call has a timeout (`LLM_TIMEOUT_S=90`).
- Temperature 0.1, set in the ConfigMap with a justification.

## Data governance
- What reaches the model: the question and the retrieved passages, all public documents from
  nu.edu.pk. No student records, no SLATE/Flex data, no credentials.
- With `ollama-host`, nothing leaves the laptop. With `hosted`, questions leave the cluster. A
  student may type personal details into a question, so the UI should say so before hosted mode
  is enabled, and logs record chunk ids and scores, never question text.
- Retrieved text and questions are untrusted data. They are fenced in `<evidence>` and
  `<question>` blocks, the instructions say they cannot change the rules, the output is
  schema-constrained, and model output is never evaluated, executed or used in SQL.

## Consequences
- The default needs Ollama running on the laptop with `OLLAMA_HOST=0.0.0.0`.
- A CPU-generated answer takes tens of seconds. The Ingress read timeout is 180 s, and CPU-based
  HPA is the wrong signal for this I/O-bound wait (ENGINEERING-NOTES.md, question 3).
