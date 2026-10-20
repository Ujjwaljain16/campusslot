#!/usr/bin/env bash
# Does the application still work with the network policies on? Used by the policy drill in CI (drills.yml).
#
# Needs the cluster of the drill: the ingress on http://localhost, the Prometheus stack in the namespace
# "monitoring", and the application in the namespace "campusslot" (or NAMESPACE).
set -uo pipefail

NS="${NAMESPACE:-campusslot}"
BASE="${BASE:-http://localhost}"

prom() {   # one number from Prometheus, or 0
  curl -s --get http://localhost:9090/api/v1/query --data-urlencode "query=$1" |
    python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else 0)'
}

echo "== the application with the policies on"
kubectl get pods -n "$NS"

for _ in $(seq 1 30); do curl -fsS "$BASE/api/rooms" >/dev/null && break; sleep 2; done
echo "rooms through the ingress: HTTP $(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/rooms")"

body='{"room_id":1,"purpose":"policy drill","booked_by":"drill","start_time":"2031-01-01T10:00:00Z","end_time":"2031-01-01T11:00:00Z"}'
echo "first booking: HTTP $(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d "$body" "$BASE/api/bookings")"
echo "same slot again: HTTP $(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d "$body" "$BASE/api/bookings")"

kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090 >/dev/null 2>&1 &
forward=$!
trap 'kill $forward 2>/dev/null' EXIT
sleep 50   # more than two scrape intervals, so that a blocked target would have turned red by now
up="$(prom "count(up{namespace=\"$NS\", pod=~\"campusslot-backend.*\"} == 1)")"
all="$(prom "count(up{namespace=\"$NS\", pod=~\"campusslot-backend.*\"})")"
echo "backend targets that Prometheus can scrape: $up of $all"
