# Canary releases, judged by the SLO

Status: **built and validated in CI (the chart renders, the tests pass). The drill has not been run on a cluster yet.** The measured numbers are added to the results section after the first run, next to the predictions below. The decision is in [ADR 0015](../adr/0015-canary-releases-judged-by-their-own-metrics.md).

## The problem

In v1 a release that never becomes ready is rolled back by `helm upgrade --atomic` ([bad release drill](bad-release-drill.md)). A release that **is ready and still bad** is not caught by anything that Kubernetes or Helm checks: the pod passes its probes, the upgrade finishes, and every user meets the fault until a burn rate alert fires and a person rolls back.

## What was built

```
                      ingress (nginx), weight 10 -> 50 -> 100
   users  ---------->  /api  ----+------------------------+
                                 |                        |
                       stable Service           canary Service
                       (old pods)               (new pods)
                                 ^                        |
                                 |  metrics of the canary pods only
                          Prometheus <--------------------+
                                 |
                       AnalysisTemplate: error ratio < 2 percent, and
                       at least 95 percent of requests within 0.25 s
                                 |
                  good: next step    bad: abort, all traffic back to stable
```

- `helm/campusslot/templates/backend.yaml`: the backend is an Argo `Rollout` when `rollout.enabled` is true, and the same pod template (shared in `_backend-pod.tpl`) as the Deployment otherwise. With the flag off, the rendered chart is the same as v1 (the only difference in the output is the order of the `selector` and `strategy` keys).
- `helm/campusslot/templates/analysis.yaml`: the `AnalysisTemplate`. It uses the same definitions as the availability and latency SLIs of the alerts, but for the canary pods only (the pod name carries the hash of the pod template).
- `backend/app/main.py`: the drill switch. `FAULT_ERROR_RATE` (0 to 1) fails that share of the API requests with a 500, and `FAULT_LATENCY_MS` adds delay. Probes and `/metrics` are never touched, so the pod stays Ready: only the request metrics show the fault. It is ignored when `APP_ENV=production` (tests in `backend/tests/test_faults.py`).
- `scripts/install-rollouts.sh`, `scripts/canary-drill.sh`, `scripts/canary_watch.py`: the controller, the drill, and a recorder of the timeline.

The default stays a plain Deployment, because the CI deploy job tests that path. CI also renders the canary variant and checks that it is valid YAML (kubeconform has no schema for the Argo kinds).

## How to run the drill

A laptop with the application, Prometheus and the Rollouts controller needs about 3.5 GB for the cluster. Close heavy applications first.

```bash
minikube start -p campusslot --memory=3500 --cpus=3
minikube addons enable ingress -p campusslot
minikube addons enable metrics-server -p campusslot
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack -n monitoring --create-namespace \
  --version 91.9.0 -f monitoring/kube-prometheus-stack-values.yaml --set grafana.enabled=false --wait
scripts/install-rollouts.sh
ROLLOUT=1 scripts/deploy-local.sh <commit-sha-of-v2>
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80 &
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090 &

scripts/canary-drill.sh good      # a harmless change goes all the way
scripts/canary-drill.sh bad       # 30 percent failures, ready but bad: the canary aborts it
```

The control run uses the plain Deployment (`rollout.enabled=false`) and the same bad release, with `scripts/canary-drill.sh control`.

## Predictions, written before the first run

Users are watched for 180 seconds by `scripts/probe.py` at 10 requests per second (about 1800 requests).

| Run | What I expect | Why |
|---|---|---|
| Control, plain Deployment | About 30 percent of the requests fail once the new pods are in (roughly 450 to 500 failed of 1800) | A rolling update replaces every pod, all of them are Ready, and nothing judges the requests |
| Canary, bad release | The canary gets about 10 percent of the traffic, so about 3 percent of the requests fail until the abort. The abort comes about 80 to 95 seconds after the upgrade (45 s initial delay, readings every 15 s, the third bad reading aborts, plus the pod start and the scrape delay). That is about 25 failed requests | 10 percent of the traffic times 30 percent failures, for about 85 seconds |
| Canary, good release | It reaches 100 percent without an abort, in about 2.5 to 3 minutes (two pauses of 60 s plus the pod starts) | The analysis passes, and the steps are timed |

If the numbers differ, the difference is the finding. Likely sources: the delay of Prometheus' first rate over the new pods, the ingress weight being approximate for a small number of requests, and a first reading that is empty.

## Results

Not measured yet.

## Limits that are already known

- The analysis needs traffic. With no requests the reading is empty, and an empty reading is inconclusive, so a quiet cluster pauses the rollout and does not promote it. That is deliberate.
- `helm upgrade --atomic` does not wait for a Rollout. The verdict moves to the Rollout object.
- Only the traffic that goes through the ingress is split. Requests that reach the backend through the frontend's own `/api` proxy always go to the stable version.
- The drill switch is a drill tool. It is ignored when `APP_ENV` is `production`, but the code exists in every image. The guard is tested, and the ADR names it as a consequence of the decision.
