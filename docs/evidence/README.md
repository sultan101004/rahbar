# Evidence

| File | What it shows | Status |
| --- | --- | --- |
| `local-resource-measurements.txt` | Peak memory of indexer/api/chroma/redis from Docker, used to size requests/limits | captured locally |
| `trivy-before-fix.txt` | The HIGH CVEs that made us bump FastAPI/Starlette and the base image | captured locally |
| `fixture-gate-fail-floor-0.55.json` | The eval gate failing (abstention 0%) when the floor was 0.55 | captured locally |
| `readyz-pin-mismatch.txt` | `/readyz` returning 503 and the `EMBEDDING PIN CONFLICT` log when EMBED_MODEL changes on the api only | captured locally (Docker) |
| `kubectl-top.txt` | `kubectl top pods -n rahbar --containers` during a re-index | **TODO on minikube** |
| `kubectl-get-endpoints.txt` | `kubectl get endpoints api -n rahbar` listing 3+ IPs after scaling | **TODO on minikube** |
| `kubectl-get-hpa.txt` | `kubectl get hpa -n rahbar` with a real CPU percentage, not `<unknown>` | **TODO on minikube** |
| `branch-protection.png` | `main` protection: PR required, CI required, one approval | **TODO on GitHub** |
| `blocked-merge.png`, `green-merge.png` | A PR that fails the eval gate (greyed-out merge), then the fix | **TODO on GitHub** |
| `rollout-undo.txt` | `kubectl set image`, `rollout status`, `rollout undo` | **TODO on minikube** |
