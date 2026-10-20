#!/usr/bin/env bash
# Roll out a release that is READY BUT BAD, and measure what the users see.
#
#   scripts/canary-drill.sh control   # plain Deployment (rollout.enabled=false): the bad release replaces every pod
#   scripts/canary-drill.sh bad       # canary Rollout: the same bad release is judged by its own metrics
#   scripts/canary-drill.sh good      # canary Rollout: a harmless change, to see a good release go all the way
#   scripts/canary-drill.sh reset     # turn the fault off again (a normal release)
#
# Needs the local Minikube cluster with the application deployed, the Prometheus stack, the Argo Rollouts
# controller (scripts/install-rollouts.sh), the ingress on http://localhost:8080
#   kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80
# and Prometheus on http://localhost:9090
#   kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090
# Method and results: docs/engineering/canary-releases.md
#
# The "bad" release is a configuration change, never a code change: FAULT_ERROR_RATE=0.3 makes 30 percent of
# the API requests fail with a 500, while /health and /ready keep answering 200. The pod passes every
# probe, so nothing in Kubernetes or in "helm upgrade --wait" can tell, which is the case that a canary
# analysis is for. The setting is ignored when APP_ENV is production.
set -uo pipefail

MODE="${1:-}"
NAMESPACE="${NAMESPACE:-campusslot}"
RELEASE="${RELEASE:-campusslot}"
SECONDS_TOTAL="${SECONDS_TOTAL:-180}"      # how long the users are watched after the upgrade
FAULT_RATE="${FAULT_RATE:-0.3}"
URL="${URL:-http://localhost:8080/api/rooms}"
PROM="${PROM:-http://localhost:9090}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHART="$ROOT/helm/campusslot"
PY="${PYTHON:-python}"

upgrade() {   # helm upgrade with the values of the running release plus the given overrides
  helm upgrade "$RELEASE" "$CHART" --namespace "$NAMESPACE" --reuse-values "$@" >/dev/null
}

run_and_watch() {   # $1 = rollout|deployment
  local kind="$1"
  "$PY" "$ROOT/scripts/probe.py" "$URL" --seconds "$SECONDS_TOTAL" --interval 0.1 --label users > /tmp/drill-probe.txt 2>&1 &
  local probe_pid=$!
  "$PY" "$ROOT/scripts/canary_watch.py" "$kind" --namespace "$NAMESPACE" --seconds "$SECONDS_TOTAL" --prometheus "$PROM"
  wait "$probe_pid" || true
  echo "----"
  cat /tmp/drill-probe.txt
}

case "$MODE" in
  control)
    echo "== plain Deployment, bad release (FAULT_ERROR_RATE=$FAULT_RATE), users watched for ${SECONDS_TOTAL} s"
    kubectl get deployment "$RELEASE-backend" -n "$NAMESPACE" >/dev/null || { echo "no Deployment: install with rollout.enabled=false"; exit 2; }
    upgrade --set-string "backend.env.FAULT_ERROR_RATE=$FAULT_RATE"
    run_and_watch deployment
    ;;
  bad)
    echo "== canary Rollout, bad release (FAULT_ERROR_RATE=$FAULT_RATE), users watched for ${SECONDS_TOTAL} s"
    kubectl get rollout "$RELEASE-backend" -n "$NAMESPACE" >/dev/null || { echo "no Rollout: install with rollout.enabled=true"; exit 2; }
    upgrade --set-string "backend.env.FAULT_ERROR_RATE=$FAULT_RATE"
    run_and_watch rollout
    ;;
  good)
    echo "== canary Rollout, harmless change, users watched for ${SECONDS_TOTAL} s"
    kubectl get rollout "$RELEASE-backend" -n "$NAMESPACE" >/dev/null || { echo "no Rollout: install with rollout.enabled=true"; exit 2; }
    upgrade --set-string "backend.env.RELEASE_NOTE=drill-$(date +%s)"
    run_and_watch rollout
    ;;
  reset)
    upgrade --set-string "backend.env.FAULT_ERROR_RATE=0"
    echo "fault switched off"
    ;;
  *)
    echo "usage: $0 control|bad|good|reset" >&2
    exit 2
    ;;
esac
