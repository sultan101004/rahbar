#!/usr/bin/env bash
# Capture the section 4 evidence from a live cluster into $OUT (one file per demo).
# Runs after scripts/ci/kind-up.sh + deploy-fixtures.sh. Every command is echoed with its
# output, so each file is a transcript, not a summary.
set -uo pipefail
NS=rahbar
OUT=${OUT:-evidence-out}
mkdir -p "$OUT"
H="Host: rahbar.local"
BASE=${BASE:-http://localhost}
run() { echo "\$ $*"; eval "$@" 2>&1; echo; }
ask() { curl -s -o /dev/null -w '%{http_code}' -m 60 -H "$H" -H 'Content-Type: application/json' \
          -X POST "$BASE/api/ask" -d "{\"question\": \"$1\"}"; }
stamp() { echo "# $1"; echo "# captured $(date -u +%Y-%m-%dT%H:%M:%SZ) on ${CLUSTER_DESC:-an ephemeral kind cluster (Calico CNI, metrics-server) in GitHub Actions}, commit ${GITHUB_SHA:-$(git rev-parse --short HEAD 2>/dev/null)}"; echo; }

# ------------------------------------------------------------- NetworkPolicy (Calico)
{
  stamp "NetworkPolicy: deny by default; the ui pod must not reach chroma, the api pod must"
  run kubectl get networkpolicy -n $NS
  UI=$(kubectl get pod -n $NS -l app=ui -o jsonpath='{.items[0].metadata.name}')
  API=$(kubectl get pod -n $NS -l app=api -o jsonpath='{.items[0].metadata.name}')
  run kubectl exec -n $NS "$UI" -- wget -q -O- -T 5 http://chroma:8000/api/v2/heartbeat '||' echo "BLOCKED: ui cannot reach chroma"
  run kubectl exec -n $NS "$API" -- python -c "\"import urllib.request;print(urllib.request.urlopen('http://chroma:8000/api/v2/heartbeat',timeout=5).read().decode())\""
  run kubectl exec -n $NS "$UI" -- wget -q -O- -T 5 http://redis:6379 '||' echo "BLOCKED: ui cannot reach redis"
} > "$OUT/networkpolicy.txt"

# ------------------------------------------------------------- kubectl top during a re-index
{
  stamp "kubectl top pods --containers, sampled every 5 s during a re-index (kubectl create job --from=cronjob/reindex)"
  run kubectl create job --from=cronjob/reindex manual-reindex-1 -n $NS
  for i in $(seq 1 24); do
    echo "--- sample $i"; kubectl top pods -n $NS --containers 2>&1
    s=$(kubectl get job manual-reindex-1 -n $NS -o jsonpath='{.status.succeeded}')
    [ "$s" = 1 ] && [ "$i" -ge 6 ] && break
    sleep 5
  done
  echo; run kubectl get jobs -n $NS
  run kubectl logs -n $NS job/manual-reindex-1 '|' tail -3
} > "$OUT/kubectl-top.txt"

# ------------------------------------------------------------- HPA
{
  stamp "HPA reads a real CPU percentage (requests.cpu set, metrics-server on), not <unknown>"
  for i in $(seq 1 24); do kubectl get hpa api -n $NS | grep -q unknown || break; sleep 5; done
  run kubectl get hpa -n $NS
  run kubectl describe hpa api -n $NS '|' sed -n "'/Metrics/,/Events/p'"
} > "$OUT/kubectl-get-hpa.txt"

# ------------------------------------------------------------- scale + endpoints
{
  stamp "Scale to 4: the Service's selector finds the new pod by label; the Service is not touched"
  run kubectl get endpoints api -n $NS
  run kubectl scale deployment/api -n $NS --replicas=4
  run kubectl rollout status deployment/api -n $NS --timeout=180s
  run kubectl wait --for=condition=Ready pod -l app=api -n $NS --timeout=120s
  run kubectl get endpoints api -n $NS
  run kubectl get pods -n $NS -l app=api -o wide
} > "$OUT/kubectl-get-endpoints.txt"

# ------------------------------------------------------------- rollout + undo
{
  stamp "Rollout with maxSurge 1 / maxUnavailable 0, then rollout undo"
  run kubectl rollout history deployment/api -n $NS
  run kubectl set image deployment/api -n $NS api=${ROLLOUT_IMAGE:-rahbar-api:ci-v2}
  run kubectl annotate deployment/api -n $NS kubernetes.io/change-cause="ship ${ROLLOUT_IMAGE:-rahbar-api:ci-v2}" --overwrite
  run kubectl rollout status deployment/api -n $NS --timeout=300s
  run kubectl get deployment api -n $NS -o wide
  run kubectl rollout undo deployment/api -n $NS
  run kubectl rollout status deployment/api -n $NS --timeout=300s
  run kubectl get deployment api -n $NS -o wide
  run kubectl rollout history deployment/api -n $NS
} > "$OUT/rollout-undo.txt"

# ------------------------------------------------------------- delete a pod, nothing breaks
{
  stamp "Delete an api pod while questions keep arriving through the Ingress"
  codes=""
  for i in $(seq 1 30); do
    [ "$i" = 8 ] && { P=$(kubectl get pod -n $NS -l app=api -o jsonpath='{.items[0].metadata.name}'); echo "\$ kubectl delete pod $P -n $NS --wait=false"; kubectl delete pod "$P" -n $NS --wait=false; }
    c=$(ask "What is the fee per credit hour for BS?"); codes="$codes $c"; sleep 1
  done
  echo; echo "HTTP status of 30 questions asked during the deletion:$codes"
  echo "non-200 responses: $(echo $codes | tr ' ' '\n' | grep -vc '^200$')"
  echo; run kubectl get pods -n $NS -l app=api
} > "$OUT/delete-pod.txt"

# ------------------------------------------------------------- embedding pin on the cluster
{
  stamp "Change EMBED_MODEL in the ConfigMap, restart only the api: the new pod stays 0/1 READY and logs the conflict; the old pods keep serving"
  run kubectl patch configmap rahbar-config -n $NS --type merge -p "'{\"data\":{\"EMBED_MODEL\":\"mxbai-embed-large\"}}'"
  run kubectl rollout restart deployment/api -n $NS
  sleep 60
  run kubectl get pods -n $NS -l app=api
  NEW=$(kubectl get pods -n $NS -l app=api --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}')
  run kubectl logs -n $NS "$NEW" '|' grep "'PIN CONFLICT'"
  run kubectl exec -n $NS "$NEW" -- python -c "\"import urllib.request,urllib.error
try: urllib.request.urlopen('http://localhost:8000/readyz')
except urllib.error.HTTPError as e: print(e.code, e.read().decode())\""
  echo "still serving through the Ingress: HTTP $(ask 'What is the fee per credit hour for BS?')"; echo
  run kubectl patch configmap rahbar-config -n $NS --type merge -p "'{\"data\":{\"EMBED_MODEL\":\"nomic-embed-text\"}}'"
  run kubectl rollout restart deployment/api -n $NS
  run kubectl rollout status deployment/api -n $NS --timeout=300s
} > "$OUT/embed-pin-cluster.txt"

{
  stamp "Final state"
  run kubectl get all,pvc,ingress,networkpolicy -n $NS
} > "$OUT/final-state.txt"
echo "evidence written to $OUT:"; ls -la "$OUT"
