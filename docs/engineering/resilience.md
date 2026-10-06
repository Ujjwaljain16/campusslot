# Resilience: measuring what users see when things change or break

## Why this exists

The README claimed zero downtime during a rollout, and the chart is configured for it (`maxUnavailable: 0`, readiness probes, two replicas). A configuration is a promise, not a measurement. I sent a steady stream of requests through the ingress and then made things change and fail, to find out what the promise is worth.

## Method

- `scripts/probe.py` sends one request every 100 ms (about 10 per second) through the ingress and counts the failures. A failure is a timeout (3 seconds), a connection error or any 5xx status.
- The probe runs on my laptop through `kubectl port-forward` to the ingress controller, so the numbers include that path.
- The experiment happens 8 to 10 seconds into the run. The raw transcripts are in [`docs/evidence`](../evidence): `resilience.txt`, `rollout-before.txt`, `rollout-after.txt`, `resilience-db-503.txt`, `alert-drill.txt`.
- The cluster is a single node Minikube, with 2 backend pods, 2 frontend pods and 1 PostgreSQL pod.

## Results

| Experiment | Before | After the change | Change made |
|---|---|---|---|
| Backend rolling update | 7 failed of 2500 requests (0.28 percent), 4 of 4 runs had failures | 0 failed of 1800 (3 runs) | `preStop` delay of 8 seconds |
| Frontend rolling update | 6 failed of 2500 (0.24 percent), 4 of 4 runs had failures | 0 failed of 1800 (3 runs) | same |
| One backend pod killed | 0 failed of 600 | not repeated | none needed |
| Database pod killed | 19 failed of 900 (2.11 percent), all counted as zero by Prometheus | 17 failed of 900 (1.89 percent), all 16 server errors counted by Prometheus | handled 503 with `Retry-After` |
| Alert drill (broken rollout) | no alert existed | alert fired after 185 seconds and resolved 52 seconds after the fix | SLO alert rules |

## Finding 1: the rollout was not zero downtime

Every rolling update lost one or two requests, always as timeouts and never as error responses. The ingress controller log for the same period contains 499 entries (5 in total), which means the client gave up while nginx was still waiting for an answer.

My explanation is that Kubernetes marks a pod for deletion and the pod stops accepting connections immediately, while the ingress controller learns about the removed endpoint a moment later. Requests sent in between go to a pod that is gone. I did not trace the packets, so this is an explanation that fits the symptoms, and the evidence for it is that the fix removed the symptom.

**The change:** a `preStop` hook that sleeps for 8 seconds (`preStopDelaySeconds` in the chart values). The old pod keeps serving while the removal spreads, and only then does it receive the stop signal. The delay is shorter than the 30 second termination grace period.

**Result:** 0 failures in all 6 repeated rollouts after the change, against failures in all 8 rollouts before it.

**Trade-off:** every rollout now takes about 8 seconds longer per pod. That is the price of a clean rollout, and it is small for a service that deploys a few times a day.

**Limit of this evidence:** 10 requests per second, one machine, 3 repeats per case. It shows that the failure pattern disappeared, not that the failure rate is exactly zero under production traffic.

## Finding 2: a database outage was invisible to the availability alerts

When I killed the database pod, users received 18 responses with status 500. Prometheus recorded no 5xx requests at all, and the 5 minute error ratio stayed at 0. The ingress log showed exactly 18 responses with status 500, and the backend log showed unhandled `OperationalError` exceptions.

The reason is where the exception escapes. An unhandled exception becomes a bare 500 produced outside the request metrics middleware, so the application never counts it. The availability SLI and the burn rate alerts built on it would have stayed silent during a database outage, which is the failure they exist to catch.

**The change:** the backend now handles `OperationalError`, `InterfaceError` and pool timeouts with an explicit 503 response and a `Retry-After: 5` header. A handled response passes through the metrics middleware. A test (`test_database_outage_is_a_handled_503_and_is_counted_in_the_metrics`) checks both the status and that `/metrics` contains the 5xx counter.

**Result on the cluster:** 16 responses with status 503 during the outage, and Prometheus counted all 16 (peak of 0.22 failed requests per second over one minute). Before the change it counted none.

**What did not change:** the outage still lasts about 6 seconds, because there is one database pod. The fix improves what we know, not how long it lasts. Shortening it needs a second database replica or a managed database with automatic failover, which is how I would run it in production.

**Would this page anyone?** No, and that is correct. A 6 second blip with 17 failed requests does not meet the fast burn condition (more than 7.2 percent errors over 5 minutes and over 1 hour, for 2 minutes). A database that stays down for several minutes does.

## Finding 3: the alert fires on a stuck rollout, and users never noticed

In the alert drill I pointed the backend at a database that does not exist. The new pod never became ready, and the alert `CampusSlotBackendReplicasUnavailable` went to pending after 62 seconds and fired after 185 seconds. After `kubectl rollout undo` it resolved after 52 seconds. Screenshots: [`alert-firing.png`](../evidence/alert-firing.png) and [`alert-resolved.png`](../evidence/alert-resolved.png).

During the whole drill the probe sent 1650 requests and none failed. The rolling update never removed the two healthy old pods, because `maxUnavailable` is 0. So this alert does not measure user pain. It tells the team that a deployment is stuck, and the bad version never reached users. That is the intended behaviour, and it shows why the configuration and the alert belong together.

The time to fire is mostly the `for: 2m` condition plus the readiness probe and scrape intervals. I kept the 2 minutes on purpose, so that a pod that is slow to start does not page anyone.

## Finding 4: killing one backend pod costs nothing

With two replicas and a readiness probe, deleting one backend pod lost 0 of 600 requests. The Service stopped sending traffic to the pod when it began terminating, and the second pod carried the load.

## What I did not test

- A second database replica or failover, because the chart uses one PostgreSQL pod. A managed Multi-AZ database is the production answer.
- Node failure. Minikube has a single node.
- Failure of the ingress controller itself.
- Behaviour under heavy load while pods are replaced. The load test was dropped from the plan.

## How to repeat it

```bash
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80 &
python scripts/probe.py http://localhost:8080/api/rooms --seconds 60 --interval 0.1
# in a second terminal, 10 seconds into the run:
kubectl rollout restart deployment/campusslot-backend -n campusslot
```
