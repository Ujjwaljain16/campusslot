#!/usr/bin/env bash
# Run the environments of gitops/ on a laptop cluster, promote a build through them with Git, and undo a manual change.
#
#   scripts/gitops-drill.sh setup       # namespaces, database Secrets, Argo CD with the ApplicationSet, dev and staging
#   scripts/gitops-drill.sh promote     # dev takes a new build, staging takes what dev runs, and a wrong promotion is refused
#   scripts/gitops-drill.sh drift       # change the cluster by hand, and measure how long Argo CD takes to undo it
#   scripts/gitops-drill.sh cleanup     # remove the drill branch, the worktree, the applications and the namespaces
#
# All the Git work of the drill happens in a separate worktree (WORKTREE, next to the repository) on a branch of its own
# (BRANCH, default promotion-drill), which is pushed to GitHub because Argo CD follows what is on GitHub. Your own
# branch, your working tree and your uncommitted changes are never touched: nothing here commits to them or resets them.
#
# The prod environment is declared and rendered in CI, but a laptop cannot hold it (it needs the Rollouts controller, the
# database operator, Prometheus, Tempo and an object store), so the drill deploys dev and staging. The images come from
# GHCR. OLD_SHA and NEW_SHA are two commits of this repository whose images exist there (the pipeline built them).
# Method and results: docs/engineering/environments-and-promotion.md
set -uo pipefail

MODE="${1:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRANCH="${BRANCH:-promotion-drill}"
WORKTREE="${WORKTREE:-$ROOT/../campusslot-promotion-drill}"
PY="${PYTHON:-python}"
OLD_SHA="${OLD_SHA:-c0d5a17a0c002264fdf6c7c4be08faf29cb630f2}"
NEW_SHA="${NEW_SHA:-d79ce938f7428ced862bc1a41c24b3624bf1b9de}"
ARGOCD_VERSION="${ARGOCD_VERSION:-10.9.6}"
# The chart pulls Redis from ecr-public.aws.com, which answers 429 (too many requests) to the shared addresses of a CI
# runner. A mirror of the same image can be named here; unset, the chart default is used.
REDIS_REPOSITORY="${REDIS_REPOSITORY:-}"
TIMEOUT="${TIMEOUT:-300}"

now() { date +%s; }
backend_image() { kubectl get deployment campusslot-backend -n "campusslot-$1" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null; }
app_state() { kubectl get application "campusslot-$1" -n argocd -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null; }

# Wait until a command prints what is wanted. Prints the seconds that it took, or fails after TIMEOUT.
wait_until() {   # $1 = description, $2 = wanted text, then the command
  local what="$1" want="$2" start out=""
  shift 2
  start="$(now)"
  while [ $(( $(now) - start )) -lt "$TIMEOUT" ]; do
    out="$("$@")"
    if [ "$out" = "$want" ]; then echo "$what: $(( $(now) - start )) s"; return 0; fi
    sleep 2
  done
  echo "$what: NOT reached within ${TIMEOUT} s (last value: ${out:-none})"
  return 1
}

# Everything below that touches Git or the environment files runs in the worktree.
wt_git() { git -C "$WORKTREE" "$@"; }
wt_promote() { "$PY" "$WORKTREE/scripts/promote.py" "$@"; }
wt_commit() {
  wt_git add gitops/envs
  wt_git -c user.name=drill -c user.email=drill@example.invalid commit -q -m "$1"
}
wt_push() { wt_git push -q --force origin "HEAD:refs/heads/$BRANCH"; }

ensure_worktree() {
  if [ ! -d "$WORKTREE" ]; then
    git -C "$ROOT" worktree add -q -B "$BRANCH" "$WORKTREE" HEAD || exit 1
  fi
}

