#!/usr/bin/env bash
# Idempotent: build images -> kind load -> apply manifests -> wait for ready.
# Re-run any time after editing code; it will rebuild + roll the relevant Deployment.
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-ims}"
NAMESPACE="${NAMESPACE:-ims}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> repo root: $REPO_ROOT"
echo "==> cluster:   $CLUSTER_NAME"
echo "==> namespace: $NAMESPACE"

# 1. Cluster.
if ! kind get clusters | grep -qx "$CLUSTER_NAME"; then
  echo "==> creating kind cluster..."
  kind create cluster --name "$CLUSTER_NAME" --config k8s/kind-cluster.yaml
else
  echo "==> kind cluster already exists; skipping create"
fi
kubectl config use-context "kind-${CLUSTER_NAME}" >/dev/null

# 2. Build images locally.
echo "==> building backend image..."
docker build -t ims-backend:local backend/

echo "==> building dashboard image..."
docker build -t ims-dashboard:local dashboard/

# 3. Load into the kind cluster.
echo "==> loading images into kind..."
kind load docker-image ims-backend:local   --name "$CLUSTER_NAME"
kind load docker-image ims-dashboard:local --name "$CLUSTER_NAME"

# 4. Apply manifests.
echo "==> applying namespace + configs..."
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-secret.yaml
kubectl apply -f k8s/02-configmap.yaml

# init-db SQL is generated from the existing init-db/01_schema.sql so we never duplicate it.
echo "==> generating init-db ConfigMap from init-db/01_schema.sql..."
kubectl create configmap ims-initdb \
    --from-file=01_schema.sql=init-db/01_schema.sql \
    -n "$NAMESPACE" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "==> applying datastores..."
kubectl apply -f k8s/03-postgres.yaml
kubectl apply -f k8s/04-mongo.yaml
kubectl apply -f k8s/05-redis.yaml

echo "==> applying app workloads..."
kubectl apply -f k8s/06-backend.yaml
kubectl apply -f k8s/07-dashboard.yaml

# Force a rollout so an updated image gets picked up by the existing pod.
kubectl -n "$NAMESPACE" rollout restart deployment/backend deployment/dashboard >/dev/null

# 5. Wait for everything to be ready.
echo "==> waiting for datastores..."
kubectl -n "$NAMESPACE" rollout status statefulset/postgres --timeout=180s
kubectl -n "$NAMESPACE" rollout status statefulset/mongo    --timeout=180s
kubectl -n "$NAMESPACE" rollout status deployment/redis     --timeout=120s

echo "==> waiting for backend + dashboard..."
kubectl -n "$NAMESPACE" rollout status deployment/backend   --timeout=180s
kubectl -n "$NAMESPACE" rollout status deployment/dashboard --timeout=180s

echo
echo "==> done."
echo "    Dashboard:    http://localhost:8501"
echo "    FastAPI docs: http://localhost:8000/docs"
echo
echo "Useful commands:"
echo "    kubectl -n $NAMESPACE get pods,svc"
echo "    kubectl -n $NAMESPACE logs -f deployment/backend"
echo "    kubectl -n $NAMESPACE exec -it statefulset/postgres -- psql -U ims -d ims"
echo
echo "To run the load test (Locust):"
echo "    bash k8s/load.sh         # apply locust manifest, then open http://localhost:8089"
