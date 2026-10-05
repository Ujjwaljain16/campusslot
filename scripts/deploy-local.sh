#!/usr/bin/env bash
# Deploy the CampusSlot Helm chart to the local Minikube cluster with the images that the
# GitHub Actions pipeline built for one commit.
#
#   scripts/deploy-local.sh <commit-sha>
#
# The images are pulled from GHCR (ghcr.io/ujjwaljain16/campusslot-{backend,frontend}:<sha>),
# so what runs locally is byte for byte what the pipeline scanned and pushed.
set -euo pipefail

SHA="${1:?usage: deploy-local.sh <commit-sha>}"
NAMESPACE="${NAMESPACE:-campusslot}"
RELEASE="${RELEASE:-campusslot}"
CHART="$(cd "$(dirname "$0")/.." && pwd)/helm/campusslot"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

kubectl apply -f "$ROOT/k8s/namespace.yaml"

# The database password is fixed when PostgreSQL first initialises its volume, so an upgrade
# must reuse it. Only a first install generates a new random one.
SECRET="${RELEASE}-campusslot-database"
if kubectl get secret "$SECRET" -n "$NAMESPACE" >/dev/null 2>&1; then
  PASSWORD="$(kubectl get secret "$SECRET" -n "$NAMESPACE" -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)"
  echo "Reusing the existing database password from secret $SECRET"
else
  PASSWORD="$(openssl rand -hex 16)"
  echo "First install: generated a random database password (stored only in the cluster Secret)"
fi

helm upgrade --install "$RELEASE" "$CHART" \
  --namespace "$NAMESPACE" \
  -f "$CHART/values-dev.yaml" \
  --set backend.image.tag="$SHA" \
  --set frontend.image.tag="$SHA" \
  --set-string postgres.password="$PASSWORD" \
  --atomic --timeout 6m

kubectl get pods,svc,ingress,hpa -n "$NAMESPACE"
