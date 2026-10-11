#!/usr/bin/env bash
# Make the application slow on purpose, and follow one slow request from the metric to its trace and to its log line.
#
#   scripts/trace-drill.sh
#
# Needs the monitoring stack, Tempo (scripts/install-tracing.sh), and the application deployed as a plain Deployment
# (rollout.enabled=false: a canary would abort a release with a slow backend before the drill could look at it). The
# ingress and the three data stores are reached through port forwards:
#   kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80 &
#   kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090 &
#   kubectl port-forward -n monitoring svc/tempo 3200:3200 &
#   kubectl port-forward -n monitoring svc/loki 3100:3100 &
# Method and results: docs/engineering/linked-signals.md
#
# The slowness is FAULT_LATENCY_MS=400: every API request waits 400 ms before it is handled, so each one is
# slower than the 0.25 s objective, while the probes stay fast. It is a configuration change of the same image, it is
# ignored when APP_ENV is production, and it is switched off again at the end, even when the drill fails.
set -uo pipefail

NS="${NAMESPACE:-campusslot}"
RELEASE="${RELEASE:-campusslot}"
LATENCY="${FAULT_LATENCY_MS:-400}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHART="$ROOT/helm/campusslot"
PY="${PYTHON:-python}"

upgrade() { helm upgrade "$RELEASE" "$CHART" --namespace "$NS" --reuse-values "$@" >/dev/null; }

wait_rollout() {
  kubectl rollout status "deployment/${RELEASE}-backend" -n "$NS" --timeout=240s
}

for url in "${BASE:-http://localhost:8080}/api/rooms" "http://localhost:9090/-/ready" "http://localhost:3200/ready" "http://localhost:3100/ready"; do
  curl -sf -o /dev/null --max-time 5 "$url" || { echo "cannot reach $url: start the port forwards listed at the top of this script"; exit 2; }
done

trap 'echo "== switching the fault off"; upgrade --set-string backend.env.FAULT_LATENCY_MS=0 && wait_rollout' EXIT

echo "== tracing on, and every API request delayed by ${LATENCY} ms"
upgrade --set tracing.enabled=true --set-string "backend.env.FAULT_LATENCY_MS=${LATENCY}"
wait_rollout || exit 1

echo "== following one slow request"
"$PY" "$ROOT/scripts/trace_chain.py" --base "${BASE:-http://localhost:8080}"
STATUS=$?
exit "$STATUS"
