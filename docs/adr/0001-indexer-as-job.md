# ADR 0001: The indexer is a Kubernetes Job, the API only reads

## Status
Accepted · 8 November 2026

## Context
The lab code indexed the corpus inside the FastAPI process at startup. On the cluster the API runs
as 3 replicas behind an HPA that can go to 8, and Chroma has one volume. If indexing stays in API
startup:

- **Three writers race one volume.** Three pods each delete the collection and add chunks halfway
  through different documents. The result is an index that no single document produced: duplicate
  ids, or a count that depends on which pod finished last.
- **Every restart re-indexes.** A rolling update, an OOMKill, a node drain or the HPA adding a pod
  each pay roughly 3 minutes of OCR and embedding (our measured Job time, 182 s), and peak memory
  near 1 GB. Our API needs about 170 MB.
- **Readiness becomes a lie.** Either the pod reports ready before the index exists and serves
  empty retrievals, or it takes minutes to become ready. Then the startup probe (60 s budget)
  kills it halfway through, and a rollout swaps three working pods for three that are still
  chunking PDFs.
- **Re-indexing needs a redeploy.** New documents become a rebuild and a rollout, which is the
  "Friday failure".

## Decision
- Indexing is a **Job** (`k8s/base/indexer.yaml`) with `restartPolicy: OnFailure` and
  `backoffLimit: 3`, plus a weekly **CronJob** `reindex` with the same image and arguments and
  `concurrencyPolicy: Forbid`.
- The Job is the **only** code that writes to Chroma (`indexer/pipeline/store.py`). The API has no
  write call anywhere.
- Re-indexing is one command with no redeploy:
  `kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar`.
- The API's readiness probe (`/readyz`) returns 503 until the collection exists, is non-empty and
  was built with the same `EMBED_MODEL`. A pod is withheld from the Service until there is
  something correct to retrieve.
- **What happens to the old index while the Job runs:** build-then-swap. The Job writes
  `rahbar-staging`, checks the count, then deletes `rahbar` and renames staging to `rahbar`. The
  API keeps serving the old index for the whole run. The only gap is the milliseconds between
  delete and rename, during which `/readyz` may report not-ready once; nothing is restarted.
  The new `index_id` invalidates the semantic cache (ADR 0003).

## Options considered
- **Index in API startup:** rejected for the four reasons above.
- **An init container on the API:** still runs per pod, so it has the same race and the same cost
  per restart.
- **A leader-elected indexer inside the API:** solves the race but not the cost or the redeploy,
  and it adds RBAC and lease code for no gain.
- **Delete-then-rebuild in place:** simpler, but every re-index empties the live index for 3
  minutes, so every API pod goes not-ready and users get 503s.

## Consequences
- Easier: re-index without a redeploy; a failed Job leaves the live index intact; the API stays
  small (memory limit 512 Mi vs 1.5 Gi for the Job).
- Harder: the corpus must reach the Job (a PVC loaded by `make corpus-load`), and first apply
  needs ordering. The Job's init containers wait for the corpus and for Chroma.
- Watch for: two Jobs at once (a manual Job during the CronJob). `concurrencyPolicy` only guards
  the CronJob, so the staging name makes the second Job's delete-and-recreate visible in the logs.
