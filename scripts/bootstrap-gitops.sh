#!/usr/bin/env bash
# Put a cluster under GitOps control with Argo CD.
#
#   scripts/bootstrap-gitops.sh
#
# Steps: namespace, the database Secret (random password, never committed), Argo CD itself, and
# finally the Argo CD Application that points at this repository.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARGOCD_VERSION="${ARGOCD_VERSION:-10.9.6}"

kubectl apply -f "$ROOT/k8s/namespace.yaml"

# Created only once: PostgreSQL fixes the password when its volume is first initialised.
if ! kubectl get secret campusslot-db -n campusslot >/dev/null 2>&1; then
  PASSWORD="$(openssl rand -hex 16)"
  kubectl create secret generic campusslot-db -n campusslot \
    --from-literal=POSTGRES_PASSWORD="$PASSWORD" \
    --from-literal=DATABASE_URL="postgresql+psycopg://campusslot:${PASSWORD}@campusslot-postgres:5432/campusslot"
  echo "Created secret campusslot-db with a random password"
else
  echo "Secret campusslot-db already exists, keeping it"
fi

helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update >/dev/null
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd --create-namespace --version "$ARGOCD_VERSION" \
  -f "$ROOT/gitops/argocd-values.yaml" --wait --timeout 8m

kubectl apply -f "$ROOT/gitops/application.yaml"
echo
echo "Argo CD UI:  kubectl port-forward -n argocd svc/argocd-server 8081:80   (user: admin)"
echo "Password:    kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath='{.data.password}' | base64 -d"
