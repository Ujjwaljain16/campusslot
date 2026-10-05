#!/usr/bin/env bash
# Install Prometheus, Grafana and Loki with Alloy, and load the CampusSlot dashboard.
#
#   scripts/install-monitoring.sh
#
# Run this BEFORE deploying the application with serviceMonitor.enabled=true, because the
# ServiceMonitor custom resource only exists once the stack's CRDs are installed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHART_VERSION="${CHART_VERSION:-91.9.0}"
LOKI_VERSION="${LOKI_VERSION:-7.3.0}"
ALLOY_VERSION="${ALLOY_VERSION:-1.13.0}"

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null

# The Grafana admin password is random on a first install and reused afterwards.
if kubectl get secret monitoring-grafana -n monitoring >/dev/null 2>&1; then
  GRAFANA_PASSWORD="$(kubectl get secret monitoring-grafana -n monitoring -o jsonpath='{.data.admin-password}' | base64 -d)"
else
  GRAFANA_PASSWORD="$(openssl rand -hex 12)"
fi

# Logs: Loki stores them, Alloy collects the CampusSlot pod logs and ships them to Loki.
helm upgrade --install loki grafana/loki \
  --namespace monitoring --create-namespace --version "$LOKI_VERSION" \
  -f "$ROOT/monitoring/loki-values.yaml" --wait --timeout 8m
helm upgrade --install alloy grafana/alloy \
  --namespace monitoring --version "$ALLOY_VERSION" \
  -f "$ROOT/monitoring/alloy-values.yaml" --wait --timeout 5m

helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --version "$CHART_VERSION" \
  -f "$ROOT/monitoring/kube-prometheus-stack-values.yaml" \
  --set-string grafana.adminPassword="$GRAFANA_PASSWORD" \
  --wait --timeout 8m

# The Grafana sidecar watches for ConfigMaps labelled grafana_dashboard=1 and imports them.
kubectl create configmap campusslot-dashboard -n monitoring \
  --from-file=campusslot-overview.json="$ROOT/monitoring/grafana-dashboard.json" \
  --dry-run=client -o yaml \
  | kubectl label --local -f - grafana_dashboard=1 -o yaml \
  | kubectl apply -f -

kubectl get pods -n monitoring
echo
echo "Grafana:    kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80   (user: admin)"
echo "Prometheus: kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090"
echo "Password:   kubectl get secret monitoring-grafana -n monitoring -o jsonpath='{.data.admin-password}' | base64 -d"
