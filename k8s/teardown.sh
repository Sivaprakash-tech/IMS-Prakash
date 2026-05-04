#!/usr/bin/env bash
# Tear down the kind cluster (also removes all workloads + PVCs since they live in the cluster's docker volume).
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-ims}"

if kind get clusters | grep -qx "$CLUSTER_NAME"; then
  echo "==> deleting kind cluster '$CLUSTER_NAME'..."
  kind delete cluster --name "$CLUSTER_NAME"
else
  echo "==> no kind cluster named '$CLUSTER_NAME'; nothing to do"
fi
