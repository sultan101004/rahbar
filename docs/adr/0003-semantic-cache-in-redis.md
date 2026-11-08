# ADR 0003: The semantic cache lives in Redis, keyed by index generation

## Status
Accepted · 8 November 2026

## Context
Generation is the slow, expensive step: about 20–80 s per answer for llama3.2:3b on a laptop CPU.
Students ask the same handful of questions in many wordings. A semantic cache returns a stored
answer when a new question's embedding is close enough to one already answered. It must be
shared by all API replicas, survive a pod restart, and be invalidated when the index changes.

## Decision
- **Redis** (`k8s/base/redis.yaml`): a Deployment with `Recreate`, an append-only file on the
  `cache-data` PVC, a ClusterIP Service, and reachable from the api pods only (NetworkPolicy).
- Entries live in a list per index generation: `rahbar:cache:<index_id>`. Each entry holds the
  question vector and the response. A lookup scans at most 500 entries and computes cosine in
  Python, which is microseconds at this scale.
- A hit means cosine ≥ `CACHE_THRESHOLD`, which is 0.93: the lowest threshold with zero false
  hits on our pairs (PIPELINE.md).
- Invalidation on re-index: the indexer stamps a new `index_id`, so lookups move to an empty key
  at once. The first pod that notices also deletes the old keys.
- Never cached: follow-ups, abstentions, fallbacks, and answers without valid citations.
- A Redis outage is a cache miss, never a failed question. `/readyz` still reports Redis, so the
  outage is visible.

## Options considered
- **A second Chroma collection:** it has vector search built in. But the indexer's
  build-then-swap rewrites collections, the cache would then share the vector store's PVC and
  failure domain, and the API would need write access to Chroma. That breaks "the indexer is the
  only writer" (ADR 0001).
- **An in-process dict:** not shared across 3–8 replicas, and lost on every restart.
- **Exact-string caching:** misses every paraphrase, so the hit rate is near zero.

## Consequences
- A linear scan is fine for hundreds of entries. Thousands would need RediSearch's vector index.
- One more stateful component with a PVC. Losing it costs only latency, never correctness.