case "$MODE" in
  setup)
    ensure_worktree
    echo "== the drill branch $BRANCH, in $WORKTREE: every environment at the old build ${OLD_SHA:0:12}"
    wt_promote promote --to dev --sha "$OLD_SHA" >/dev/null
    wt_promote promote --to staging >/dev/null
    wt_promote promote --to prod >/dev/null
    wt_git diff --quiet -- gitops/envs || wt_commit "drill: start every environment at the old build"
    wt_push

    echo "== namespaces and database Secrets (random passwords, only in the cluster)"
    kubectl apply -f "$ROOT/k8s/environments.yaml"
    for env in dev staging; do
      if ! kubectl get secret campusslot-db -n "campusslot-$env" >/dev/null 2>&1; then
        password="$(openssl rand -hex 16)"
        kubectl create secret generic campusslot-db -n "campusslot-$env" \
          --from-literal=POSTGRES_PASSWORD="$password" \
          --from-literal=DATABASE_URL="postgresql+psycopg://campusslot:${password}@campusslot-postgres:5432/campusslot"
      fi
    done

    echo "== Argo CD with the ApplicationSet controller"
    helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
    helm repo update argo >/dev/null
    helm upgrade --install argocd argo/argo-cd --namespace argocd --create-namespace \
      ${REDIS_REPOSITORY:+--set "redis.image.repository=$REDIS_REPOSITORY"} \
      --version "$ARGOCD_VERSION" -f "$ROOT/gitops/argocd-values.yaml" --wait --timeout 8m || {
        # A drill that goes on after this measures nothing: without its Redis, Argo CD cannot compare Git with the cluster.
        echo "Argo CD did not become ready:"
        kubectl get pods -n argocd
        kubectl get events -n argocd --sort-by=.lastTimestamp | tail -n 15
        exit 1
      }

    echo "== the ApplicationSet, for dev and staging, following $BRANCH"
    "$PY" "$ROOT/scripts/promote.py" appset --envs dev,staging --revision "$BRANCH" | kubectl apply -f -
    wait_until "dev is synced and healthy" "Synced/Healthy" app_state dev
    wait_until "staging is synced and healthy" "Synced/Healthy" app_state staging
    echo "dev runs $(backend_image dev)"
    echo "staging runs $(backend_image staging)"
    ;;

  promote)
    ensure_worktree
    echo "== before: dev runs $(backend_image dev | sed 's/.*://' | cut -c1-12), staging runs $(backend_image staging | sed 's/.*://' | cut -c1-12)"

    echo "== 1. dev takes the new build ${NEW_SHA:0:12}"
    wt_promote promote --to dev --sha "$NEW_SHA" || exit 1
    wt_commit "drill: promote ${NEW_SHA:0:12} to dev"
    start="$(now)"
    wt_push
    wait_until "dev runs the new image after the push" "ghcr.io/ujjwaljain16/campusslot-backend:$NEW_SHA" backend_image dev
    wait_until "dev is synced and healthy" "Synced/Healthy" app_state dev
    echo "staging still runs $(backend_image staging | sed 's/.*://' | cut -c1-12): it has not been promoted"

    echo "== 2. a hand edit that gives staging a build that dev does not run is refused"
    base="$(wt_git rev-parse HEAD)"
    sed -i "s/$OLD_SHA/eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee/g" "$WORKTREE/gitops/envs/staging/values.yaml"
    wt_commit "drill: a hand edit of staging to a build that dev does not run"
    # The refusal has to be the rules speaking. A crash of the tool also exits non-zero, and must not count as a pass.
    out="$(wt_promote check --base "$base" 2>&1)"; rc=$?
    if [ "$rc" -eq 0 ]; then
      echo "FAIL: the rule did not stop it"
    elif echo "$out" | grep -q "PROMOTION RULES BROKEN"; then
      echo "PASS: the rule stopped it, as CI would"; echo "$out" | sed 's/^/      /'
    else
      echo "FAIL: the check did not run properly (exit $rc):"; echo "$out" | sed 's/^/      /'
    fi
    wt_git reset -q --hard "$base"   # in the worktree only

    echo "== 3. staging takes what dev runs"
    wt_promote promote --to staging || exit 1
    wt_promote check --base "$base" || exit 1
    wt_commit "drill: promote ${NEW_SHA:0:12} to staging"
    wt_push
    wait_until "staging runs the new image after the push" "ghcr.io/ujjwaljain16/campusslot-backend:$NEW_SHA" backend_image staging
    wait_until "staging is synced and healthy" "Synced/Healthy" app_state staging
    echo "total: $(( $(now) - start )) s from the first push to both environments on the new build"
    ;;

  drift)
    echo "== 1. a person scales the backend of dev by hand"
    kubectl scale deployment campusslot-backend -n campusslot-dev --replicas=3 >/dev/null
    echo "replicas now: $(kubectl get deployment campusslot-backend -n campusslot-dev -o jsonpath='{.spec.replicas}')"
    wait_until "Argo CD puts the replica count back" "1" kubectl get deployment campusslot-backend -n campusslot-dev -o jsonpath='{.spec.replicas}'

    # Two kinds of manual setting, because Argo CD compares the fields that Git declares, and a setting that Git does not
    # mention is a different case from a setting that Git declares with another value. (The first run of this drill
    # expected both to be undone; the first one was not.)
    echo "== 2a. a person adds an environment variable to the backend Deployment that Git does not declare"
    kubectl set env deployment/campusslot-backend -n campusslot-dev DRILL_EXTRA=by-hand >/dev/null
    TIMEOUT=60 wait_until "Argo CD removes the extra variable" "" kubectl get deployment campusslot-backend -n campusslot-dev -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="DRILL_EXTRA")].value}'
    echo "application state meanwhile: $(app_state dev)"
    kubectl set env deployment/campusslot-backend -n campusslot-dev DRILL_EXTRA- >/dev/null   # removed by hand, to leave dev clean

    echo "== 2b. a person changes a setting that Git declares (LOG_LEVEL in the ConfigMap of the backend)"
    declared="$(kubectl get configmap campusslot-backend-config -n campusslot-dev -o jsonpath='{.data.LOG_LEVEL}')"
    echo "declared value: $declared"
    kubectl patch configmap campusslot-backend-config -n campusslot-dev --type merge -p '{"data":{"LOG_LEVEL":"ERROR"}}' >/dev/null
    wait_until "Argo CD puts the declared value back" "$declared" kubectl get configmap campusslot-backend-config -n campusslot-dev -o jsonpath='{.data.LOG_LEVEL}'
    wait_until "dev is synced again" "Synced" kubectl get application campusslot-dev -n argocd -o jsonpath='{.status.sync.status}'

    echo "== 3. a person deletes the frontend Service"
    kubectl delete service campusslot-frontend -n campusslot-dev >/dev/null
    wait_until "Argo CD recreates the Service" "campusslot-frontend" kubectl get service campusslot-frontend -n campusslot-dev -o jsonpath='{.metadata.name}'
    ;;

  cleanup)
    kubectl delete applicationset campusslot -n argocd --ignore-not-found
    kubectl delete application campusslot-dev campusslot-staging campusslot-prod -n argocd --ignore-not-found
    kubectl delete namespace campusslot-dev campusslot-staging --ignore-not-found
    git -C "$ROOT" push -q origin --delete "$BRANCH" 2>/dev/null && echo "deleted the remote branch $BRANCH"
    git -C "$ROOT" worktree remove --force "$WORKTREE" 2>/dev/null && echo "removed the worktree"
    git -C "$ROOT" branch -D "$BRANCH" >/dev/null 2>&1 && echo "deleted the local branch $BRANCH"
    ;;

  *)
    echo "usage: $0 setup|promote|drift|cleanup" >&2
    exit 2
    ;;
esac
