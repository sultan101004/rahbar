# Evidence

| File | What it shows | Status |
| --- | --- | --- |
| `local-resource-measurements.txt` | Peak memory of indexer/api/chroma/redis from Docker, used to size requests/limits | captured locally |
| `trivy-before-fix.txt` | The HIGH CVEs that made us bump FastAPI/Starlette and the base image | captured locally |
| `fixture-gate-fail-floor-0.55.json` | The eval gate failing (abstention 0%) when the floor was 0.55 | captured locally |
| `readyz-pin-mismatch.txt` | `/readyz` returning 503 and the `EMBEDDING PIN CONFLICT` log when EMBED_MODEL changes on the api only | captured locally (Docker) |
| `kubectl-top.txt` | `kubectl top pods -n rahbar --containers` during a re-index | **TODO on minikube** |
| `kubectl-get-endpoints-kind.txt` | Real cluster (kind, in cd.yml): `endpoints/api` lists 3 pod IPs, indexer Job Complete, chroma StatefulSet Running | captured in CD |
| `cd-run.txt` | Green cd.yml run: images `ghcr.io/sultan101004/rahbar-*:<sha>` pulled, rollout complete, smoke test through the Ingress passed | captured in CD |
| `branch-protection.json` | `main` requires the 6 CI checks and 1 approval; force pushes off | captured from GitHub API |
| `ui-screenshot.jpg` | The chat UI answering with a citation | captured locally |
| `kubectl get endpoints` on minikube after `kubectl scale --replicas=4` | | **TODO on minikube** |
| `kubectl-get-hpa.txt` | `kubectl get hpa -n rahbar` with a real CPU percentage, not `<unknown>` | **TODO on minikube** |
| `blocked-merge.png`, `green-merge.png` | A PR that fails the eval gate (greyed-out merge), then the fix | **TODO on GitHub** |
| `rollout-undo.txt` | `kubectl set image`, `rollout status`, `rollout undo` | **TODO on minikube** |
