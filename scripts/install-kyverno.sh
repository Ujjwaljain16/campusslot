#!/usr/bin/env bash
# Install Kyverno with only the admission controller, which is what image verification needs.
#
#   scripts/install-kyverno.sh
#
# The background, cleanup and reports controllers are switched off. They scan and report on resources that
# already exist, which this project does not use, and each one costs memory on a laptop cluster.
set -euo pipefail

CHART_VERSION="${CHART_VERSION:-3.9.1}"   # Kyverno v1.19.1

helm repo add kyverno https://kyverno.github.io/kyverno/ >/dev/null 2>&1 || true
helm repo update kyverno >/dev/null

helm upgrade --install kyverno kyverno/kyverno \
  --namespace kyverno --create-namespace \
  --version "$CHART_VERSION" \
  --set admissionController.replicas=1 \
  --set backgroundController.enabled=false \
  --set cleanupController.enabled=false \
  --set reportsController.enabled=false \
  --wait --timeout 5m

kubectl get pods -n kyverno
