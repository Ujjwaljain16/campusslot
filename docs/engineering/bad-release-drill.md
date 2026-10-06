# Bad release drill: what happens when a deployment is broken

## Why this exists

Every other measurement in this project describes a healthy system or a single component that fails. The question that matters on a deployment day is different: what happens to users, and to the release, when the new version is broken? I deployed one deliberately broken release and measured three things: how quickly the failure is recognized, how long the automatic rollback takes, and what users experience.

I wrote down a hypothesis before running it: no user request fails, because the rolling update keeps the old pods serving. I treated it as a hypothesis to test, not as a result to produce.

## The scenario

A one-line change that is never committed or pushed: the container entrypoint listens on port 8080 instead of 8000.

```diff
- exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
+ exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
```

The Kubernetes probes use port 8000, so the new container starts, answers nothing on the port that Kubernetes asks about, and never becomes ready. I chose this bug because it is realistic and because the existing gates cannot see it: the unit tests do not run the entrypoint, the image builds, and the vulnerability scan looks at packages, not behaviour. Only a real environment with the real probes notices.

The release is deployed with `helm upgrade --atomic --timeout 60s`, which waits for the new pods to become ready and rolls the release back by itself if they do not. Users call the API through the Ingress at 10 requests per second for the whole drill ([`scripts/probe.py`](../../scripts/probe.py)). The drill is one script, [`scripts/bad-release-drill.sh`](../../scripts/bad-release-drill.sh).

## Where the timeout comes from

A timeout that is too short rolls back healthy releases that are only slow, and one that is too long keeps a broken release waiting. I measured the normal case first ([`bad-release-healthy.txt`](../evidence/bad-release-healthy.txt), [`bad-release-cold.txt`](../evidence/bad-release-cold.txt)):

| Rollout | Time until Helm reports it ready |
|---|---|
| Healthy, image already on the node (3 runs) | 9.2 to 9.4 s |
| Healthy, the node must pull a new image | 17.3 s |

The slowest normal rollout took 17 seconds, so I set the timeout to 60 seconds, about 3.5 times that. The same 60 seconds is also the budget of the startup probe (30 checks, 2 seconds apart), so Kubernetes and Helm give up at about the same moment.

## Results

Three runs of the broken release with the automatic rollback ([`run1`](../evidence/bad-release-run1.txt), [`run2`](../evidence/bad-release-run2.txt), [`run3`](../evidence/bad-release-run3.txt)):

| Measure | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| First failure signal from Kubernetes (startup probe refused) | 5.2 s | 3.6 s | 5.4 s |
| Automatic decision by Helm | 62.1 s | 62.2 s | 62.3 s |
| Only the previous release left, broken pod removed | 71.6 s | 71.8 s | 72.5 s |
| Lowest number of ready replicas | 2 | 2 | 2 |
| User requests, and how many failed | 1600, 0 | 1600, 0 | 1600, 0 |
| User latency, median and p95 | 17.8, 34.8 ms | 18.4, 36.1 ms | 18.0, 34.2 ms |

- **Detection:** Kubernetes knew within about 5 seconds that the new pod was not answering. Helm decided 62 seconds after the start, because it waits for its timeout. The gap is the price of the timeout, and it is deliberate.
- **Rollback:** the rollback itself is fast. The previous release was already running, so Helm only had to restore the old revision, and the broken pod was gone about 9.5 seconds after the decision. Most of that is the 8 second `preStop` delay of the pod that was removed.
- **User impact:** none. Across the three runs, 0 of 4800 requests failed and the latency did not change. The hypothesis held, and the reason is the combination of three settings that were built earlier for other reasons: the rolling update never removes a healthy pod before its replacement is ready (`maxUnavailable: 0`), the readiness probe keeps the broken pod out of the traffic, and the old pods keep serving until the end.
- **Monitoring:** the alert `CampusSlotBackendReplicasUnavailable` reached the state pending and never fired, because the whole episode was shorter than its 2 minutes. That is the intended behaviour of that alert (a self-healing rollout should not page anybody), and it also means that nobody is told that a rollback happened. There is no Alertmanager, and no notification of an automatic rollback.

## What `--atomic` buys: a control

To see what the mechanism contributes, I ran the same broken release with `--wait` and no `--atomic` ([`bad-release-control-no-atomic.txt`](../evidence/bad-release-control-no-atomic.txt)).

| Measure | With `--atomic` (3 runs) | Without it |
|---|---|---|
| Helm's verdict | rolls back at 62 s | gives up at 62 s, the release is marked `failed`, nothing is rolled back |
| The broken pod | removed at about 72 s | stays, with one pod that never becomes ready |
| Alert | pending, never fires | fires at 187 s (150 s in an earlier run of the control) |
| Recovery | automatic, at about 72 s | needs a person: my script rolled back the instant the alert fired (the command finished at 188 s, the broken pod was gone at 199 s), and a real person would be slower |
| User requests failed | 0 of 4800 | 0 of 3900 |

The control shows what the mechanism does and does not do. It does **not** protect users, because the rolling update and the readiness probe already do that. It removes the stuck release and the need for a person: the system reaches a clean state in about 72 seconds, against a best case of about 190 seconds plus the time that a person needs to notice and react.

## Two other results, for completeness

- **A different kind of bad release, a missing image** ([`bad-release-imagepull.txt`](../evidence/bad-release-imagepull.txt)): my first attempt did not run the planned scenario, because the script reported the broken image as built when it was not on the node (the build had failed without an error code). The new pod could not pull its image and the result was the same: rollback at 62.3 seconds and 0 of 1600 requests failed. The script now checks that the image exists before it starts. I kept the transcript as a second, unplanned example.
- **The first run of the planned scenario** ([`bad-release-first-version-of-script.txt`](../evidence/bad-release-first-version-of-script.txt)) was made with the first version of the script. I then added the first failure signal, the difference between pending and firing, and the lowest ready replica count, and repeated the drill three times. The results did not change.

## Limits

- **One kind of failure.** `--atomic` reacts to a release that never becomes ready. It does not catch a release that becomes ready and then returns errors or answers slowly. That needs the SLO burn rate alerts, and a person or a canary to act on them. I did not build a canary, on purpose.
- **A single node and 10 requests per second.** On a bigger cluster the timeline would be similar, but the numbers belong to this setup.
- **The timeout of the repository's deploy script is 6 minutes** ([`deploy-local.sh`](../../scripts/deploy-local.sh)), not 60 seconds, because the same command also performs first installs where three images must be pulled. With 6 minutes a broken upgrade would be rolled back later than in this drill. The measurements support 60 seconds for upgrades on a warm cluster. I did not change the script, because users were not affected.
- **The pipeline's own reaction was not measured.** The deploy job of the pipeline retries its Helm command three times with `--atomic --timeout 6m`, so a release that never becomes ready could take up to 18 minutes to fail there. That is read from the workflow and not measured, and it is a candidate for a later improvement.
- **The drill ran locally on Minikube,** with the broken image built inside the cluster and never pushed to the registry.

## How to repeat it

```bash
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80 &
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090:9090 &
scripts/bad-release-drill.sh healthy               # normal rollout time
scripts/bad-release-drill.sh broken                # the broken release with the automatic rollback
CONTROL=1 scripts/bad-release-drill.sh broken      # the same without --atomic
```
