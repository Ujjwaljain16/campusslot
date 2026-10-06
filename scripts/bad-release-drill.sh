#!/usr/bin/env bash
# Deploy a deliberately broken release with "helm upgrade --atomic" and measure what happens.
#
#   scripts/bad-release-drill.sh healthy      # how long does a normal rollout take?
#   scripts/bad-release-drill.sh cold <sha>   # and one that has to pull a new image? (together they set the timeout)
#   scripts/bad-release-drill.sh broken       # the broken release, with the automatic rollback
#
# Needs the local Minikube cluster with the release deployed (scripts/deploy-local.sh), the ingress
# reachable on http://localhost:8080 (kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller
# 8080:80), and optionally Prometheus on http://localhost:9090. Details and results:
# docs/engineering/bad-release-drill.md
#
# The broken release is a one-line change that is never committed or pushed: the entrypoint listens on
# port 8080 instead of 8000, so the container starts but the Kubernetes probes (port 8000) never
# succeed. Unit tests, the image build and the vulnerability scan cannot see this, because none of
# them starts the container next to its probes.
set -uo pipefail

MODE="${1:-}"
NAMESPACE="${NAMESPACE:-campusslot}"
RELEASE="${RELEASE:-campusslot}"
TIMEOUT="${TIMEOUT:-60}"            # seconds that helm waits before it rolls back (about 3.5 times the slowest normal rollout)
URL="${URL:-http://localhost:8080/api/rooms}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHART="$ROOT/helm/campusslot"
BAD_REPO="campusslot-backend-local"
BAD_TAG="broken"

now() { python -c "import time; print(f'{time.time():.3f}')"; }
since() { python -c "print(f'{$(now) - $1:.1f}')"; }
backend_pods() { kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=backend --no-headers 2>/dev/null; }
ready_count() { kubectl get deploy "${RELEASE}-backend" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null; }
running_image() { kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=backend -o jsonpath='{range .items[*]}{.spec.containers[0].image}{"\n"}{end}' | sort | uniq -c | sed 's/^ *//'; }
revision() { helm history "$RELEASE" -n "$NAMESPACE" --max 1 -o json 2>/dev/null | python -c "import sys,json; h=json.load(sys.stdin); print(h[-1]['revision'] if h else 0)"; }

case "$MODE" in
healthy)
  echo "### Healthy rollouts with --atomic --timeout ${TIMEOUT}s (a harmless setting changes, so every pod is replaced)"
  for n in 1 2 3; do
    t0=$(now)
    helm upgrade "$RELEASE" "$CHART" -n "$NAMESPACE" --reuse-values --set-string backend.env.DRILL_ROLLOUT="$(date +%s)-$n" \
      --atomic --timeout "${TIMEOUT}s" > /dev/null 2>&1
    rc=$?
    echo "rollout $n: helm finished after $(since "$t0") s (exit $rc), ready replicas: $(ready_count)"
    sleep 10
  done
  ;;

cold)
  # Roll to an image that this node has never pulled, then back. A cold pull is the slowest normal rollout.
  other="${2:?usage: $0 cold <other-commit-sha>}"
  current=$(kubectl get deploy "${RELEASE}-backend" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].image}' | sed 's/.*://')
  echo "### Rollout that has to pull a new image (cold), then back to the cached one"
  for tag in "$other" "$current"; do
    t0=$(now)
    helm upgrade "$RELEASE" "$CHART" -n "$NAMESPACE" --reuse-values --set backend.image.tag="$tag" \
      --atomic --timeout 300s > /dev/null 2>&1
    rc=$?
    echo "backend image ${tag:0:7}: helm finished after $(since "$t0") s (exit $rc), ready replicas: $(ready_count)"
    sleep 10
  done
  ;;

