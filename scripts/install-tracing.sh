#!/usr/bin/env bash
# Install Tempo (the trace store) and the SLO dashboard, and make Grafana able to jump between a metric, a trace and a log line.
#
#   scripts/install-tracing.sh
#
# Run scripts/install-monitoring.sh first (or the leaner install of docs/engineering/canary-releases.md), because the
# data sources that link the three signals are provisioned into Grafana by that release: the Loki data source gets a
# derived field on trace_id that opens the trace, and the Tempo data source can open the logs of a span. Then
# deploy the application with tracing.enabled=true.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPO_CHART_VERSION="${TEMPO_CHART_VERSION:-1.24.4}"   # Tempo 2.9.0

helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update grafana >/dev/null

helm upgrade --install tempo grafana/tempo \
  --namespace monitoring --create-namespace \
  --version "$TEMPO_CHART_VERSION" \
  -f "$ROOT/monitoring/tempo-values.yaml" \
  --wait --timeout 5m

# The Grafana data sources are part of the monitoring release, so the new Tempo data source and the derived field of the
# Loki data source arrive with an upgrade of that release.
GRAFANA_PASSWORD="$(kubectl get secret monitoring-grafana -n monitoring -o jsonpath='{.data.admin-password}' | base64 -d)"
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --reuse-values \
  -f "$ROOT/monitoring/kube-prometheus-stack-values.yaml" \
  --set-string grafana.adminPassword="$GRAFANA_PASSWORD" \
  --wait --timeout 8m

# The SLO dashboard is loaded by the same sidecar as the overview dashboard.
kubectl create configmap campusslot-slo-dashboard -n monitoring \
  --from-file=campusslot-slo.json="$ROOT/monitoring/slo-dashboard.json" \
  --dry-run=client -o yaml \
  | kubectl label --local -f - grafana_dashboard=1 -o yaml \
  | kubectl apply -f -

kubectl get pods -n monitoring -l app.kubernetes.io/name=tempo
echo
echo "Tempo:   http://tempo.monitoring.svc.cluster.local:3200 (data source in Grafana: Tempo)"
echo "Next:    helm upgrade campusslot ... --reuse-values --set tracing.enabled=true"
