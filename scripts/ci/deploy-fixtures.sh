#!/usr/bin/env bash
# Deploy the ci overlay with the given images, index the fixture corpus with the indexer
# Job, and wait until the api rollout is complete. Usage:
#   scripts/ci/deploy-fixtures.sh <api-image> <ui-image> <indexer-image>
set -euo pipefail
API_IMAGE=$1 UI_IMAGE=$2 INDEXER_IMAGE=$3
: "${OLLAMA_IP:?run scripts/ci/kind-up.sh first}"
NS=rahbar
WORK=$(mktemp -d)
cp -r k8s "$WORK/"
(
  cd "$WORK/k8s/overlays/ci"
  kustomize edit set image "rahbar-api=$API_IMAGE" "rahbar-ui=$UI_IMAGE" "rahbar-indexer=$INDEXER_IMAGE"
)
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap rahbar-corpus-fixtures -n "$NS" \
  --from-file=eval/fixtures/academic-rules-2023.md \
  --from-file=eval/fixtures/academic-rules-2026.md \
  --from-file=eval/fixtures/fees-2026.md \
  --dry-run=client -o yaml | kubectl apply -f -
kustomize build "$WORK/k8s/overlays/ci" | sed "s/OLLAMA_HOST_IP/$OLLAMA_IP/g" | kubectl apply -f -

kubectl rollout status statefulset/chroma -n "$NS" --timeout=300s
if ! kubectl wait --for=condition=complete job/indexer -n "$NS" --timeout=600s; then
  kubectl describe job/indexer -n "$NS"; kubectl logs -n "$NS" job/indexer --all-containers || true
  exit 1
fi
kubectl logs -n "$NS" job/indexer | tail -5
if ! kubectl rollout status deployment/api -n "$NS" --timeout=300s; then
  kubectl get pods -n "$NS"; kubectl describe pods -n "$NS" -l app=api | tail -40
  kubectl logs -n "$NS" -l app=api --tail=50 || true
  exit 1
fi
kubectl rollout status deployment/ui -n "$NS" --timeout=180s
kubectl get pods,svc,ingress,endpoints -n "$NS"