broken)
  echo "### Bad release drill, $(date '+%Y-%m-%d %H:%M:%S')"
  echo "timeout for the automatic rollback: ${TIMEOUT} s"
  echo
  echo "### 1. The broken change (never committed, never pushed)"
  work="$(mktemp -d)"
  cp -r "$ROOT/backend" "$work/backend"
  sed -i 's/:-8000/:-8080/' "$work/backend/docker-entrypoint.sh"
  diff <(sed 's/:-8080/:-8000/' "$work/backend/docker-entrypoint.sh") "$work/backend/docker-entrypoint.sh" | sed 's/^/    /'
  for attempt in 1 2 3; do
    minikube image build -p campusslot -t "$BAD_REPO:$BAD_TAG" "$work/backend" > "$work/build.txt" 2>&1 && break
    echo "image build attempt $attempt failed, retrying"; sleep 10
  done
  rm -rf "$work"
  # "minikube image build" can print an error and still exit with 0, so check that the image is really there
  if ! minikube ssh -p campusslot -- "sudo crictl images 2>/dev/null | grep -q '$BAD_REPO.*$BAD_TAG'"; then
    echo "the broken image is not on the node, so this would test a missing image and not the port mismatch: stopping" >&2
    exit 1
  fi
  echo "broken image built in the cluster: $BAD_REPO:$BAD_TAG"

  echo; echo "### 2. Before: a healthy release is running"
  before_rev=$(revision)
  echo "helm revision: $before_rev"; backend_pods | awk '{print "   "$1, $2, $3, "restarts="$4}'
  echo "images: $(running_image | tr '\n' ';')"
  good_image=$(kubectl get deploy "${RELEASE}-backend" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].image}')

  echo; echo "### 3. Users keep calling the API through the Ingress during the whole drill"
  # CONTROL=1 runs the same release without --atomic: helm only waits, and a person has to roll back
  if [ "${CONTROL:-0}" = 1 ]; then HELM_FLAG="--wait"; PROBE_SECONDS=$((TIMEOUT + 330)); else HELM_FLAG="--atomic"; PROBE_SECONDS=$((TIMEOUT + 100)); fi
  python "$ROOT/scripts/probe.py" "$URL" --seconds "$PROBE_SECONDS" --interval 0.1 --label "users" > "${TMPDIR:-/tmp}/drill_probe.txt" 2>&1 &
  probe=$!
  sleep 15

  echo; echo "### 4. Deploy the broken release: helm upgrade $HELM_FLAG --timeout ${TIMEOUT}s"
  T0=$(now)
  echo "T+0.0 s  upgrade started ($(date '+%H:%M:%S'))"
  helm upgrade "$RELEASE" "$CHART" -n "$NAMESPACE" --reuse-values \
    --set backend.image.repository="$BAD_REPO" --set backend.image.tag="$BAD_TAG" \
    $HELM_FLAG --timeout "${TIMEOUT}s" > "${TMPDIR:-/tmp}/drill_helm.txt" 2>&1 &
  helm_pid=$!

  # a timeline, one line when something changes
  last=""; min_ready=99
  while kill -0 $helm_pid 2>/dev/null; do
    state=$(backend_pods | awk '{printf "%s:%s:%s:r%s ", substr($1, length($1)-4), $2, $3, $4}')
    if [ "$state" != "$last" ]; then echo "T+$(since "$T0") s  $state"; last="$state"; fi
    r=$(ready_count); r=${r:-0}; [ "$r" -lt "$min_ready" ] && min_ready=$r
    sleep 1
  done
  wait $helm_pid; helm_exit=$?
  T_HELM=$(now)
  echo "T+$(since "$T0") s  helm exited with code $helm_exit"
  sed 's/^/    helm: /' "${TMPDIR:-/tmp}/drill_helm.txt" | head -4

  if [ "${CONTROL:-0}" = 1 ]; then
    echo; echo "### 5. Control: nothing rolled back by itself. What the cluster looks like now:"
    backend_pods | awk '{print "   "$1, $2, $3, "restarts="$4}'
    echo "   helm status: $(helm status "$RELEASE" -n "$NAMESPACE" -o json | python -c "import sys,json; print(json.load(sys.stdin)['info']['status'])"), ready replicas: $(ready_count) of $(kubectl get deploy "${RELEASE}-backend" -n "$NAMESPACE" -o jsonpath='{.spec.replicas}')"
    echo "   waiting for the alert to fire, because someone has to be told before they can act"
    T_ALERT=""
    for i in $(seq 1 240); do
      if curl -s -G http://localhost:9090/api/v1/query --data-urlencode 'query=ALERTS{alertname="CampusSlotBackendReplicasUnavailable",alertstate="firing"}' | grep -q '"value"'; then T_ALERT=$(now); break; fi
      sleep 1
    done
    if [ -n "$T_ALERT" ]; then
      echo "T+$(since "$T0") s  alert firing, after $(python -c "print(f'{$T_ALERT - $T0:.1f}')") s"
    else
      echo "T+$(since "$T0") s  the alert did not fire within the wait"
    fi
    T_ROLL=$(now)
    helm rollback "$RELEASE" "$before_rev" -n "$NAMESPACE" --wait --timeout 120s > /dev/null 2>&1
    echo "T+$(since "$T0") s  manual helm rollback finished, it took $(since "$T_ROLL") s"
  fi

  echo; echo "### 5. Wait until the previous release serves with all its pods"
  settle_from=$(now)
  until [ "$(ready_count)" = "$(kubectl get deploy "${RELEASE}-backend" -n "$NAMESPACE" -o jsonpath='{.spec.replicas}')" ] \
     && [ "$(running_image | wc -l)" = 1 ] && [ "$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=backend --no-headers | wc -l)" = "$(ready_count)" ]; do
    sleep 1
    [ "$(python -c "print(int($(now) - $settle_from))")" -gt 90 ] && { echo "did not settle"; break; }
  done
  T_BACK=$(now)
  echo "T+$(since "$T0") s  only the previous release is left: $(ready_count) ready replicas, images: $(running_image | tr '\n' ';')"
  echo "lowest number of ready replicas seen while the broken release was failing: $min_ready"

  echo; echo "### 6. What Kubernetes reported about the broken pod (first and last time, relative to the start)"
  signal=$(kubectl get events -n "$NAMESPACE" -o json | python -c "
import sys, json, datetime
t0 = $T0
rows = []
def sec(ts):
    return datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp() - t0
for e in json.load(sys.stdin)['items']:
    name = e['involvedObject'].get('name', '')
    if 'backend' not in name or e['reason'] not in ('Unhealthy', 'Failed', 'BackOff', 'FailedScheduling'):
        continue
    first = e.get('firstTimestamp') or e.get('eventTime') or e.get('lastTimestamp')
    last = e.get('lastTimestamp') or first
    if not first:
        continue
    f, l = sec(first), sec(last)
    if f < -2 or f > $TIMEOUT + 60:
        continue
    rows.append((f, l, e['reason'], name[-5:], e.get('count', 1), (e.get('message') or '')[:100]))
for f, l, reason, name, count, msg in sorted(rows):
    print(f'   first T+{f:5.1f} s, last T+{l:5.1f} s  {reason:<9} {name} (x{count}) {msg}')
if rows:
    print('FIRST_SIGNAL=%.1f' % min(r[0] for r in rows))
")
  echo "$signal" | grep -v '^FIRST_SIGNAL'
  FIRST_SIGNAL=$(echo "$signal" | sed -n 's/^FIRST_SIGNAL=//p')

  echo; echo "### 7. What the monitoring saw"
  if curl -s -m 3 http://localhost:9090/api/v1/query >/dev/null 2>&1; then
    q() { curl -s -G http://localhost:9090/api/v1/query --data-urlencode "query=$1" | python -c "import sys,json; r=json.load(sys.stdin)['data']['result']; print(r[0]['value'][1] if r else 'none')"; }
    echo "   backend replicas unavailable, highest in the last 6 minutes: $(q 'max_over_time(kube_deployment_status_replicas_unavailable{namespace="campusslot",deployment="campusslot-backend"}[6m])')"
    echo "   alert CampusSlotBackendReplicasUnavailable was pending (1 = yes): $(q 'max_over_time(ALERTS{alertname="CampusSlotBackendReplicasUnavailable",alertstate="pending"}[6m])')"
    echo "   alert CampusSlotBackendReplicasUnavailable was firing  (1 = yes): $(q 'max_over_time(ALERTS{alertname="CampusSlotBackendReplicasUnavailable",alertstate="firing"}[6m])')"
  else
    echo "   Prometheus is not reachable on localhost:9090, skipped"
  fi

  echo; echo "### 8. Helm history (what the release looks like afterwards)"
  helm history "$RELEASE" -n "$NAMESPACE" --max 4 | cut -c1-150

  echo; echo "### 9. What the users experienced"
  wait $probe 2>/dev/null
  cat "${TMPDIR:-/tmp}/drill_probe.txt"

  echo; echo "### Result"
  echo "first failure signal from Kubernetes (startup probe): T+${FIRST_SIGNAL:-?} s"
  if [ "${CONTROL:-0}" = 1 ]; then
    echo "helm gave up (timeout ${TIMEOUT} s) without rolling back: T+$(python -c "print(f'{$T_HELM - $T0:.1f}')") s"
    if [ -n "$T_ALERT" ]; then echo "alert firing: T+$(python -c "print(f'{$T_ALERT - $T0:.1f}')") s"; else echo "alert firing: not within the wait"; fi
    echo "a person rolled back by hand: T+$(python -c "print(f'{$T_BACK - $T0:.1f}')") s. Until then the release stayed broken with one pod that never became ready"
  else
    echo "automatic decision by helm: T+$(python -c "print(f'{$T_HELM - $T0:.1f}')") s (the timeout was ${TIMEOUT} s)"
    echo "only the previous release left, broken pod removed: T+$(python -c "print(f'{$T_BACK - $T0:.1f}')") s ($(python -c "print(f'{$T_BACK - $T_HELM:.1f}')") s after the decision, which includes the pod's preStop delay)"
  fi
  echo "ready replicas never fell below: $min_ready"
  echo "revision before: $before_rev, after: $(revision); image running: $(running_image | tr '\n' ';') (expected: $good_image)"
  ;;

*)
  echo "usage: $0 healthy | cold <sha> | broken" >&2; exit 2 ;;
esac
