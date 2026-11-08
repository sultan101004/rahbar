# Engineering notes

Line numbers refer to the commit that adds this file.

## 1. Indexing in API startup: what breaks with 3 replicas and one Chroma volume?

- **What breaks:** three writers on one collection. With the starter's `write_dummy_index`
  pattern (delete the collection, create it, add), pod A deletes the collection pod B is halfway
  through filling. The surviving index is a mix that no single run produced, or `add` fails with
  duplicate ids. On top of that, every restart, rollout step and HPA scale-up pays the full index
  cost: 182 s and about 1 GB per pod in our measurement. A rolling update with
  `maxUnavailable: 0` would then wait minutes per pod, and a 60 s startup budget
  (`failureThreshold: 30 × periodSeconds: 2`) would kill pods mid-OCR.
- **The object that prevents it:** the `Job` at `k8s/base/indexer.yaml:20` (plus the CronJob with
  `concurrencyPolicy: Forbid` at line 110) is the only writer. The API's lifespan
  (`api/app/main.py:37-42`) builds a cache client and runs a *read-only* pin check; nothing in
  `api/` calls `add`, `upsert` or `delete_collection`.
- **The line in our manifest:** `replicas: 3` at `k8s/base/api.yaml:22` is the reason it matters,
  and `readinessProbe: /readyz` at `k8s/base/api.yaml:63` is what keeps those three pods out of
  the Service until the Job has produced a non-empty index.

## 2. Readiness and liveness swapped, Chroma slow for 90 seconds: what happens?

If liveness pointed at `/readyz`, which checks Chroma (`api/app/services/readiness.py:30`), and
readiness at `/healthz`:

- Liveness runs every 20 s with `failureThreshold: 3` (`k8s/base/api.yaml:59-62`). After about
  60 s of a slow Chroma, the kubelet kills **all three** api containers, because they all depend on
  the same slow Chroma. They restart, the startup probe passes (`/healthz` is fine), and liveness
  fails again 60 s later. That is a restart storm, `CrashLoopBackOff` with growing back-off. When
  Chroma recovers at 90 s, the pods are sitting in back-off for up to minutes, so a 90 s blip
  becomes a longer outage, and every in-flight request is dropped at each kill.
- Meanwhile readiness on `/healthz` always says yes, so the Service keeps sending traffic to pods
  that cannot retrieve. Users get errors instead of the pods being briefly withheld.
- With our wiring, a slow Chroma makes `/readyz` 503, so pods leave the Endpoints and nobody is
  restarted. When Chroma recovers they rejoin within one 10 s period. Liveness protects the pod;
  readiness protects the users. `/healthz` touches nothing (`api/app/routes/health.py:13`).

## 3. What does a CPU-based HPA measure on a generation service, and what should scale it?

Our HPA (`k8s/base/api.yaml:96-108`) targets 70% of `requests.cpu: 100m`. During a question the
api pod spends 20–80 s waiting on an HTTP response from Ollama (the `rahbar_generation_seconds`
histogram, `api/app/routes/metrics.py:26`) and almost no time computing. From the pod's point of
view generation is I/O-bound, so CPU stays near idle while the service is saturated. The HPA
measures **the cost of JSON parsing and cosine math, not load**, and will not scale out while
users queue.

The signal that should scale it is **concurrent in-flight requests per pod**, or equivalently
request latency or queue depth, plus the provider's own saturation. To use it you need:

1. a gauge such as `rahbar_inflight_requests` incremented around `/api/ask` (we already export
   request latency and generation latency);
2. Prometheus scraping `/metrics`;
3. an adapter that exposes it to the HPA (prometheus-adapter or KEDA);
4. an HPA with `type: Pods` on that metric, e.g. a target of 2 in-flight per pod.

Also, scaling the api does not add generation capacity when one Ollama on one laptop does all
the work. The real bottleneck is the provider, so in hosted mode the limit is the provider's
rate limit, not pods.

## 4. The indexer's peak memory, its limit, the margin, and the exit code when it is wrong

- **Measured peak:** 977.8 MiB for the real corpus (OCR of 23 pages at 200 dpi + pdfplumber on
  58- and 64-page PDFs + 239 vectors in memory). We sampled `docker stats` every 2 s while the
  indexer image ran the same command the Job runs (`corpus/raw` mounted at `/corpus`). The api
  peaked at 173 MB (`memory.peak` in its cgroup), Chroma at 106 MB with 239 chunks, Redis at 13 MB.
- **`kubectl top pods`** on a cluster (`docs/evidence/kubectl-top.txt`, kind + metrics-server):
  api 69-70Mi per replica, chroma 18Mi, redis 3Mi, ui 2Mi on the fixture corpus. That is far
  under the api's 192Mi request, so the request could be lowered. The fixture re-index ran in
  24 s, faster than metrics-server's sampling window, so the indexer's figure is the Docker peak
  on the real corpus above.
- **Limit:** `memory: 1536Mi` (`k8s/base/indexer.yaml:84`), request 512Mi. Margin: 1536 / 978
  = **57% headroom**. The api limit is 512Mi against a 173 MB peak.
- **Exit code when it is wrong:** **137**, SIGKILL from the OOM killer, `OOMKilled` in
  `kubectl describe pod`. The Job restarts the pod (`restartPolicy: OnFailure`) until
  `backoffLimit: 3`, so a too-low limit shows up as `CrashLoopBackOff` with exit 137. We hit
  exit 137 ourselves: Docker Desktop's VM had only 1.6 GB, and running two indexers and an image
  build at once killed the build with 137.

