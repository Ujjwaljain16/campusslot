#!/usr/bin/env bash
# Install the CloudNativePG operator, and optionally what point-in-time recovery needs.
#
#   scripts/install-cnpg.sh                    # the operator: a primary, replicas and automatic failover
#   WITH_BACKUP=1 scripts/install-cnpg.sh      # also cert-manager and the Barman Cloud plugin (WAL archiving and backups)
#
# Run this BEFORE deploying the application with postgres.operator.enabled=true, because the Cluster custom
# resource only exists once the operator's CRDs are installed. For the backups the object store comes next:
# scripts/install-objectstore.sh.
set -euo pipefail

CNPG_CHART_VERSION="${CNPG_CHART_VERSION:-0.29.1}"             # CloudNativePG 1.30.1
CERT_MANAGER_VERSION="${CERT_MANAGER_VERSION:-v1.21.2}"
BARMAN_PLUGIN_VERSION="${BARMAN_PLUGIN_VERSION:-v0.15.1}"      # needs CloudNativePG 1.26 or newer
WITH_BACKUP="${WITH_BACKUP:-0}"

helm repo add cnpg https://cloudnative-pg.github.io/charts >/dev/null 2>&1 || true
helm repo update cnpg >/dev/null

helm upgrade --install cnpg cnpg/cloudnative-pg \
  --namespace cnpg-system --create-namespace \
  --version "$CNPG_CHART_VERSION" \
  --wait --timeout 5m

if [ "$WITH_BACKUP" = "1" ]; then
  # The plugin's webhooks and its connection to the operator are secured with certificates that cert-manager issues.
  helm repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || true
  helm repo update jetstack >/dev/null
  helm upgrade --install cert-manager jetstack/cert-manager \
    --namespace cert-manager --create-namespace \
    --version "$CERT_MANAGER_VERSION" \
    --set crds.enabled=true \
    --wait --timeout 5m

  kubectl apply -f "https://github.com/cloudnative-pg/plugin-barman-cloud/releases/download/${BARMAN_PLUGIN_VERSION}/manifest.yaml"
  kubectl rollout status deployment/barman-cloud -n cnpg-system --timeout=180s \
    || kubectl get deploy -n cnpg-system
fi

kubectl get pods -n cnpg-system
