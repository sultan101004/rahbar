# Evidence on minikube (9 Nov 2026)

minikube v1.35.0, docker driver on Docker Desktop (4 GB VM), `--cni=calico`, addons
metrics-server and ingress; manifests applied with `kubectl apply -k k8s/overlays/dev-docker-desktop`
(generation via Groq `openai/gpt-oss-120b` with the key in the `rahbar-secret` Secret; embeddings
`nomic-embed-text` from the laptop's Ollama). The Ingress was port-forwarded to `localhost:8080`
because Docker Desktop's VM hides the minikube IP from the host.

| File | Result |
| --- | --- |
| `kubectl-top-first-index.txt` | first indexer Job on the real corpus (6 docs, 23 OCR pages): **peak 1025Mi, 1002m CPU**; Job Complete in 6m28s; 240 chunks. api pods sat at 0/1 READY until the index existed. |
| `ask-through-ingress.txt` | cited answers through the Ingress; the hostel question declined |
| `networkpolicy.txt` | Calico enforces it: ui → chroma and ui → redis **BLOCKED**, api → chroma OK |
| `kubectl-top.txt` | re-index with no redeploy (`kubectl create job --from=cronjob/reindex`): peak 624Mi |
| `kubectl-get-hpa.txt` | `cpu: 4%/70%`, min 3, max 8 |
| `kubectl-get-endpoints.txt` | **finding:** `kubectl scale --replicas=4` was undone by the HPA ("New size: 3; reason: All metrics below target"); raising `minReplicas` to 4 gave 4 Ready pods and 4 endpoints |
| `rollout-undo.txt` | `set image rahbar-api:v2` → rolled out → `rollout undo` → rolled out |
| `delete-pod.txt` | 30 questions through the Ingress while an api pod was deleted: **30/30 HTTP 200** |
| `embed-pin-cluster.txt` | EMBED_MODEL changed: new pod **0/1 READY**, `EMBEDDING PIN CONFLICT`, `/readyz` 503, Ingress still 200; restored |
