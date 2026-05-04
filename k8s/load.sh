#!/usr/bin/env bash
# Bring up the Locust load tester (separate from deploy.sh because it's optional).
set -euo pipefail

NAMESPACE="${NAMESPACE:-ims}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> creating locustfile ConfigMap..."
kubectl create configmap ims-locustfile \
    --from-file=locustfile.py=scripts/locustfile.py \
    -n "$NAMESPACE" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "==> applying locust workload..."
kubectl apply -f k8s/08-locust.yaml
kubectl -n "$NAMESPACE" rollout restart deployment/locust >/dev/null
kubectl -n "$NAMESPACE" rollout status  deployment/locust --timeout=120s

echo
echo "==> Locust UI: http://localhost:8089"
echo "    in the UI: users=1000, spawn rate=200, host=http://backend:8000"