## 5. recall@5 by question type: where is it worst, and why?

At the shipped `top_k=5`, recall@5 is 1.0 for every type (`eval/results.json`). The differences
show at tighter k, which is where an embedding-only retriever would be:

| top_k | ordinary | version | exact | injection |
| --- | --- | --- | --- | --- |
| 1 | 0.80 | **0.33** | 1.00 | 1.00 |
| 3 | 0.90 | 1.00 | 1.00 | 1.00 |
| 5 | 1.00 | 1.00 | 1.00 | 1.00 |

- **Worst: version-sensitive questions at k=1 (0.33).** The 2026 handbook, the 2026 Prospectus
  and the Student Handbook state overlapping rules, so the right section is often second or third.
  The superseded filter keeps the 2023 text out; it does not decide between current documents.
- **Exact terms are perfect only because of hybrid retrieval.** "What does rule 4.18 say?" has a
  top-1 *embedding* similarity of 0.591, below the 0.70 floor. Pure embeddings would have declined
  it. Embeddings encode meaning, and "4.18" carries almost none: it embeds close to "4.17" and
  "1.18". The lexical `$contains` query (`api/app/retrieval/chroma.py`) finds the chunk that
  literally contains "4.18".
- **The lecture technique:** hybrid retrieval, lexical (BM25 or exact match) fused with dense
  vectors. Next step: re-rank the fused list with a cross-encoder.

## 6. EMBED_MODEL changed on the API only: what does your system do?

Change `EMBED_MODEL` in the ConfigMap, restart only the api
(`kubectl rollout restart deployment/api -n rahbar`):

1. At startup, `startup_pin_check` (`api/app/services/readiness.py:66`, called from
   `api/app/main.py:42`) reads the collection metadata (`embed_model: nomic-embed-text`), finds
   that it differs from the new value, and logs `EMBEDDING PIN CONFLICT` with both names and the
   dimension.
2. Every `/readyz` (`readiness.py:30`) returns **503**, naming the conflict, e.g.
   `"embed_model": "embedding model mismatch: index built with 'nomic-embed-text', API pinned to
   EMBED_MODEL='mxbai-embed-large' ..."`.
3. With `maxUnavailable: 0`, the new pods sit at `0/1 READY`, the rollout stalls, and **the old
   pods keep serving**. Users see no change. `kubectl rollout undo` or restoring the ConfigMap
   ends it.
4. Belt and braces: if a mismatched pod did serve, `ChromaRetriever.retrieve`
   (`api/app/retrieval/chroma.py:86-88`) refuses a query vector whose dimension differs from the
   index's.

**Without the guardrail:** if the new model has the same dimension (768), Chroma happily compares
vectors from two unrelated spaces. Retrieval returns confident nonsense, the floor passes or fails
at random, and nothing errors anywhere. If the dimension differs, every question 500s. The silent
case is the dangerous one, and the guardrail turns it into a loud, safe one.

## 7. The failure that cost us more than an hour

- **Symptom:** chunks from the 2026 Academic Rules Handbook were nonsense. Clause 1.9 sat next
  to clause 1.14 on the same line ("1.9 A theory course is normally assigned 2 to 4 credit hours,
  d) For pre-planned activities (conferences, etc.) during"). The section labels were wrong, and
  the handbook produced 94,748 characters where the page count suggested about 60,000.
- **What we wrongly believed first:** that the handbook was a two-column layout. We wrote
  `column_splits()`, a gutter detector over character x-positions, and then the left half of
  every page disappeared (characters dropped to 62,987). We tried widening the gutter search,
  and nothing changed.
- **What told us the truth:** printing the character x-range of one page:
  `print(min(c[0] for c in chars), max(c[1] for c in chars))` gave **`-376.49 376.56`** for a page
  whose `page.bbox` is `(0, 0, 419.5, 595.3)`. The PDF is a 2-up imposition. Each page object also
  carries its neighbour page's text at *negative* x, outside the visible box, and pdfplumber
  happily extracted it. One line fixed it: `page = page.within_bbox(page.bbox)` in
  `indexer/pipeline/extract.py`. The gutter detector stayed, because the three-column Prospectus
  genuinely needs it. Lesson: inspect the raw coordinates before writing a heuristic about the
  layout.

### Also: chroma-0 in CrashLoopBackOff on the first CI cluster

Chroma ran locally but crash-looped on kind. That was two causes in sequence, each found with
one command:

1. **`unable to open database file`.** Reproduced locally with the pod's exact security
   settings (`--user 1000 --read-only --cap-drop ALL` on a root-owned volume). The kind and
   minikube volume provisioners ignore `fsGroup`, so `/data` stayed root-owned. Fix: a
   `fix-permissions` init container that only chowns `/data`, with only `CAP_CHOWN`.
2. **`Error loading config: invalid type: found string "tcp://10.96.0.10:8000", expected u16
   for key "PORT" in CHROMA_ environment variable(s)`.** Kubernetes injects service-link
   variables for every Service, and our Service is named `chroma`, so the pod got
   `CHROMA_PORT=tcp://...`. Chroma reads `CHROMA_*` as its own config. Fix:
   `enableServiceLinks: false` on every pod.

The same CI run also showed the API crashing at startup when Chroma was down, because
`chromadb.HttpClient()` connects in its constructor. Now the client is created lazily and a down
Chroma means `/readyz` 503, never a dead pod (`api/app/retrieval/chroma.py`, `client` property).
