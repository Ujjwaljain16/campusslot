#!/usr/bin/env bash
# Prove that the HorizontalPodAutoscaler really scales the backend.
#
#   scripts/load-test.sh [load-seconds] [cooldown-seconds]
#
# Load generators run INSIDE the cluster (plain busybox pods in the default namespace calling the
# backend Service), so the test does not depend on a port-forward. Every 10 seconds the script
# prints a timestamped line with the HPA reading, the replica counts and the backend pods, which
# gives a timeline of: idle -> load starts -> CPU rises -> replicas increase -> load stops ->
# replicas return to the minimum.
set -uo pipefail

# Stop Git Bash on Windows from rewriting /bin/sh style arguments into Windows paths.
export MSYS_NO_PATHCONV=1

LOAD_SECONDS="${1:-150}"
COOLDOWN_SECONDS="${2:-240}"
NAMESPACE="${NAMESPACE:-campusslot}"
GENERATORS="${GENERATORS:-4}"
TARGET="http://campusslot-backend.${NAMESPACE}.svc.cluster.local:8000/api/rooms"

sample() {
  local phase="$1"
  local hpa pods
  hpa="$(kubectl get hpa campusslot-backend -n "$NAMESPACE" --no-headers | awk '{print "cpu="$4, "replicas="$7}')"
  pods="$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=backend --no-headers \
    | awk '{printf "%s(%s) ", substr($1, length($1)-4), $3}')"
  printf '%s  %-9s %s  pods: %s\n' "$(date +%H:%M:%S)" "$phase" "$hpa" "$pods"
}

cleanup() {
  kubectl delete pod -l app=campusslot-loadgen --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== baseline =="
sample baseline

echo "== starting $GENERATORS load generators against $TARGET =="
for i in $(seq 1 "$GENERATORS"); do
  kubectl run "loadgen-$i" --image=busybox:1.37 --restart=Never --labels=app=campusslot-loadgen \
    --command -- /bin/sh -c "while true; do wget -q -O /dev/null $TARGET; done" >/dev/null
done

end=$((SECONDS + LOAD_SECONDS))
while [ "$SECONDS" -lt "$end" ]; do sample load; sleep 10; done

echo "== stopping the load =="
cleanup
end=$((SECONDS + COOLDOWN_SECONDS))
while [ "$SECONDS" -lt "$end" ]; do sample cooldown; sleep 10; done

echo "== final =="
sample final
