#!/usr/bin/env bash
# Bring up the ephemeral CI cluster: kind + ingress-nginx + Ollama (embeddings only) as a
# container on the kind network, so pods reach it by IP. Prints OLLAMA_IP to $GITHUB_ENV.
set -euo pipefail
CLUSTER=${CLUSTER:-rahbar}
OLLAMA_IMAGE=${OLLAMA_IMAGE:-ollama/ollama:0.6.8}
EMBED_MODEL=${EMBED_MODEL:-nomic-embed-text}

kind create cluster --name "$CLUSTER" --config "${KIND_CONFIG:-k8s/kind/kind-config.yaml}" --wait "${KIND_WAIT:-120s}"
if [ -n "${CNI_MANIFEST:-}" ]; then   # evidence cluster: Calico, so NetworkPolicy is enforced
  kubectl apply -f "$CNI_MANIFEST"
  kubectl wait -n kube-system --for=condition=Ready pod -l k8s-app=calico-node --timeout=300s
fi
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.1/deploy/static/provider/kind/deploy.yaml

docker run -d --name ollama --network kind "$OLLAMA_IMAGE"
for _ in $(seq 1 30); do docker exec ollama ollama list >/dev/null 2>&1 && break; sleep 2; done
docker exec ollama ollama pull "$EMBED_MODEL"
OLLAMA_IP=$(docker inspect -f '{{(index .NetworkSettings.Networks "kind").IPAddress}}' ollama)
echo "ollama on the kind network at $OLLAMA_IP"
echo "OLLAMA_IP=$OLLAMA_IP" >> "${GITHUB_ENV:-/dev/null}"

kubectl wait -n ingress-nginx --for=condition=Ready pod -l app.kubernetes.io/component=controller --timeout=180s
