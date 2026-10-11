#!/usr/bin/env bash
# Install the Argo Rollouts controller, which runs canary releases (rollout.enabled=true in the chart).
#
#   scripts/install-rollouts.sh
#
# Run this BEFORE deploying the application with rollout.enabled=true, because the Rollout and
# AnalysisTemplate custom resources only exist once the controller's CRDs are installed. The Prometheus
# stack (scripts/install-monitoring.sh) comes first as well, because the analysis reads from it.
set -euo pipefail

CHART_VERSION="${CHART_VERSION:-2.43.6}"   # Argo Rollouts v1.10.0

helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update argo >/dev/null

helm upgrade --install argo-rollouts argo/argo-rollouts \
  --namespace argo-rollouts --create-namespace \
  --version "$CHART_VERSION" \
  --set controller.replicas=1 \
  --set dashboard.enabled=false \
  --set controller.metrics.enabled=true \
  --set controller.metrics.serviceMonitor.enabled=true \
  --wait --timeout 5m

kubectl get pods -n argo-rollouts
