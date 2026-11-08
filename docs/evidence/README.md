# Evidence

Cluster transcripts were captured by `.github/workflows/evidence.yml` (run
https://github.com/sultan101004/rahbar/actions/runs/42511526605) on an ephemeral **kind**
cluster with **Calico** (NetworkPolicy enforced) and metrics-server, deploying the same
manifests on the fixture corpus. Our laptop's Docker VM has 1.6 GB, too little for minikube,
so this stands in for the minikube runs; every file is a transcript of real commands.

| File | What it shows |
| --- | --- |
| `networkpolicy.txt` | 7 policies; **ui → chroma and ui → redis time out (blocked)**, api → chroma answers |
| `kubectl-top.txt` | `kubectl top pods --containers` sampled every 5 s during `kubectl create job --from=cronjob/reindex`: api ~70Mi, chroma ~18Mi, redis 3Mi, ui 2Mi. The fixture re-index finished in 24 s, before metrics-server sampled it; the indexer's peak (978 MiB on the real corpus) is measured with Docker in `local-resource-measurements.txt`. |
| `kubectl-get-hpa.txt` | HPA `cpu: 6%/70%`, min 3, max 8: a real percentage, not `<unknown>` |
| `kubectl-get-endpoints.txt` | `endpoints/api` with 3 IPs, then 4 after `kubectl scale --replicas=4`; the Service was not touched |
| `rollout-undo.txt` | `kubectl set image` → `rollout status` → `rollout undo` → `rollout status`, with history |
| `delete-pod.txt` | an api pod deleted while 30 questions go through the Ingress: **30/30 HTTP 200** |
| `embed-pin-cluster.txt` | `EMBED_MODEL` changed in the ConfigMap + api restarted: new pod **0/1 READY**, `EMBEDDING PIN CONFLICT` log, `/readyz` 503, old pods still serve 200; then restored |
| `final-state.txt` | `kubectl get all,pvc,ingress,networkpolicy` at the end |
| `cd-run.txt`, `kubectl-get-endpoints-kind.txt` | Green cd.yml run: GHCR images by SHA, rollout, smoke test through the Ingress |
| `branch-protection.json` | `main` requires the 6 CI checks and 1 approval; no force pushes |
| `readyz-pin-mismatch.txt` | the same guardrail on the real 240-chunk index (Docker) |
| `local-resource-measurements.txt` | Docker peak memory on the real corpus, used to size requests/limits |
| `trivy-before-fix.txt` | HIGH CVEs that made us move to FastAPI 0.160/Starlette 1.8 and a trixie base |
| `fixture-gate-fail-floor-0.55.json` | the eval gate failing (abstention 0%) when the floor was 0.55 |
| `ui-screenshot.jpg` | the chat UI answering with a citation |
| `blocked-merge.png`, `green-merge.png` | **TODO**: screenshots of a gate-failing PR with merge blocked, then a green one |
