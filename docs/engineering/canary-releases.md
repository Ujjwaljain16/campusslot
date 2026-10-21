# Canary releases, judged by the SLO

Status: **built, and the drill has run** on a kind cluster of a GitHub-hosted runner (20 October 2026, [run 39490639414](https://github.com/Ujjwaljain16/campusslot/actions/runs/39490639414)). The measured numbers are in the results section, next to the predictions. The decision is in [ADR 0015](../adr/0015-canary-releases-judged-by-their-own-metrics.md).

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

The route that was used, with no laptop: push the branch `drill/phase1` (`git push origin v2:refs/heads/drill/phase1`). The workflow `drills.yml` builds a kind cluster, installs the ingress, Prometheus and the Rollouts controller, deploys the chart with `rollout.enabled=true` (the control job with `false`) and runs the three drills. The transcripts are the artifacts of the run.

On a laptop:

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

Run by the workflow [`drills.yml`](../../.github/workflows/drills.yml) (branch `drill/phase1`), not on a laptop. Environment ([environment.txt](../evidence/v2/phase1/environment.txt)): a GitHub-hosted runner with 4 vCPU and 16 GB of memory, one kind node, Kubernetes v1.35.0, the images of commit `2ca20e4`, 2 backend replicas, 10 requests per second through the ingress. The latencies are those of a shared runner and say little about a production cluster. The *behaviour* (what was aborted, when, how many users saw it) is what the drill measures.

| Run | Predicted | Measured | Transcript |
|---|---|---|---|
| Control, plain Deployment, bad release | 450 to 500 failed of 1800 | **521 failed of 1800 (28.9 percent)**, the first at +6.0 s and the last at +179.8 s | [control.txt](../evidence/v2/phase1/control.txt) |
| Canary, bad release | Abort 80 to 95 s after the upgrade, about 25 failed requests | **Aborted at +78.6 s, 45 failed of 1800 (2.5 percent)**; the canary pods served 150 requests (5.0 percent), 49 of them failed | [bad.txt](../evidence/v2/phase1/bad.txt) |
| Canary, good release | 100 percent in 150 to 180 s | **Healthy at +125.1 s**, 0 failed of 2400 | [good.txt](../evidence/v2/phase1/good.txt) |

The same bad release reached **521 users' requests without a canary and 45 with one**: 91 percent fewer failed requests, and the roll back needed no person.

### Where the predictions were wrong

1. **Failed requests of the control run: 521, predicted at most 500.** The prediction did not count the whole window. After the first failure at +6 s there were about 1740 requests, and 30 percent of 1740 is 522. The mistake was in the arithmetic, not in the system.
2. **Failed requests of the canary run: 45, predicted 25.** The prediction assumed that the canary has 10 percent of the traffic until the abort. It did not: the first pause (60 s) ended at +64.1 s and the rollout moved to **50 percent** (step 3), and the abort came at +78.6 s. For about 15 seconds half of the traffic went to the bad version. The abort took 75 s of analysis (45 s initial delay and two more readings, 15 s apart) plus the pod start, which is longer than the first pause. **The honest claim is therefore "aborted in 79 s, at 50 percent of the traffic", not "aborted at 10 percent".** Two ways to get the claim back, to be decided and measured in a later run: a first pause longer than the time to the abort (for example 90 s), or fewer allowed bad readings before the abort.
3. **Good release: 125 s, predicted 150 to 180 s.** I had added a pod start time on top of the two 60 s pauses. With the images pulled, a pod is ready in about 3 s, so the total is the two pauses (120 s) and 5 s.

### After the fix: a first pause of 90 s

The second finding above was fixed by lengthening the first pause from 60 s to 90 s (`rollout.steps` in `values.yaml`), which is longer than the 75 s plus the pod start that the analysis needs to reach a verdict on a bad release. The drill was run again on the same kind of runner ([run 39646092777](https://github.com/Ujjwaljain16/campusslot/actions/runs/39646092777), transcripts in [`docs/evidence/v2/phase1-after-fix`](../evidence/v2/phase1-after-fix)).

| | First run (60 s pause) | After the fix (90 s pause) |
|---|---|---|
| Control, plain Deployment, failed requests | 521 of 1800 (28.9 %) | 535 of 1800 (29.7 %) |
| Canary, bad release: abort | at +78.6 s, **at 50 percent** of the traffic | at +78.7 s, **at 10 percent**: the rollout stayed at step 1 and never reached 50 |
| Canary, bad release: failed requests | 45 of 1800 (2.5 %) | **27 of 1800 (1.5 %)**, against a prediction of about 25 |
| The canary pods served | 150 requests (5.0 %), 49 failed | 83 requests (2.6 %), 27 failed |
| Canary, good release: Healthy | +125.1 s | +155.5 s (two pauses of 90 s and 60 s, and the pod starts) |
| Failed requests of the bad release against the control | 91 % fewer | **95 % fewer** (535 to 27) |

The readings of the canary pods in the bad release were 0.22, 0.35 and 0.35 (the injected failure rate is 0.30), each above the limit of 0.02, so the third reading aborted it. The prediction of about 25 failed requests, which was wrong in the first run, now holds, and for the reason that it was written for: the canary had 10 percent of the traffic until the abort. The cost of the longer pause is a slower good release (about 30 s more). The frontend page answered `200` in all 449 probes again.

### What the known risks turned out to be

| Risk named before the run | Result |
|---|---|
| The canary Ingress might drop the frontend rule | It keeps all the paths (`/api`, `/docs`, `/openapi.json`, `/`) ([ingress-timeline.txt](../evidence/v2/phase1/ingress-timeline.txt)). The frontend page answered `200` in all 450 one-second probes during the rollouts ([frontend-status-counts.txt](../evidence/v2/phase1/frontend-status-counts.txt)) |
| The analysis queries might return no number (the pod hash in the pod name) | They return numbers. The first reading came at the end of the 45 s initial delay, and none was empty ([analysisruns.yaml](../evidence/v2/phase1/analysisruns.yaml)) |
| The first reading might be late, because Prometheus had not discovered the new pods | It was not late. A 15 s scrape interval was enough |

The readings of the bad release: the error ratio of the canary pods was 0.344, 0.334 and 0.316 (the injected failure rate is 0.30), each above the limit of 0.02, so the third reading aborted the rollout. The latency metric stayed at 1.0 (all requests within 0.25 s) in the same analysis, which shows that the failure was caught by the error ratio and not by the latency, as it should be for this fault.

### How the drill ran (and the first run that proved nothing)

The first run of the workflow passed in the control job and failed in the canary job. The control pass was false: the scripts were committed from Windows without the executable bit, so `scripts/canary-drill.sh` printed "Permission denied" and the pipe into `tee` hid the failure. The workflow now uses `bash -eo pipefail`, and the scripts have the bit set in Git. The second run is the one above. A pass that measured nothing is the case that the transcripts exist to catch: the control job of the first run had a transcript with one line.

## Limits that are already known

- The analysis needs traffic. With no requests the reading is empty, and an empty reading is inconclusive, so a quiet cluster pauses the rollout and does not promote it. That is deliberate.
- `helm upgrade --atomic` does not wait for a Rollout. The verdict moves to the Rollout object.
- Only the traffic that goes through the ingress is split. Requests that reach the backend through the frontend's own `/api` proxy always go to the stable version.
- The drill switch is a drill tool. It is ignored when `APP_ENV` is `production`, but the code exists in every image. The guard is tested, and the ADR names it as a consequence of the decision.
