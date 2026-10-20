#!/usr/bin/env bash
# Try to do things that the policies must refuse, and the things that they must still allow.
#
#   scripts/policy-drill.sh admission    # images: wrong registry, no tag, latest, and (with Kyverno) no attestation
#   scripts/policy-drill.sh network      # connections between pods, and out of the cluster
#
# "admission" needs policies/admission/restrict-images.yaml to be applied (and, for the last check,
# Kyverno with policies/kyverno/verify-image-attestations.yaml). Every admission request is a
# server side dry run, so no pod is created and nothing is pulled.
# "network" needs a cluster whose network plugin enforces NetworkPolicy (minikube start --cni=calico)
# and the chart installed with networkPolicy.enabled=true. Run it once before enabling the policies (the
# control: everything is allowed) and once after.
#
# GOOD_IMAGE   an image that the policies must accept (default: the backend image of the running release)
# BAD_ATTEST   an image of this project built WITHOUT an attestation, for the Kyverno check (optional)
# Method and results: docs/engineering/admission-and-network-policy.md
set -uo pipefail

MODE="${1:-}"
NS="${NAMESPACE:-campusslot}"
PASS=0
FAIL=0

result() {   # $1 = PASS|FAIL, $2 = description, $3 = detail
  if [ "$1" = "PASS" ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); fi
  printf '%-5s %s\n      %s\n' "$1" "$2" "$3"
}

# The test pod meets the "restricted" Pod Security profile of the namespace, so that the only thing that can refuse
# it is the image rule under test. (The first run of this drill used a bare pod: Pod Security refused all of them
# before the image policies were asked, and the checks passed for the wrong reason.)
overrides() {   # $1 = image
  printf '{"spec":{"containers":[{"name":"drill-pod","image":"%s","securityContext":{"allowPrivilegeEscalation":false,"runAsNonRoot":true,"runAsUser":10001,"capabilities":{"drop":["ALL"]},"seccompProfile":{"type":"RuntimeDefault"}}}]}}' "$1"
}

try_pod() {   # $1 = image
  kubectl run drill-pod -n "$NS" --image="$1" --restart=Never --dry-run=server -o name --overrides="$(overrides "$1")" 2>&1
}

# A refusal only counts when it names one of the policies of this project.
POLICY_MESSAGE='campusslot-restrict-images|image not allowed|explicit tag|image attestations verification failed'

expect_denied() {   # $1 = description, $2 = image
  local out
  out="$(try_pod "$2")"
  if [ $? -ne 0 ] && echo "$out" | grep -qE "$POLICY_MESSAGE"; then
    result PASS "$1" "$(echo "$out" | grep -E "$POLICY_MESSAGE" | head -n 1 | cut -c1-260)"
  else
    result FAIL "$1 (it was NOT refused by an image policy)" "$(echo "$out" | tail -n 1 | cut -c1-260)"
  fi
}

expect_allowed() {  # $1 = description, $2 = image
  local out
  out="$(try_pod "$2")"
  if [ $? -eq 0 ]; then
    result PASS "$1" "$out"
  else
    result FAIL "$1 (it was refused)" "$(echo "$out" | tail -n 1 | cut -c1-260)"
  fi
}

# One check of a connection: it must succeed or it must fail, within a few seconds.
expect_connection() {   # $1 = want (open|blocked), $2 = description, then the command to run
  local want="$1" desc="$2"
  shift 2
  if "$@" >/dev/null 2>&1; then got=open; else got=blocked; fi
  if [ "$got" = "$want" ]; then result PASS "$desc" "connection is $got, as intended"; else result FAIL "$desc" "connection is $got, expected $want"; fi
}

case "$MODE" in
  admission)
    GOOD="${GOOD_IMAGE:-$(kubectl get pods -n "$NS" -l app.kubernetes.io/component=backend -o jsonpath='{.items[0].spec.containers[0].image}' 2>/dev/null)}"
    echo "== admission policies, namespace $NS (good image: ${GOOD:-none found})"
    expect_denied  "an image from Docker Hub is refused"                      "nginx:1.27-alpine"
    expect_denied  "an image of the project with the tag latest is refused"   "ghcr.io/ujjwaljain16/campusslot-backend:latest"
    expect_denied  "an image without a tag is refused"                        "postgres"
    [ -n "$GOOD" ] && expect_allowed "the image that is running now is accepted" "$GOOD"
    if [ -n "${BAD_ATTEST:-}" ]; then
      expect_denied "an image of the project without a build attestation is refused (Kyverno)" "$BAD_ATTEST"
    else
      echo "skip  the attestation check: set BAD_ATTEST to an image built without an attestation"
    fi
    ;;
  network)
    echo "== network policies, namespace $NS"
    BACKEND="$(kubectl get pods -n "$NS" -l app.kubernetes.io/component=backend -o jsonpath='{.items[0].metadata.name}')"
    FRONTEND="$(kubectl get pods -n "$NS" -l app.kubernetes.io/component=frontend -o jsonpath='{.items[0].metadata.name}')"
    POSTGRES="$(kubectl get pods -n "$NS" -l app.kubernetes.io/component=postgres -o jsonpath='{.items[0].metadata.name}')"
    # Only a TCP connection is tested, so that "blocked" can never be confused with "the server answered
    # with something that is not HTTP". The backend image has Python and no nc, the other two have busybox nc.
    BACKEND_SVC="${BACKEND_SERVICE:-campusslot-backend}"
    POSTGRES_SVC="${POSTGRES_SERVICE:-campusslot-postgres}"
    PYCONNECT='import socket,sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), 3)'

    expect_connection open    "the backend reaches the database"                kubectl exec -n "$NS" "$BACKEND" -- python -c "$PYCONNECT" "$POSTGRES_SVC" 5432
    expect_connection open    "the frontend reaches the backend"                kubectl exec -n "$NS" "$FRONTEND" -- nc -z -w 3 "$BACKEND_SVC" 8000
    expect_connection blocked "the frontend cannot reach the database"          kubectl exec -n "$NS" "$FRONTEND" -- nc -z -w 3 "$POSTGRES_SVC" 5432
    expect_connection blocked "the backend cannot reach the internet"           kubectl exec -n "$NS" "$BACKEND" -- python -c "$PYCONNECT" 1.1.1.1 80
    expect_connection blocked "the database cannot reach the internet"          kubectl exec -n "$NS" "$POSTGRES" -- nc -z -w 3 1.1.1.1 80
    # A pod in another namespace is not on the allow list for the backend.
    expect_connection blocked "a pod in another namespace cannot reach the backend" \
      kubectl run drill-np -n default --rm -i --restart=Never --image=curlimages/curl:8.10.1 --command -- curl -sf -m 4 -o /dev/null "http://${BACKEND_SVC}.${NS}:8000/health"
    ;;
  *)
    echo "usage: $0 admission|network" >&2
    exit 2
    ;;
esac

echo "----"
echo "passed: $PASS, failed: $FAIL"
[ "$FAIL" -eq 0 ]
